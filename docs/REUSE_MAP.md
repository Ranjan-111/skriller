# Source reuse map

**2026-10-17 A-SOCIAL acquisition:** The actual OpenCLI backend is now pinned at
`e6174a952c763a836a9bb0dd2f097d2962b3876b` in `third_party/external/opencli` with
2,343 unmodified files, license and archive/per-file hashes. Candidate Instagram/
Facebook profile/search modules and their dependencies are identified in
[SOCIAL_BACKEND_REVIEW.md](SOCIAL_BACKEND_REVIEW.md). This is source acquisition,
not an installed/validated/activated platform operation. Runtime isolation and
operation acceptance remain open under SKR-085/SKR-086.

Date: 12 October 2026  
Related: [Implementation tickets](IMPLEMENTATION_TICKETS.md), [PRD](PRD.md), [technical stack](TECH_STACK.md)

## Implementation rule

The user's latest direction is to copy existing code from the supplied repositories and make necessary changes rather than independently rewriting their features. This supersedes the earlier preference for installing upstream packages alone.

Keep `reference/` as the original comparison material. Copy source packages, supporting files and relevant tests into `third_party/` during the import tickets, preserving original Python package names and notices. Install those local copies as local path dependencies. Preserve the dependency closure instead of copying an isolated class and discovering missing helpers later. Product adapters may add tenancy, budgets, evidence, schemas, and orchestration that the reference code does not supply.

For every imported feature: record source path and snapshot hash; copy/adapt relevant upstream tests; add a regression for every behaviour changed; and add a product-boundary test. Copying code is not evidence that the feature works in the new environment. Do not discard upstream tests to make a patch pass.

Use a provenance manifest for each copied tree plus a modification log. Any missing upstream implementation must be acquired as a separately pinned dependency/source or explicitly scoped as new integration code. Do not claim that a diagnostics module is a scraper. Runtime copies and adaptations are recorded in their provenance manifests and ticket completion reports.

## Available snapshots

LinkedIn native search runtime (2026-10-17): `infra/egress/Dockerfile.linkedin`
copies the acquired `third_party/external/linkedin/linkedin_mcp_server` package
unchanged, with LICENSE/NOTICE/SOURCE_MANIFEST at commit
`f1ba6aa87234526cf22812e59233e0c619073529`. The worker composes its
`linkedin/session.py`, `navigation.py`, `content.py`, `capture.py` and permalink
listener, while the existing adapted URL/link modules retain their recorded
hashes. Product glue adds owner/session scopes, one-attempt capture, request
bounds, isolated execution and durable reference provenance. The installed
synthetic-browser fixture verifies both search operations without networking;
it does not certify live access. See `docs/completions/LINKEDIN-WORKER-LOCAL.json`.

The reference folder contains extracted directories, not top-level ZIP files. Local metadata identifies Scrapling 0.4.15, Agent-Reach 1.5.0, and ScrapeGraph-AI 2.3.1. These are metadata observations, not tested release compatibility. There is no verified upstream commit identity for these ZIP-derived snapshots. [Reference inventory](REFERENCE_INVENTORY.json) uses content hashes to identify the supplied material without inventing a commit SHA.

Reference contribution instructions apply if modifying/contributing to those upstream projects. We are planning separate local copies, not publishing upstream changes. Preserve their notices; if an upstream contribution is later requested, follow that project's branching and contribution instructions then.

## Code and test map

All paths below are relative to the workspace root. IDs are referenced by individual implementation tickets. [Machine-readable reuse groups](reuse_sources.json) list exact code and test paths; the reference inventory contains per-file hashes. A-CORE also includes the MCP integration scaffolding for the later MCP ticket.

