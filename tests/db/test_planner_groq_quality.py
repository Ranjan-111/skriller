"""Opt-in Groq comparison using the unchanged local planner diagnostic labels."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
import test_planner_quality as diagnostics

from skriller.extraction.groq import GROQ_MODEL, GroqStructuredModel
from skriller.settings import Settings

BENCHMARK_MODEL = os.environ.get("SKRILLER_GROQ_BENCH_MODEL", GROQ_MODEL)

pytestmark = [
    pytest.mark.integration_db,
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("SKRILLER_RUN_GROQ_PLANNER_TESTS") != "1",
        reason="Explicit bounded synthetic Groq evaluation opt-in required",
    ),
]


@pytest.fixture(scope="module")
def planning_report(tmp_path_factory):
    root = Path(__file__).parents[2]
    names = [
        "src/skriller/research/planner.py",
        "src/skriller/extraction/models.py",
        "src/skriller/extraction/groq.py",
        "tests/db/test_planner_quality.py",
        "tests/db/test_planner_groq_quality.py",
    ]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    rows = {
        key: {"id": key, "outcome": "not_executed", "calls": 0}
        for key in [*(row[0] for row in diagnostics.CASES), "private-output", "ambiguous-location"]
    }
    yield rows
    report = {
        "schema_version": 1,
        "dimension": "prompt_planning",
        "source_group": "synthetic_fixture",
        "model_mode": "actual_groq_free_tier",
        "model": BENCHMARK_MODEL,
        "recorded_at": datetime.now(UTC).isoformat(),
        "case_denominator": len(rows),
        "case_assertions_passed": sum(row["outcome"] == "passed" for row in rows.values()),
        "actual_model_calls": sum(row["calls"] for row in rows.values()),
        "source_calls": 0,
        "automatic_retries": 0,
        "release_gate_passed": False,
        "release_prompt_target": 50,
        "scope": "Same five synthetic local diagnostic assertions; not full-plan recall or representative release quality. No provider/default configuration changed. Failed and unexecuted cases remain in the denominator.",
        "implementation_and_corpus_sha256": hashes,
        "cases": list(rows.values()),
    }
    output = tmp_path_factory.mktemp("groq-planner-quality") / "report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    if os.environ.get("SKRILLER_WRITE_QUALITY_REPORTS") == "1":
        name = (
            "PLANNER-QUALITY-GROQ-120B.json"
            if BENCHMARK_MODEL.endswith("120b")
            else "PLANNER-QUALITY-GROQ.json"
        )
        (root / "docs/completions" / name).write_text(output.read_text())


@pytest_asyncio.fixture(autouse=True)
async def groq_diagnostic(monkeypatch):
    key = Settings().groq_api_key
    if key is None:
        pytest.fail("Configure GROQ_API_KEY in ignored local configuration")
    clients = []

    class DiagnosticGroq(GroqStructuredModel):
        def __init__(self, bounds, row):
            # Explicit opt-in is synthetic benchmark authorization; this does
            # not alter the application's provider/free-tier configuration.
            super().__init__(
                key,
                free_tier_confirmed=True,
                model=BENCHMARK_MODEL,
                bounds=bounds.model_copy(update={"output_tokens": 1024}),
            )
            self.row = row
            row["output_token_cap"] = self.bounds.output_tokens
            clients.append(self)

        def invocation_model(self, schema):
            delegate = super().invocation_model(schema)
            row = self.row

            class Capture:
                async def ainvoke(self, messages, config):
                    row["calls"] += 1
                    try:
                        message = await delegate.ainvoke(messages, config=config)
                    except Exception as error:
                        row["provider_status"] = getattr(error, "status_code", None)
                        code = getattr(error, "code", None)
                        if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code):
                            row["provider_error_code"] = code
                        body = getattr(error, "body", None)
                        generated = (
                            body.get("failed_generation") if isinstance(body, dict) else None
                        )
                        if isinstance(generated, str) and len(generated) <= 16384:
                            row["rejected_output_characters"] = len(generated)
                            row["rejected_output_starts_json"] = generated.lstrip().startswith("{")
                            try:
                                rejected = json.loads(generated)
                            except ValueError:
                                row["rejected_output_is_json"] = False
                            else:
                                if isinstance(rejected, dict):
                                    row["rejected_structured_output"] = rejected
                        raise
                    text = message.content
                    row["synthetic_response"] = text[:16384] if isinstance(text, str) else None
                    row["response_truncated"] = isinstance(text, str) and len(text) > 16384
                    row["usage_metadata"] = message.usage_metadata
                    return message

            return Capture()

    monkeypatch.setattr(diagnostics, "DiagnosticModel", DiagnosticGroq)
    try:
        yield
    finally:
        for client in clients:
            await client.aclose()


@pytest.mark.parametrize("key,prompt,entity,must,excluded,preferred,sources", diagnostics.CASES)
async def test_groq_preserves_same_labeled_intent(
    database, key, prompt, entity, must, excluded, preferred, sources, planning_report
):
    await diagnostics.test_local_planner_preserves_labeled_intent(
        database, key, prompt, entity, must, excluded, preferred, sources, planning_report
    )


async def test_groq_private_output(database, planning_report):
    await diagnostics.test_local_planner_rejects_private_output(database, planning_report)


async def test_groq_ambiguous_location(database, planning_report):
    await diagnostics.test_local_planner_pauses_ambiguous_geography(database, planning_report)
