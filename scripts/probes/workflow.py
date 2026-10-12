"""Opt-in real broker-to-free-search probe; no browser/user tokens or paid keys."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from skriller.contracts import Limits, SearchPlan
from skriller.db import ConversationRepository, Database, JobRepository
from skriller.jobs.outbox import submit
from skriller.research.service import dispatch, result_rows
from skriller.settings import Settings


def probe():
    settings = Settings()
    database = Database(settings.application_database_url)
    actor = "local-workflow-probe-" + uuid4().hex
    workspace = database.create_workspace(actor, "Live workflow probe")["id"]
    started = time.monotonic()
    try:
        with database.tenant(actor, workspace) as session:
            conversation = ConversationRepository.create(session, "Public source probe")
            ConversationRepository.add_message(
                session, conversation["id"], "user", "OpenAI company official website"
            )
            plan = SearchPlan(
                workspace_id=workspace,
                conversation_id=conversation["id"],
                revision=1,
                entity_type="company",
                sources=["web"],
                limits=Limits(
                    result_limit=2,
                    search_calls=1,
                    fetch_attempts=0,
                    llm_calls=0,
                    token_cap=0,
                    deadline_seconds=90,
                ),
            )
            revision = ConversationRepository.revise_plan(
                session, conversation["id"], plan.model_dump(mode="json")
            )
            job = submit(session, conversation["id"], revision["id"], uuid4().hex)
        dispatch(database, settings.broker_url, actor, workspace)
        for _ in range(90):
            with database.tenant(actor, workspace) as session:
                current = JobRepository.get(session, job["id"])
                if current["state"] in {"completed", "partial", "failed", "cancelled"}:
                    rows = result_rows(session, job["id"])
                    return {
                        "state": current["state"],
                        "result_count": len(rows),
                        "all_snippets_unverified": all(
                            row["evidence_kind"] == "search_snippet"
                            and row["qualification"] == "unverified"
                            for row in rows
                        ),
                        "source": "exa_keyless",
                        "paid_key_used": False,
                        "firebase_user_roundtrip": False,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                    }
            time.sleep(0.5)
        return {"state": "timeout", "paid_key_used": False}
    finally:
        database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("Explicit --live is required")
    report = probe()
    Path("docs/completions/WORKFLOW-LIVE.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