| Map ID | Existing implementation to copy/adapt | Upstream regression starting point | Necessary product adaptation |
| --- | --- | --- | --- |
| S-HTTP | `reference/Scrapling-main/scrapling/fetchers/requests.py`, `scrapling/engines/static.py` within that tree | `reference/Scrapling-main/tests/fetchers/async/test_requests.py`, `test_requests_session.py` in the same folder | Bounded requests, response validation, deadline/budget hooks and evidence metadata. |
| S-PARSE | `reference/Scrapling-main/scrapling/parser.py`, its `core/` helpers | `reference/Scrapling-main/tests/parser/test_general.py`, `test_adaptive.py`, `test_find_similar_advanced.py` | Evidence locators, semantic validation; reuse selector/similarity logic. |
| S-STORE | `reference/Scrapling-main/scrapling/core/storage.py` | `reference/Scrapling-main/tests/core/test_storage_core.py` | Adapt storage contract for tenant/source/template/version scoping and PostgreSQL. Existing storage keys use domain plus identifier and have no product workspace boundary. Check parser constructor/cache requirements. |
| S-BROWSER | `reference/Scrapling-main/scrapling/fetchers/chrome.py`, `scrapling/engines/_browsers/` | `reference/Scrapling-main/tests/fetchers/async/test_dynamic.py`, `test_dynamic_session.py` | Isolated capacity pool, cancellation, egress, navigation/content limits. |
| S-STEALTH | `reference/Scrapling-main/scrapling/fetchers/stealth_chrome.py`, `scrapling/engines/_browsers/_stealth.py` | `reference/Scrapling-main/tests/fetchers/test_cloudflare_solver.py`, `async/test_stealth.py` | Keep documented engine capabilities; bound internal solver/retry work and classify persistent failure. Mocked challenge success is not a live bypass benchmark. |
| S-RATE | `reference/Scrapling-main/scrapling/spiders/throttle.py`, `scrapling/engines/toolbelt/proxy_rotation.py` | `reference/Scrapling-main/tests/spiders/test_throttle.py`, `tests/fetchers/test_proxy_rotation.py` | Reuse backoff/proxy logic but add shared cross-worker limits and accounting; avoid independent retry budgets. |
| S-CACHE | `reference/Scrapling-main/scrapling/spiders/cache.py`, `checkpoint.py` in that folder | `reference/Scrapling-main/tests/spiders/test_cache.py`, `test_checkpoint.py` | Adapt reusable cache/checkpoint operations; product DB remains canonical, with tenant/access scope and deletions. |
| A-CORE | `reference/Agent-Reach-main/agent_reach/channels/base.py`, `channels/__init__.py`, `doctor.py`, `probe.py` | `reference/Agent-Reach-main/tests/test_channel_contracts.py`, `test_doctor.py`, `test_probe.py` | Copy routing/diagnostics; instantiate channels per tenant/check rather than sharing mutable registry singleton state. Separate configured from actually working. |
| A-SEC | `reference/Agent-Reach-main/agent_reach/utils/url.py`, `utils/paths.py`, `utils/text.py`, `utils/process.py` | `reference/Agent-Reach-main/tests/test_url_security.py`, `test_private_file_writes.py`, `test_scrub_credentials.py`, `test_process.py` | Reuse URL/path/redaction helpers; add DNS/redirect/network egress controls. Process helper sets UTF-8; it is not a complete execution sandbox. Child environment must be allowlisted. |
| A-LI | `reference/Agent-Reach-main/agent_reach/channels/linkedin.py`, `channels/mcporter.py` | `reference/Agent-Reach-main/tests/test_mcporter_config.py`, `test_doctor_credential_boundaries.py` | These check configuration for external `mcp-server-linkedin`; actual profile/post/search backend source is absent. Pin/acquire it separately if selected. No `@latest` or host-global config for customer jobs. |
| A-REDDIT | `reference/Agent-Reach-main/agent_reach/channels/reddit.py`, `backends/opencli.py` | `reference/Agent-Reach-main/tests/test_reddit_channel.py`, `test_opencli_backend.py` | External OpenCLI/rdt implementations are absent. Distinguish bridge/configured/session from tested search/read. Replace home-global credential assumptions with workspace-owned context. |
| A-PUBLIC | `reference/Agent-Reach-main/agent_reach/channels/github.py`, `rss.py`, `youtube.py`, `web.py` in that folder | `reference/Agent-Reach-main/tests/test_youtube_channel.py`, `test_web_channel.py`, `test_channels.py` | Reuse capability detection and any actual reading logic present; add typed adapters for external gh/feedparser/yt-dlp as needed. Source channels have different implementation depth. |
| A-SOCIAL | `reference/Agent-Reach-main/agent_reach/channels/twitter.py`, `instagram.py`, `facebook.py`, `_opencli_site.py`, `bilibili.py`, `xiaohongshu.py` | `reference/Agent-Reach-main/tests/test_twitter_channel.py`, `test_opencli_backend.py`, `test_xhs_format.py` | Copy available routing/formatting; acquire missing external backends and test each operation. Never reuse host-wide accounts across customers. |
| G-GRAPH | `reference/Scrapegraph-ai-main/scrapegraphai/graphs/smart_scraper_graph.py`, `abstract_graph.py`, `base_graph.py` | `reference/Scrapegraph-ai-main/tests/integration/test_smart_scraper_integration.py`, `tests/graphs/abstract_graph_test.py` | Copy graph infrastructure; adapt to collected local content and explicit stage limits; disable uncontrolled refetch/reattempt/code-generation branches. |
| G-EXTRACT | `reference/Scrapegraph-ai-main/scrapegraphai/nodes/generate_answer_node.py`, `parse_node.py`, `fetch_node.py`, associated prompts and `utils/output_parser.py` | `reference/Scrapegraph-ai-main/tests/test_generate_answer_node.py`, `tests/nodes/fetch_node_test.py`, `tests/utils/output_parser_test.py` | Preserve extraction/model/parser logic, but add evidence IDs, bounded chunks/model calls, timeout cancellation, and strict acceptance. Local content path logs raw source text and must be redacted. |
| G-CLEAN | `reference/Scrapegraph-ai-main/scrapegraphai/utils/cleanup_html.py`, `convert_to_md.py`, `split_text_into_chunks.py` | `reference/Scrapegraph-ai-main/tests/test_cleanup_html.py`, `tests/utils/convert_to_md_test.py` | Preserve JSON-LD/evidence before pruning. `reduce_html(..., 2)` truncates ordinary text to 20 characters: disable/adapt it for research evidence. Actual cleanup return shape must be wrapped accurately. |
| G-EXPORT | `reference/Scrapegraph-ai-main/scrapegraphai/utils/data_export.py` | No dedicated export test found in supplied tests; add product round-trip tests | Copy JSON/CSV helpers; patch heterogeneous-field handling, empty output semantics, streaming, formula safety, evidence/version columns, and private destination control. JSONL is new extension, not present here. |
| G-PRIVACY | `reference/Scrapegraph-ai-main/scrapegraphai/telemetry/telemetry.py` | `reference/Scrapegraph-ai-main/tests/test_telemetry_flag.py` | Telemetry is enabled by default and loads/writes a home config at import. Disable external telemetry before import and isolate/no-op unnecessary home writes in the copied runtime. Product metrics remain independent. |

