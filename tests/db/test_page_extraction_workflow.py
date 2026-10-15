"""Saved real HTTP evidence reaches the copied graph and scoped claim ledger."""

from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
import test_fetch
from langchain_core.messages import AIMessage
from test_collection_workflow import discover

from skriller.db import ResearchRepository
from skriller.db.schema import attempts
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import current_usage
from skriller.research.collection import execute_collection
from skriller.research.page_extraction import execute_page_extraction, preset_for_source_url
from skriller.settings import Settings
from skriller.storage import EvidenceStorage, LocalBlobBackend

pytestmark = pytest.mark.integration_db
proxy = test_fetch.proxy


class ModelFixture:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        assert config["callbacks"] == [] and "untrusted_source" in messages[1].content
        return AIMessage(
            content='{"claims":['
            '{"field":"company_name","value":"Aurora Ledger","quote":"Aurora Ledger"},'
            '{"field":"private_email","value":"invented@example.com","quote":"Aurora Ledger"},'
            '{"field":"employee_count","value":250,"quote":"25"}]}',
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


class CareersModelFixture:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        prompt = "\n".join(str(message.content) for message in messages)
        assert "job_posted_date" in prompt and "careers_url" in prompt
        assert config["callbacks"] == [] and "untrusted_source" in prompt
        return AIMessage(
            content=(
                '{"claims":['
                '{"field":"job_title","value":"engineers","quote":"Hiring engineers"},'
                '{"field":"job_posted_date","value":"10 October 2026",'
                '"quote":"10 October 2026"},'
                '{"field":"company_name","value":"Aurora Ledger",'
                '"quote":"Aurora Ledger"}]}'
            ),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


class TeamModelFixture:
    async def ainvoke(self, messages, config):
        prompt = "\n".join(str(message.content) for message in messages)
        assert "person_name" in prompt and "team_page_url" in prompt
        assert config["callbacks"] == [] and "untrusted_source" in prompt
        return AIMessage(
            content=(
                '{"claims":['
                '{"field":"person_name","value":"Mira Rao","quote":"Mira Rao"},'
                '{"field":"job_title","value":"Founder","quote":"Founder"},'
                '{"field":"employee_count","value":25,"quote":"25"}]}'
            ),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org/about?next=/jobs", "company"),
        ("https://example.org/team", "team"),
        ("https://example.org/careers", "careers"),
        ("https://example.org/services", "services"),
        ("https://example.org/contact", "contact"),
        ("https://example.org/directory", "directory"),
        ("https://careers.example.org/overview", "directory"),
    ],
)
def test_page_preset_router_uses_only_explicit_url_path(url, expected):
    assert preset_for_source_url(url) == expected


def test_team_page_uses_team_preset_and_rejects_company_fields(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, _ = proxy
    actor = f"page-team-{uuid4()}"
    client, accepted, _, tasks, _ = discover(
        database, monkeypatch, actor, endpoint, ["team"], extraction=True
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    execute_collection(database, tasks[0], endpoint, storage=storage, enable_extraction=True)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == accepted["job_id"],
                    attempts.c.stage == "extracting",
                )
            )
            .mappings()
            .one()
        )
    outcome = execute_page_extraction(
        database,
        {**tasks[0], "attempt_id": attempt["id"]},
        storage=storage,
        model=LocalStructuredModel(model_instance=TeamModelFixture()),
    )
    assert outcome["status"] == "checkpointed" and requests == ["/team"]
    results = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"]
    observations = results[0]["extraction"]["observations"]
    assert {(row["field"], row["value"]) for row in observations} == {
        ("person_name", "Mira Rao"),
        ("job_title", "Founder"),
    }
    assert all(row["status"] == "unverified" for row in observations)


def test_careers_page_uses_careers_preset_and_keeps_posting_date_unverified(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, _ = proxy
    actor = f"page-careers-{uuid4()}"
    client, accepted, _, tasks, _ = discover(
        database, monkeypatch, actor, endpoint, ["careers"], extraction=True
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    execute_collection(database, tasks[0], endpoint, storage=storage, enable_extraction=True)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == accepted["job_id"],
                    attempts.c.stage == "extracting",
                )
            )
            .mappings()
            .one()
        )
    task = {**tasks[0], "attempt_id": attempt["id"]}
    model = CareersModelFixture()
    outcome = execute_page_extraction(
        database,
        task,
        storage=storage,
        model=LocalStructuredModel(model_instance=model),
    )
    assert outcome["status"] == "checkpointed"
    assert requests == ["/careers"]
    results = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"]
    observations = results[0]["extraction"]["observations"]
    assert {(row["field"], row["value"]) for row in observations} == {
        ("job_title", "engineers"),
        ("job_posted_date", "10 October 2026"),
    }
    assert all(row["status"] == "unverified" for row in observations)
    assert all(row["quote"] in {"Hiring engineers", "10 October 2026"} for row in observations)


