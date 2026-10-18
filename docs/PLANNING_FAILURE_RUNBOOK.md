# Rejected prompt-planning recovery

`GET /v1/jobs/{job_id}/plan` now returns optional `planning_failure` on a paused
planning job whose interpretation was rejected. It never includes model text,
provider exceptions, credentials, or a replacement interpretation. Existing workspace
authorization applies; foreign-tenant requests return 404. Successful, pending,
clarification and canceled plans retain `planning_failure: null`.

| reason | recovery | UI meaning |
| --- | --- | --- |
| invalid_interpretation | revise_prompt | The model could not produce a validated interpretation. Review/edit the retained prompt and start a new run explicitly. |
| model_unavailable | check_service | The configured model service was unavailable or rate limited. Check service readiness before choosing a new run. |
| budget_exhausted | check_limits | The planning run reached its permitted budget. Review limits before choosing a new run. |
| execution_interrupted | review_run | Execution stopped or its outcome needs review. Check the run; do not replay an uncertain call automatically. |

All outcomes carry `automatic_retry_allowed: false` and `source_search_started:
false`. This describes the rejected planning job, not a source outage or global
availability. Its initial stored search objective is not a validated semantic plan.
No source discovery was dispatched by this planning attempt. No budget, permission,
model selection or job transition changes when viewing this metadata.

The frontend client validates the exact reason/recovery pairs, rejected status,
both false flags, and rejects unexpected metadata keys. Generated API types include
`PlanningFailureView`; old responses without this optional field remain compatible.

## Luna UI implementation — 2026-10-17

The existing interpretation section now explains all four sanitized failure
categories, their recovery direction, and that discovery did not start. It preserves
the composer prompt and provides an explicit action to focus it; editing and submitting
remain separate user actions. Rejected plans do not render their saved objective or
criteria as a validated semantic interpretation. Legacy rejected plans without metadata get a neutral
message and no unsupported claim about source execution. The panel does not mutate
the job or automatically submit another request. Fixture coverage passes (50 results
tests), TypeScript and formatting pass. Authenticated localhost browser acceptance
remains pending under the user's saved browser restriction.

## Local verification

Nine fixed-outcome cases validate sanitization and recovery mapping. The two actual
database/API rejected-plan scenarios cover schema-invalid and ungrounded responses,
safe recovery details, retained immutable objective, no repeated model call, and
cross-tenant 404. Frontend transport checks cover valid metadata and five misleading
or extra-field variants. These checks do not establish model intent accuracy.

Plan retrieval also follows job-state transitions; delayed rejection is covered without dropping saved results or resubmitting.

## Explicit omitted constraints

The planner pauses for clarification if supported minimum/maximum employee wording
or an explicit industry constraint is missing from the model's interpretation. These
guards do not fill in criteria automatically or weaken literal quote/value checks.
Seven dedicated cases include preservation of a correctly grounded industry/maximum
combination. They verify rejection/recovery behavior, not model semantic accuracy.