## Missing product capabilities

None of these three source trees supplies Skriller's full conversational UI, multi-tenant SaaS permissions, evidence/claim database, business qualification rules, spending ledger, billing, or coordinated Celery/RabbitMQ orchestration. Those tickets add original product glue rather than reimplementing existing scraping engines. Owner-authorised YouTube Analytics is also a distinct integration from a public transcript tool.

Upstream tests are starting points, not a replacement for product tests. Some tests require network/model keys or old dependency interfaces. Record their baseline outcomes and adapt affected tests transparently. Never label skipped network tests as passing source access.

## Added bounded integrations — 16 October 2026

Owner YouTube Analytics is original product/provider glue; the supplied trees have no owner OAuth implementation. Encryption and safe private-key loading reuse the existing Agent-Reach-derived keyring/store patterns. The optional private report summary directly reuses the installed copied ScrapeGraph answer node, structured parser, existing product graph/ledger and report citation types. It creates no new extraction engine or workspace-shared private evidence.

SKR-084 retains a separately pinned full `public-clis/twitter-cli` source at commit `7c634e0d396b1e7af9f63315b414925fe4f29ae7`. Its unchanged pure models/parser are copied into `src/skriller/_vendor/twitter` with byte-hash provenance and license. No upstream auth/client/CLI/write path is imported into product execution; isolated source access remains in progress.

The X worker now copies Scrapling's `parse_retry_after` function unchanged into
`src/skriller/_vendor/retry_after.py`, adapting imports to standard-library types
and logging so the standalone worker does not load the browser/spider stack.
An AST comparison checks it against the pinned source; the Docker image includes
Scrapling's license. X PKCE/consent code adapts the existing product Salesforce
transport and encrypted consent lifecycle. Two pre-existing formatting edits in
unused reference CLI/output files are explicitly recorded in the acquisition
manifest and `third_party/external/twitter/MODIFICATIONS.md`; the runtime parser,
models and license remain byte-identical.

SKR-093 adapts the existing copied Agent-Reach `integrations/mcp_server.py` with optional trusted product handlers, preserving its default diagnostic behavior. The product reuses that server/stdio scaffolding and calls the existing authenticated research/list/evidence APIs, rather than adding another research engine or bypassing the job ledger. The modification and hash are recorded in the Agent-Reach copy's provenance manifest.