def prepare_page(database, monkeypatch, endpoint, tmp_path):
    actor = f"page-extraction-{uuid4()}"
    client, accepted, _, tasks, _ = discover(
        database, monkeypatch, actor, endpoint, ["company"], extraction=True
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    execute_collection(database, tasks[0], endpoint, storage=storage, enable_extraction=True)
    assert client.get(f"/v1/jobs/{accepted['job_id']}").json()["stage"] == "extracting"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        attempt = (
            session.execute(
                sa.select(attempts).where(
                    attempts.c.job_id == accepted["job_id"],
                    attempts.c.stage == "extracting",
                )
            )
            .mappings()
            .one()
        )
    return actor, client, accepted, {**tasks[0], "attempt_id": attempt["id"]}, storage


def test_saved_page_graph_claims_citations_budgets_and_replay(
    database, monkeypatch, proxy, tmp_path
):
    endpoint, requests, _ = proxy
    actor, client, accepted, task, storage = prepare_page(database, monkeypatch, endpoint, tmp_path)
    fixture = ModelFixture()
    model = LocalStructuredModel(model_instance=fixture)
    outcome = execute_page_extraction(database, task, storage=storage, model=model)
    assert outcome["status"] == "checkpointed"
    assert (
        execute_page_extraction(database, task, storage=storage, model=model)["status"]
        == "checkpointed"
    )
    assert 1 <= fixture.calls <= 2 and requests == ["/company"]
    response = client.get(f"/v1/jobs/{accepted['job_id']}/results")
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert response.json()["state"] == "completed" and result["qualification"] == "unverified"
    assert result["extraction"]["rejected_claims"] >= 2
    observed = result["extraction"]["observations"]
    assert len(observed) == 1 and observed[0]["value"] == "Aurora Ledger"
    assert observed[0]["status"] == "unverified" and observed[0]["quote"] == "Aurora Ledger"
    assert len(observed[0]["evidence_ids"]) == 1
    citation = client.get(f"/v1/jobs/{accepted['job_id']}/evidence/{observed[0]['evidence_ids'][0]}")
    assert citation.status_code == 200 and citation.json()["collected_at"]
    with database.tenant(actor, accepted["workspace_id"]) as session:
        claims = ResearchRepository.claims_for(session, result["id"])
        assert len(claims) == 1 and claims[0]["status"] == "unverified"
        _, usage = current_usage(session, accepted["job_id"])
        assert (
            usage["llm_calls"] == fixture.calls
            and usage["tokens"] == 30 * fixture.calls
            and usage["fetch_attempts"] == 1
        )
    assert "object_key" not in response.text and "_collection_" not in response.text


@pytest.mark.parametrize("stop", ["cancel", "corrupt"])
def test_cancelled_or_corrupt_saved_evidence_never_calls_model(
    database, monkeypatch, proxy, tmp_path, stop
):
    endpoint, requests, _ = proxy
    actor, client, accepted, task, storage = prepare_page(database, monkeypatch, endpoint, tmp_path)
    fixture = ModelFixture()
    if stop == "cancel":
        assert client.post(f"/v1/jobs/{accepted['job_id']}/cancel").status_code == 200
    else:
        entity_id = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()["results"][0]["id"]
        with database.tenant(actor, accepted["workspace_id"]) as session:
            entity = ResearchRepository.get_entity(session, entity_id)
            record = ResearchRepository.get_evidence(
                session, entity["attributes"]["_collection_body_evidence_id"]
            )
            (Path(tmp_path) / record["object_key"]).write_bytes(b"corrupted fixture")
    outcome = execute_page_extraction(
        database, task, storage=storage, model=LocalStructuredModel(model_instance=fixture)
    )
    assert fixture.calls == 0 and requests == ["/company"]
    if stop == "cancel":
        assert outcome["status"] == "not_dispatchable"
    else:
        assert outcome["status"] == "checkpointed"
        result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
        assert result["state"] == "partial"
        assert result["results"][0]["extraction"]["failure_code"] == "evidence_missing"


@pytest.mark.live
def test_real_local_ollama_saved_page_trial(database, monkeypatch, proxy, tmp_path):
    import json
    from time import monotonic

    endpoint, requests, _ = proxy
    actor, client, accepted, task, storage = prepare_page(database, monkeypatch, endpoint, tmp_path)
    started = monotonic()
    local = LocalStructuredModel()
    invocation = local.invocation_model
    diagnostics = []

    def observed_invocation(schema):
        transport = invocation(schema)

        class SyntheticTransport:
            async def ainvoke(self, messages, config):
                try:
                    return await transport.ainvoke(messages, config)
                except Exception as exc:
                    # Only this explicit local synthetic fixture records the
                    # server error; product provider errors remain redacted.
                    diagnostics.append({"type": type(exc).__name__, "message": str(exc)[:300]})
                    raise

        return SyntheticTransport()

    monkeypatch.setattr(local, "invocation_model", observed_invocation)
    outcome = execute_page_extraction(
        database,
        task,
        storage=storage,
        model=local,
        settings=Settings(_env_file=None, model_provider="ollama", ollama_model="llama3.2:3b"),
    )
    result = client.get(f"/v1/jobs/{accepted['job_id']}/results").json()
    observed = result["results"][0].get("extraction", {}).get("observations", [])
    factual_pass = any(
        row["field"] == "company_name" and row["value"] == "Aurora Ledger" for row in observed
    )
    with database.tenant(actor, accepted["workspace_id"]) as session:
        cost, usage = current_usage(session, accepted["job_id"])
    report = {
        "model": "llama3.2:3b",
        "provider": "local_ollama",
        "synthetic_fixture": True,
        "status": "passed" if factual_pass else "quality_failed",
        "worker_status": outcome["status"],
        "elapsed_seconds": round(monotonic() - started, 3),
        "usage": usage,
        "cost_usd": str(cost),
        "extraction": result["results"][0].get("extraction"),
        "synthetic_transport_diagnostics": diagnostics,
        "limitations": [
            "One synthetic fixture; this is not a release quality benchmark.",
            "Source identity and qualification remain unverified.",
        ],
    }
    Path("docs/completions/LOCAL-PAGE-PIPELINE-LIVE.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    assert requests == ["/company"] and usage["llm_calls"] <= 2
    assert factual_pass, report
