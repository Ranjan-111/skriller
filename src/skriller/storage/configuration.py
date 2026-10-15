"""Operator-configured private blob backend shared by API and workers."""

import boto3
from botocore.config import Config

from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend, S3BlobBackend


def configured_storage(settings: Settings) -> EvidenceStorage:
    if settings.object_backend == "local":
        return EvidenceStorage(LocalBlobBackend(settings.object_directory))
    credentials = {}
    for setting, argument in (
        (settings.s3_access_key_id, "aws_access_key_id"),
        (settings.s3_secret_access_key, "aws_secret_access_key"),
        (settings.s3_session_token, "aws_session_token"),
    ):
        if setting is not None:
            credentials[argument] = setting.get_secret_value()
    client = None
    try:
        client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"total_max_attempts": 1},
                signature_version="s3v4",
            ),
            **credentials,
        )
        return EvidenceStorage(S3BlobBackend(client, settings.s3_bucket or ""))
    except Exception:  # noqa: BLE001 - SDK diagnostics can contain credentials or private URLs
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001, S110 - preserve the redacted startup error
                pass
        raise RuntimeError("Private S3 storage could not be verified") from None
