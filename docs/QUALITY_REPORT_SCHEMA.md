# Quality report aggregation contract

`scripts/quality_reports.py` validates each report before creating an aggregate. It accepts the existing scalar extraction and repair reports plus a common labelled-case report for any of `field_extraction`, `qualification`, `identity`, or `repair`.

The common JSON shape is:

```json
{
  "schema_version": 1,
  "dimension": "qualification",
  "source_group": "synthetic_fixture",
  "model_mode": "deterministic_fixture",
  "cases": [
    {"id": "case-1", "expected": "accept", "outcome": "accepted"},
    {"id": "case-2", "expected": "reject", "outcome": "unknown"},
    {"id": "case-3", "expected": "reject", "outcome": "not_executed"}
  ]
}
```

`expected` is `accept` or `reject`; `outcome` is `accepted`, `rejected`, `unknown`, or `not_executed`. Unknown and not-executed cases remain in the source denominator and do not count as correct. IDs must be unique within each run. `source_group` must describe the evidence source actually measured; absent provenance is labelled `source_unreported`. A synthetic fixture is never labelled as LinkedIn, Reddit, or another live platform.

Every report is retained as its own run with a content hash and denominator. Repeated runs are not added together because they may share cases. Dimensions without a compatible labelled report are marked `unmeasured`, with no implied zero score or pass. Legacy extraction and repair reports are checked against their per-case outcomes and declared scalar counts; repair gates are recalculated from the report's unchanged declared threshold and mismatch allowance.

Inputs are capped at 32 reports, 2 MiB per file and 1,000 case rows per report. Adversarial wrong-target outcomes remain visible as failed evidence, rather than being discarded as invalid reports. Common reports expose positive/negative and predicted-acceptance denominators separately: precision is true positives divided by predicted acceptances, or null when there are none. Unknown and unexecuted cases remain in the total denominator. Source-group measurements retain their original report paths and hashes; aggregation does not verify that a claimed source/model execution occurred.

The seeded qualification report defines rejection as a record that cannot be confirmed; its raw `observed_status` and `unknown_criteria` retain near-match/exclusion/unknown distinctions. Its exact-label metric separately checks the full expected status. Seeding reviewed facts is never described as extraction or source access.

Generate the current local evidence roll-up with:

```sh
uv run python scripts/quality_reports.py \
  --input field_extraction=docs/completions/OLLAMA-llama3.2-3b-benchmark.json \
  --input repair=docs/completions/REPAIR-QUALITY-LOCAL-INITIAL.json \
  --input repair=docs/completions/REPAIR-QUALITY-LOCAL-STABLE-ATTRIBUTES.json \
  --input repair=docs/completions/REPAIR-QUALITY-LOCAL-ENUM.json \
  --input repair=docs/completions/REPAIR-QUALITY-LOCAL.json \
  --input qualification=docs/completions/QUALIFICATION-QUALITY-LOCAL.json \
  --input identity=docs/completions/IDENTITY-QUALITY-FUTURE-FAILURE.json \
  --input identity=docs/completions/IDENTITY-QUALITY-LOCAL.json \
  --output docs/completions/QUALITY-AGGREGATE-LOCAL.json
```
