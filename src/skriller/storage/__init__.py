"""Private, backend-neutral evidence blobs; database authorization precedes reads."""

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from skriller.db.repositories import ResearchRepository, scope


class BlobUnavailable(LookupError):
    """Missing, expired, or inaccessible object; no tenant existence disclosure."""


class BlobTooLarge(ValueError):
    """Blob exceeds configured byte budget."""


class BlobIntegrityError(ValueError):
    """Stored bytes do not match immutable evidence digest."""


def validate_key(workspace_id: str, key: str) -> tuple[str, str]:
    workspace = str(UUID(str(workspace_id)))
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != workspace or parts[1] != "evidence":
        raise BlobUnavailable("Object unavailable")
    if not re.fullmatch(r"[0-9a-f]{32}", parts[2]):
        raise BlobUnavailable("Object unavailable")
    return workspace, parts[2]


class BlobBackend(Protocol):
    def put(self, workspace_id: str, key: str, content: bytes) -> None: ...
    def get(self, workspace_id: str, key: str, max_bytes: int) -> bytes: ...
    def delete(self, workspace_id: str, key: str) -> None: ...


class LocalBlobBackend:
    """Private files with descriptor-relative traversal and no symlink following."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).absolute()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError("Object directory cannot be a symlink")
        os.chmod(self.directory, 0o700)

    def _directory_fd(self, workspace_id: str, key: str, *, create: bool) -> tuple[int, str]:
        workspace, name = validate_key(workspace_id, key)
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in (workspace, "evidence"):
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            return descriptor, name
        except OSError as error:
            os.close(descriptor)
            raise BlobUnavailable("Object unavailable") from error

    def put(self, workspace_id: str, key: str, content: bytes) -> None:
        directory, name = self._directory_fd(workspace_id, key, create=True)
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode=0o600,
                dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                os.unlink(name, dir_fd=directory)
                raise
        finally:
            os.close(directory)

    def get(self, workspace_id: str, key: str, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("Positive byte limit required")
        directory, name = self._directory_fd(workspace_id, key, create=False)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(descriptor, "rb") as stream:
                if os.fstat(stream.fileno()).st_size > max_bytes:
                    raise BlobTooLarge("Stored object exceeds byte limit")
                content = stream.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise BlobTooLarge("Stored object exceeds byte limit")
                return content
        except OSError as error:
            raise BlobUnavailable("Object unavailable") from error
        finally:
            os.close(directory)

    def delete(self, workspace_id: str, key: str) -> None:
        directory, name = self._directory_fd(workspace_id, key, create=False)
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass
        finally:
            os.close(directory)


class S3Client(Protocol):
    def get_public_access_block(self, **kwargs: Any) -> dict: ...
    def get_bucket_acl(self, **kwargs: Any) -> dict: ...
    def put_object(self, **kwargs: Any) -> dict: ...
    def get_object(self, **kwargs: Any) -> dict: ...
    def delete_object(self, **kwargs: Any) -> dict: ...


class S3BlobBackend:
    """S3-compatible private bucket; never emits a public or presigned URL.

    A compatible service must expose the privacy checks used here. Unsupported
    privacy verification fails closed rather than silently accepting a public bucket.
    """

    def __init__(self, client: S3Client, bucket: str):
        if not bucket:
            raise ValueError("Private bucket required")
        configuration = client.get_public_access_block(Bucket=bucket)[
            "PublicAccessBlockConfiguration"
        ]
        if not all(
            configuration.get(flag) is True
            for flag in (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
        ):
            raise ValueError("Bucket must block all public access")
        acl = client.get_bucket_acl(Bucket=bucket)
        if any(grant.get("Grantee", {}).get("URI") for grant in acl.get("Grants", [])):
            raise ValueError("Bucket must have no group ACL grants")
        self.client, self.bucket = client, bucket

    def put(self, workspace_id: str, key: str, content: bytes) -> None:
        validate_key(workspace_id, key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType="application/octet-stream",
            ServerSideEncryption="AES256",
            IfNoneMatch="*",
        )

    def get(self, workspace_id: str, key: str, max_bytes: int) -> bytes:
        validate_key(workspace_id, key)
        if max_bytes <= 0:
            raise ValueError("Positive byte limit required")
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {
                "NoSuchKey",
                "AccessDenied",
                "404",
                "403",
            }:
                raise BlobUnavailable("Object unavailable") from error
            raise
        stream = response["Body"]
        try:
            if response["ContentLength"] > max_bytes:
                raise BlobTooLarge("Stored object exceeds byte limit")
            content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise BlobTooLarge("Stored object exceeds byte limit")
            return content
        finally:
            stream.close()

    def delete(self, workspace_id: str, key: str) -> None:
        validate_key(workspace_id, key)
        self.client.delete_object(Bucket=self.bucket, Key=key)


class EvidenceStorage:
    def __init__(self, backend: BlobBackend, *, max_bytes: int = 10 * 1024 * 1024):
        if max_bytes <= 0:
            raise ValueError("Positive byte limit required")
        self.backend, self.max_bytes = backend, max_bytes

    def store(
        self,
        session: Session,
        content: bytes,
        *,
        source_url: str,
        source_platform: str,
        collected_at: datetime,
        expires_at: datetime | None = None,
        excerpt: str | None = None,
    ):
        workspace = scope(session)
        if len(content) > self.max_bytes:
            raise BlobTooLarge("Object exceeds byte limit")
        from skriller.retention import expiry_for

        expires_at = expiry_for(source_platform, collected_at, expires_at)
        if expires_at is not None and (
            expires_at.tzinfo is None or expires_at <= datetime.now(UTC)
        ):
            raise BlobUnavailable("Expiration must be in the future with timezone")
        key = f"{workspace}/evidence/{uuid4().hex}"
        self.backend.put(workspace, key, content)
        try:
            return ResearchRepository.add_evidence(
                session,
                source_url=source_url,
                source_platform=source_platform,
                collected_at=collected_at,
                expires_at=expires_at,
                excerpt=excerpt,
                object_key=key,
                content_hash=hashlib.sha256(content).hexdigest(),
            )
        except BaseException:
            self.backend.delete(workspace, key)
            raise

    def retrieve(self, session: Session, evidence_id: str) -> bytes:
        workspace = scope(session)
        evidence = ResearchRepository.get_evidence(session, evidence_id)
        if evidence is None or not evidence["object_key"]:
            raise BlobUnavailable("Object unavailable")
        expiration = evidence["expires_at"]
        if expiration is not None and expiration <= datetime.now(UTC):
            raise BlobUnavailable("Object expired")
        content = self.backend.get(workspace, evidence["object_key"], self.max_bytes)
        if hashlib.sha256(content).hexdigest() != evidence["content_hash"]:
            raise BlobIntegrityError("Object digest mismatch")
        return content
