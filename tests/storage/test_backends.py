from io import BytesIO
from uuid import uuid4

import pytest

from skriller.storage import (
    BlobTooLarge,
    BlobUnavailable,
    LocalBlobBackend,
    S3BlobBackend,
)


def key():
    workspace = str(uuid4())
    return workspace, f"{workspace}/evidence/{uuid4().hex}"


def test_local_private_roundtrip_and_cross_workspace(tmp_path):
    backend = LocalBlobBackend(tmp_path / "private")
    workspace, object_key = key()
    backend.put(workspace, object_key, b"evidence")
    assert backend.get(workspace, object_key, 8) == b"evidence"
    assert (tmp_path / "private" / object_key).stat().st_mode & 0o777 == 0o600
    with pytest.raises(BlobUnavailable):
        backend.get(str(uuid4()), object_key, 8)
    with pytest.raises(BlobTooLarge):
        backend.get(workspace, object_key, 7)
    with pytest.raises(FileExistsError):
        backend.put(workspace, object_key, b"replacement")
    backend.delete(workspace, object_key)
    with pytest.raises(BlobUnavailable):
        backend.get(workspace, object_key, 8)


def test_local_rejects_traversal_and_symlink_escape(tmp_path):
    backend = LocalBlobBackend(tmp_path / "private")
    workspace, object_key = key()
    with pytest.raises(BlobUnavailable):
        backend.put(workspace, f"{workspace}/evidence/../../../secret", b"secret")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "private" / workspace).symlink_to(outside, target_is_directory=True)
    with pytest.raises(BlobUnavailable):
        backend.put(workspace, object_key, b"secret")
    assert list(outside.iterdir()) == []


class S3ContractClient:
    """Wire-contract double, not a claim of live S3 verification."""

    def __init__(self):
        self.calls = []
        self.body = b"evidence"
        self.configuration = dict.fromkeys(
            ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"),
            True,
        )
        self.grants = []
        self.stream = None

    def get_public_access_block(self, **kwargs):
        return {"PublicAccessBlockConfiguration": self.configuration}

    def get_bucket_acl(self, **kwargs):
        return {"Grants": self.grants}

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {}

    def get_object(self, **kwargs):
        self.stream = BytesIO(self.body)
        return {"ContentLength": len(self.body), "Body": self.stream}

    def delete_object(self, **kwargs):
        self.calls.append(kwargs)
        return {}


def test_s3_privacy_and_wire_contract():
    client = S3ContractClient()
    backend = S3BlobBackend(client, "private-bucket")
    workspace, object_key = key()
    backend.put(workspace, object_key, b"evidence")
    assert client.calls[-1] == {
        "Bucket": "private-bucket",
        "Key": object_key,
        "Body": b"evidence",
        "ContentType": "application/octet-stream",
        "ServerSideEncryption": "AES256",
        "IfNoneMatch": "*",
    }
    assert backend.get(workspace, object_key, 8) == b"evidence"
    assert client.stream.closed
    with pytest.raises(BlobTooLarge):
        backend.get(workspace, object_key, 7)
    assert client.stream.closed
    with pytest.raises(BlobUnavailable):
        backend.get(str(uuid4()), object_key, 8)
    client.configuration["BlockPublicPolicy"] = False
    with pytest.raises(ValueError, match="public access"):
        S3BlobBackend(client, "public")
    client.configuration["BlockPublicPolicy"] = True
    client.grants = [{"Grantee": {"URI": "http://acs.amazonaws.com/groups/global/AllUsers"}}]
    with pytest.raises(ValueError, match="group ACL"):
        S3BlobBackend(client, "public")


def test_storage_rejects_invalid_input_before_backend_write(tmp_path):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.orm import Session

    from skriller.storage import EvidenceStorage

    backend = LocalBlobBackend(tmp_path / "private")
    service = EvidenceStorage(backend, max_bytes=8)
    with Session() as session:
        # Only pure validation is exercised; this is not repository authorization proof.
        session.info["workspace_id"] = str(uuid4())
        for expiration in (datetime.now(), datetime.now(UTC) - timedelta(seconds=1)):
            with pytest.raises(BlobUnavailable, match="Expiration"):
                service.store(
                    session,
                    b"evidence",
                    source_url="https://example.test",
                    source_platform="web",
                    collected_at=datetime.now(UTC),
                    expires_at=expiration,
                )
        with pytest.raises(BlobTooLarge):
            service.store(
                session,
                b"too large",
                source_url="https://example.test",
                source_platform="web",
                collected_at=datetime.now(UTC),
            )
    assert list((tmp_path / "private").iterdir()) == []


def test_s3_sdk_request_validation_and_typed_missing_response():
    import boto3
    from botocore.stub import Stubber

    # SDK validation only: no network, service, or production credential is involved.
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="contract-test",
        aws_secret_access_key="contract-test",
    )
    workspace, object_key = key()
    with Stubber(client) as stub:
        stub.add_response(
            "get_public_access_block",
            {
                "PublicAccessBlockConfiguration": dict.fromkeys(
                    (
                        "BlockPublicAcls",
                        "IgnorePublicAcls",
                        "BlockPublicPolicy",
                        "RestrictPublicBuckets",
                    ),
                    True,
                )
            },
            {"Bucket": "private-bucket"},
        )
        stub.add_response("get_bucket_acl", {"Grants": []}, {"Bucket": "private-bucket"})
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private-bucket",
                "Key": object_key,
                "Body": b"evidence",
                "ContentType": "application/octet-stream",
                "ServerSideEncryption": "AES256",
                "IfNoneMatch": "*",
            },
        )
        stub.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            http_status_code=404,
            expected_params={"Bucket": "private-bucket", "Key": object_key},
        )
        backend = S3BlobBackend(client, "private-bucket")
        backend.put(workspace, object_key, b"evidence")
        with pytest.raises(BlobUnavailable):
            backend.get(workspace, object_key, 8)
        stub.assert_no_pending_responses()
