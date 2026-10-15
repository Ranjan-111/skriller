import pytest
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.settings import Settings
from skriller.storage import LocalBlobBackend, S3BlobBackend
from skriller.storage.configuration import configured_storage


def test_local_configuration_never_constructs_cloud_client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "skriller.storage.configuration.boto3.client",
        lambda *a, **k: pytest.fail("Local storage attempted cloud discovery"),
    )
    with configured_storage(Settings(_env_file=None, object_directory=str(tmp_path))) as storage:
        assert isinstance(storage.backend, LocalBlobBackend)


@pytest.mark.parametrize(
    "options",
    [
        {"object_backend": "s3"},
        {"s3_endpoint_url": "http://storage.example.test"},
        {"s3_endpoint_url": "https://user:password@storage.example.test"},
        {"s3_endpoint_url": "https://storage.example.test/?token=private"},
        {"AWS_ACCESS_KEY_ID": "fixture-only"},
        {"AWS_SESSION_TOKEN": "fixture-only"},
    ],
)
def test_storage_configuration_refuses_incomplete_or_unsafe_settings(options):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **options)


def test_blank_credentials_preserve_role_provider_and_validation_errors_hide_inputs():
    settings = Settings(
        _env_file=None, AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="", AWS_SESSION_TOKEN=""
    )
    assert (
        settings.s3_access_key_id
        is settings.s3_secret_access_key
        is settings.s3_session_token
        is None
    )
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, object_backend="s3", AWS_ACCESS_KEY_ID="synthetic-sensitive-key")
    assert "synthetic-sensitive-key" not in str(error.value)


def test_selected_s3_backend_uses_bounded_sdk_and_application_lifecycle(monkeypatch):
    import boto3
    from botocore.stub import Stubber

    original = boto3.client
    created = {}

    def client_factory(service, **options):
        created.update(options)
        client = original(service, **options)
        stub = Stubber(client)
        stub.add_response(
            "get_public_access_block",
            {
                "PublicAccessBlockConfiguration": dict.fromkeys(
                    [
                        "BlockPublicAcls",
                        "IgnorePublicAcls",
                        "BlockPublicPolicy",
                        "RestrictPublicBuckets",
                    ],
                    True,
                )
            },
            {"Bucket": "private-fixture"},
        )
        stub.add_response(
            "get_bucket_acl",
            {
                "Owner": {"ID": "fixture-owner"},
                "Grants": [
                    {
                        "Grantee": {"Type": "CanonicalUser", "ID": "fixture-owner"},
                        "Permission": "FULL_CONTROL",
                    }
                ],
            },
            {"Bucket": "private-fixture"},
        )
        stub.activate()
        close = client.close

        def closed():
            created["closed"] = True
            stub.assert_no_pending_responses()
            close()

        client.close = closed
        return client

    monkeypatch.setattr("skriller.storage.configuration.boto3.client", client_factory)
    settings = Settings(
        _env_file=None,
        environment="test",
        object_backend="s3",
        s3_bucket="private-fixture",
        s3_endpoint_url="https://storage.example.test",
        AWS_ACCESS_KEY_ID="fixture-access",
        AWS_SECRET_ACCESS_KEY="fixture-secret",
    )
    assert "fixture-secret" not in repr(settings)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert isinstance(app.state.evidence_storage.backend, S3BlobBackend)
        assert not created.get("closed")
    assert created["closed"] is True
    assert created["aws_access_key_id"] == "fixture-access"
    assert created["config"].connect_timeout == 3
    assert created["config"].read_timeout == 10
    assert created["config"].retries["total_max_attempts"] == 1


def test_s3_startup_failure_closes_client_and_redacts_errors(monkeypatch):
    class FailingClient:
        closed = False

        def get_public_access_block(self, **_):
            raise RuntimeError("synthetic-private-secret")

        def close(self):
            self.closed = True

    client = FailingClient()
    monkeypatch.setattr("skriller.storage.configuration.boto3.client", lambda *a, **k: client)
    with pytest.raises(RuntimeError, match="could not be verified") as error:
        configured_storage(
            Settings(_env_file=None, object_backend="s3", s3_bucket="private-fixture")
        )
    assert client.closed and "synthetic-private-secret" not in str(error.value)


def test_local_backup_refuses_remote_objects_before_loading_keys(monkeypatch, tmp_path):
    import sys

    from scripts import backup_pilot

    monkeypatch.setattr(
        sys,
        "argv",
        ["backup_pilot", "create", "--key-file", "unused", "--archive", str(tmp_path / "archive")],
    )
    monkeypatch.setattr(
        backup_pilot,
        "Settings",
        lambda: Settings(_env_file=None, object_backend="s3", s3_bucket="private-fixture"),
    )
    monkeypatch.setattr(
        backup_pilot.Keyring, "load", lambda _: pytest.fail("Read key before storage refusal")
    )
    with pytest.raises(SystemExit, match="remote object backup"):
        backup_pilot.main()


@pytest.mark.integration_db
def test_local_to_s3_swap_preserves_authorized_evidence_reference(database, tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from io import BytesIO
    from uuid import uuid4

    import boto3
    from botocore.response import StreamingBody
    from botocore.stub import Stubber

    from skriller.storage import BlobUnavailable

    actor = f"storage-swap-{uuid4()}"
    workspace = database.create_workspace(actor, "Original private store")["id"]
    other = database.create_workspace(actor, "Unrelated workspace")["id"]
    body = b"synthetic stable evidence"
    with (
        configured_storage(Settings(_env_file=None, object_directory=str(tmp_path))) as local,
        database.tenant(actor, workspace) as session,
    ):
        saved = local.store(
            session,
            body,
            source_url="https://example.org/company",
            source_platform="web",
            collected_at=datetime.now(UTC),
        )
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="fixture", aws_secret_access_key="fixture"
    )
    with Stubber(client) as stub:
        stub.add_response(
            "get_public_access_block",
            {
                "PublicAccessBlockConfiguration": dict.fromkeys(
                    [
                        "BlockPublicAcls",
                        "IgnorePublicAcls",
                        "BlockPublicPolicy",
                        "RestrictPublicBuckets",
                    ],
                    True,
                )
            },
            {"Bucket": "private-fixture"},
        )
        stub.add_response(
            "get_bucket_acl",
            {"Owner": {"ID": "fixture-owner"}, "Grants": []},
            {"Bucket": "private-fixture"},
        )
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private-fixture",
                "Key": saved["object_key"],
                "Body": body,
                "ContentType": "application/octet-stream",
                "ServerSideEncryption": "AES256",
                "IfNoneMatch": "*",
            },
        )
        stub.add_response(
            "get_object",
            {
                "ContentLength": len(body),
                "Body": StreamingBody(BytesIO(body), len(body)),
            },
            {"Bucket": "private-fixture", "Key": saved["object_key"]},
        )
        monkeypatch.setattr("skriller.storage.configuration.boto3.client", lambda *a, **k: client)
        with configured_storage(
            Settings(_env_file=None, object_backend="s3", s3_bucket="private-fixture")
        ) as remote:
            remote.backend.put(workspace, saved["object_key"], body)
            with database.tenant(actor, other) as session, pytest.raises(BlobUnavailable):
                remote.retrieve(session, saved["id"])
            with database.tenant(actor, workspace) as session:
                assert remote.retrieve(session, saved["id"]) == body
        stub.assert_no_pending_responses()