## Selected LinkedIn/Reddit discovery subsets — 2026-10-15

The pinned acquired backends now supply runtime-only pure-data subsets under `src/skriller/_vendor/`: Reddit `models.py` and `parser.py` are unchanged; LinkedIn `link_metadata.py` is unchanged and `search_urls.py` adapts one exception import to the exact extracted exception class. The Python package namespace is product-local to prevent accidental imports of upstream authentication/browser startup. Provenance, modification logs and source-hash contract tests preserve traceability. Product wrappers enforce bounds, filters, source references and unknown identity/date semantics. These parsing contracts are used by controlled feasibility probes; production tenant credential/budget/worker integration and live readiness are still separate gates.

## Installed YouTube backend and job adapter — 2026-10-15

The runtime continues to use the copied `third_party/agent-reach/agent_reach/channels/youtube.py`
for platform routing and actual installed-tool health checks. Reading delegates to
Agent-Reach's existing external dependency `yt-dlp==2026.8.19`, with the six missing
`yt-dlp[default]` closure wheels staged from their exact `uv.lock` sizes and hashes.
No new video extraction engine or audio transcription implementation was written.
Installed metadata declares yt-dlp `Unlicense`, and yt-dlp-ejs `Unlicense AND MIT AND ISC`.
The immutable image also reuses the Node binary bundled in the existing pinned
Playwright installation; it downloads no new runtime at task execution.

`youtube_worker.py` is product glue: fixed single-video operation, existing yt-dlp
urllib transport with request/redirect metering, selected supplied VTT retrieval,
output bounds and source validation. It invokes no private account or paid model.
`youtube_executor.py` reuses the existing guarded process/container runner.
`youtube_collection.py` follows the existing public collection/checkpoint/storage
interfaces for tenant ownership, job reservations, cancellation, erasure, scoped
metadata/caption evidence and identity limits. The installed backend fixture uses
actual yt-dlp processing with a synthetic InfoExtractor and network disabled;
public-source readiness is separately recorded as unverified after a backend failure.

2026-10-17 analytics/CRM integration follow-through: `analytics/jobs.py` adapts the
existing follow-up admission/reporting lease/outbox orchestration and retains
`analytics.summaries` -> copied ScrapeGraph answer-node/parser/model ledger.
`crm/router.py` delegates selection to the existing copied-export/qualification
queue. `crm/oauth.py` reuses the existing OAuth redirect validation and bounded
native transport pattern; `crm/consents.py` adapts the existing owner OAuth AES-GCM,
single-use consent and generation fences. No source engine was rewritten, and no
new third-party source snapshot was imported by this batch.

### 2026-10-17 Reddit OAuth discovery boundary

`_vendor/reddit/search.py` copies only the pinned acquired `RedditClient.search`
method (AST equality tested), with fixed relative URL constants and a transport-
free `_get` seam. The existing unchanged parser/models remain in use. New
`reddit_request.py` moves the existing request contracts without changing their
bounds. `reddit_worker.py` and `reddit_executor.py` adapt the already tested X
fixed-host/isolated execution pattern; shared credential, job, capacity and
checkpoint infrastructure is reused. Upstream write/auth/anti-detection clients
are excluded. The minimal image shares the X locked wheel closure. See
`REDDIT_OAUTH_RUNBOOK.md`; source and live acceptance remain separate gates.

Reddit OAuth lifecycle reuses `connections/x_oauth.py` encryption/ownership/replay
controls and `connectors/x_oauth.py` bounded fixed-endpoint transport, adapting
only Reddit's confidential-code/read-scope/nonrotating-refresh protocol. The
new durable continuation store is product glue for actor/job/request/credential
binding; each source page still uses the pinned copied rdt-cli search builder and
parser. Neither acquired source authentication/session engines nor write clients
are imported into the runtime worker.

## 2026-10-18 OpenCLI runtime reuse

Five selected read modules are copied into src/skriller/_vendor/opencli with license,
source/adapted hashes and Instagram modification notices. The static READ_SCRIPTS.json
is generated from those functions, not reimplemented extraction logic. Facebook
search/profile and the response helper remain unchanged. Python adapters add product
contracts, credential isolation, durable jobs and evidence lifecycle. See
SOCIAL_BACKEND_REVIEW.md for boundaries and offline execution reports.
