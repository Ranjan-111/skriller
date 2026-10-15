import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from scripts.probes import model_benchmark, model_trial


def test_benchmark_scores_records_and_aggregates_observed_call_usage(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "html": "<p>synthetic</p>",
                    "expected": {"company": "Example"},
                },
                {
                    "id": "two",
                    "html": "<p>synthetic</p>",
                    "expected": {"company": "Fixture"},
                },
            ]
        )
    )
    monkeypatch.setattr(model_benchmark, "DATASET", corpus)
    monkeypatch.setattr(
        model_benchmark,
        "trial_case",
        lambda model, source, expected, include: {
            "model": model,
            "elapsed_seconds": 1.5,
            "model_calls": 1,
            "successful_model_calls": 1,
            "failed_model_calls": 0,
            "usage_reported_calls": 1,
            "token_usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            "status": "passed" if expected["company"] == "Example" else "quality_failed",
        },
    )

    report = model_benchmark.benchmark("local-test")

    assert report["synthetic_only"] is True
    assert report["status"] == "diagnostic_only"
    assert report["calls"] == 2 and report["corpus_size"] == 2
    assert report["correct_records"] == 1 and report["record_accuracy"] == 0.5
    assert report["mean_seconds"] == report["median_seconds"] == 1.5
    assert report["token_usage"] == {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}
    assert report["token_usage_coverage"]["status"] == "complete"
    assert report["cost_usd"] is None


def test_usage_callback_counts_each_invocation_once_and_accepts_reported_usage():
    callback = model_trial.TrialUsageCallback()
    run_id = uuid4()
    callback.on_chat_model_start({}, [], run_id=run_id)
    callback.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="{}",
                            usage_metadata={
                                "input_tokens": 12,
                                "output_tokens": 3,
                                "total_tokens": 15,
                            },
                        )
                    )
                ]
            ],
            llm_output=None,
        ),
        run_id=run_id,
    )
    assert callback.report == {
        "model_calls": 1,
        "successful_model_calls": 1,
        "failed_model_calls": 0,
        "usage_reported_calls": 1,
        "token_usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    }


def test_usage_callback_keeps_missing_or_invalid_usage_unknown():
    callback = model_trial.TrialUsageCallback()
    run_id = uuid4()
    callback.on_llm_start({}, ["prompt"], run_id=run_id)
    callback.on_llm_end(
        LLMResult(generations=[[ChatGeneration(message=AIMessage(content="{}"))]], llm_output=None),
        run_id=run_id,
    )
    assert callback.report["model_calls"] == 1
    assert callback.report["token_usage"] is None


def test_benchmark_does_not_infer_calls_or_usage_from_record_count(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([{"id": "one", "html": "<p>x</p>", "expected": {"company": "x"}}]))
    monkeypatch.setattr(model_benchmark, "DATASET", corpus)
    monkeypatch.setattr(
        model_benchmark,
        "trial_case",
        lambda *_args: {"elapsed_seconds": 1.0, "status": "failed", "token_usage": None},
    )
    report = model_benchmark.benchmark("local-test")
    assert report["calls"] is None
    assert report["calls_observed"] is False
    assert report["token_usage"] is None
    assert report["token_usage_coverage"]["status"] == "unknown"


def test_benchmark_rejects_duplicate_example_ids(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.json"
    case = {"id": "same", "html": "<p>x</p>", "expected": {"company": "x"}}
    corpus.write_text(json.dumps([case, case]))
    monkeypatch.setattr(model_benchmark, "DATASET", corpus)
    with pytest.raises(ValueError, match="unique"):
        model_benchmark.benchmark("local-test")
