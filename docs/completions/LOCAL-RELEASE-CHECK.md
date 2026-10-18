# Local release check — 18 October 2026

## Observed running-stack checks

Restarted the verified project API, Next.js, research worker and retention processes
through `scripts/dev_stack.py --discovery-only`. Existing PostgreSQL/RabbitMQ data
services were retained. No local environment file was edited. The profile disables
experimental planning/extraction/direct reads only in its child processes.

- FastAPI `/health/live`: HTTP 200, status ok.
- FastAPI `/health/ready`: HTTP 200; database, broker and worker all true.
- Next.js `/`: HTTP 200 and HTML.
- Actual application-role PostgreSQL connection: succeeds; superuser=false,
  bypass_rls=false.
- Migration revision 0056 matches the sole repository head.
- Actual PostgreSQL -> RabbitMQ -> running research worker -> one bounded free
  Exa query -> persisted results: completed with two unverified source snippets
  in 7.884 seconds. No paid model/search key or user Firebase session was used.

Machine evidence: LOCAL-RELEASE-READINESS.json and LOCAL-RELEASE-WORKFLOW.json.

## Final automated selection

Backend: **139 passed, 1 optional actual-model test skipped**. Includes grounded
planning/bootstrap/resume, real RabbitMQ delivery with controlled source I/O,
combined copied source/extraction/owner-review/private export, qualification,
export privacy and local launcher profile checks. Two existing lxml deprecation
warnings are not failed checks.

Frontend: **176 passed across five files** (API, workbench, results, qualified
exports, source exports). TypeScript, generated-client contract drift check and
production Next.js build pass. These fixture/component checks do not use the
human Firebase session or provide real-model semantic accuracy evidence.

The final build ran before restarting the development server so build/dev output
did not compete. No additional Groq/Ollama evaluation or heavy model download ran.

## Packaging changes and bounds

The optional `infra/deploy/compose.data.yaml` overlay adds private PostgreSQL and
RabbitMQ, durable volumes and a profile-gated operator bootstrap/migration task.
The public API's runtime DB URLs use only the restricted role; the operator
env-file is separate. YAML/network/port/migration-command static checks pass.
Docker Compose `config --quiet` also passes for the combined application/data
manifests using synthetic temporary configuration; no actual runtime secrets,
daemon, images or containers were required. See DEPLOYMENT-MANIFEST-CONFIG.json.
Docker execution, target image dependency closure and hosted acceptance remain
unverified and user-deferred. No container, remote server or cloud purchase ran.

## Four-ticket audit

| Ticket | Status | Required evidence still missing |
| --- | --- | --- |
| SKR-096 | implemented_pending_verification | Representative semantic acceptance and authenticated clarification/resubmission browser journey. Existing local/Groq diagnostics fail the unchanged quality gate. |
| SKR-076 | in_progress | Representative 50-prompt/200-record quality acceptance and real-source/pilot evidence. New local regression passes cannot replace these. |
| SKR-067 | implemented_pending_verification | Actual-model/source/accepted-evidence/confirmed-export end-to-end acceptance and current authenticated browser test. The real discovery probe and synthetic reviewed-record export each pass within their stated scopes. |
| SKR-074 | in_progress | Actual Linux image/Compose execution, secrets/roles, private storage/egress, TLS, bounded load/recovery, off-host restore and hosted smoke evidence. The ticket includes deployment itself. |

None qualifies for Done from this local check. An internal staging deployment can
be the next verification environment; a public qualified-lead launch remains blocked.
Board stays 57 done / 33 implemented_pending_verification / 2 in_progress / 4 planned.

## User handoff

The local app is running at http://localhost:3000 in discovery-only mode. Follow
`../LOCAL_RUN_AND_MANUAL_TEST.md` for full start/status/stop commands and the real
Google-sign-in -> prompt -> source CSV/JSON manual check. The current user browser
journey has not been asserted tested by this batch. Prior saved browser access
restrictions were respected; no user browser/session/token was accessed.

For hosting order, configuration, builds, private data services, migrations, HTTPS,
acceptance and rollback, follow `../DEPLOYMENT_HOSTING_GUIDE.md`. Source/semantic,
S3 backup/recovery and payment acceptance must not be hidden by a successful
staging startup. No new key or Codex coding-model switch is needed for the local
manual source-export test.
