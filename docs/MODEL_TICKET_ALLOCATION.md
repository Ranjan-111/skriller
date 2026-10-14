# Model allocation for remaining tickets

The user selected GPT-6.1 Sol Medium on 2026-10-14. The two-model allocation remains unchanged; assignment does not change completion status.

**Active model: GPT-6.1 Sol, Medium.** The remaining unfinished-ticket count is 69; the original model assignments remain unchanged. SKR-054 was closed; SKR-058, SKR-063, SKR-065 and SKR-066 now have additional verified implementation slices but remain pending acceptance integration.

Official guidance describes Sol as suitable for complex projects where cost matters and Luna as the most efficient option for focused work: [OpenAI model selection](https://developers.openai.com/api/docs/guides/model-selection). API pricing is not used to infer Plus usage consumption.

## Execution order

1. **Sol stabilization batch first:** inspect the interrupted SKR-096 planning bootstrap; finish genuine stage-routing and worker fixture failures; check migrations 0013–0017 and API contracts. Reconcile the interrupted SKR-055 list API and SKR-056 report component. Check SKR-025 cancellation and SKR-027/028 runtime gates. Do not enable semantic planning until its quality gate passes.
2. **Luna batch active:** take dependency-ready diagnostics, CI/probe harnesses, query/classifier/cleanup work, UI and serialization tickets from the table. Reuse existing implementations and test only changed behavior plus required gates.
3. **Sol integration batch:** connect collection → extraction → identity → qualification → exports/research; finish security, credential, recovery, source-specific and hosted-pilot gates.
4. **Alternate only when dependencies require it:** return eligible UI/connectors/benchmark tasks to Luna, then use Sol for final security and end-to-end review. P1/P2 keep their original dependency gates; model allocation does not make them ready.

## Ownership and credit discipline

- Exactly one model owns each unfinished ticket. Shared files belong to the active batch; no overlapping edits.
- Luna may implement ordinary fixtures, UI, documentation and standard adapters. Sol reviews changes touching authorization, evidence acceptance, budgets, private export data, or architectural contracts.
- Missing source accounts, production image availability or model quality stay explicit gates; neither model may substitute mocks for live acceptance.
- Preserve tests and verified code. Avoid whole-history subagent prompts and rerunning already-passing suites without a material change.
- If Luna needs an architectural change or cannot resolve a failure after bounded attempts, hand the relevant files and failure evidence to Sol.
- Done requires completed scope and verified checks. Existing `tickets.json` status remains authoritative.

## Ticket ownership

| Ticket | Model / effort | Phase | Current status | Work |
| --- | --- | --- | --- | --- |
| SKR-008 | 6 Luna / Medium | P0 | done | Set up ticket-level CI and artifact reporting |
| SKR-009 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Validate LinkedIn backend route and acquire missing implementation |
| SKR-010 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Validate Reddit route and acquire missing implementation |
| SKR-011 | 6 Luna / Medium | P0 | implemented_pending_verification | Validate search coverage, operators and provider terms |
| SKR-012 | 6 Luna / Medium | P0 | implemented_pending_verification | Validate cloud/local models against copied extraction code |
| SKR-018 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement private evidence object storage |
| SKR-025 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement cancellation, deadline and resume semantics |
| SKR-027 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Adapt public URL validation and network egress controls |
| SKR-028 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Adapt subprocess helpers into isolated backend runner |
| SKR-029 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Store source credentials with tenant-scoped access |
| SKR-030 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement source connect, expire, reconnect and revoke |
| SKR-032 | 6 Luna / Medium | P0 | done | Adapt doctor/probe results and expose connector status |
| SKR-033 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement chosen search-provider adapter |
| SKR-034 | 6 Luna / Medium | P0 | implemented_pending_verification | Generate bounded search/dork query variants |
| SKR-035 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Normalise and deduplicate discovered candidates |
| SKR-036 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Adapt copied Scrapling HTTP fetching into product stage |
| SKR-037 | 6 Luna / Medium | P0 | done | Classify challenges, empty pages and unavailable access |
| SKR-038 | 6.1 Sol / Medium | P0 | done | Adapt copied dynamic browser engine and bounded pool |
| SKR-039 | 6.1 Sol / Medium | P0 | planned | Adapt copied stealth/challenge engine with bounded retries |
| SKR-040 | 6.1 Sol / Medium | P0 | planned | Adapt copied proxy rotation and session continuity |
| SKR-041 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Adapt copied cache logic to access-scoped freshness |
| SKR-043 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Integrate copied adaptive selector matching with validation |
| SKR-044 | 6 Luna / Medium | P0 | implemented_pending_verification | Adapt copied HTML cleanup and chunking without evidence loss |
| SKR-045 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Adapt copied model creation and usage callbacks |
| SKR-046 | 6.1 Sol / Medium | P0 | done | Adapt SmartScraper graph to already-collected content |
| SKR-047 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Validate extraction fields against schema and evidence |
| SKR-048 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Adapt bounded LLM selector repair and template promotion |
| SKR-049 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Resolve entity identity with reversible links |
| SKR-050 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Evaluate essential criteria and preference ranking |
| SKR-051 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Validate contacts and per-claim freshness |
| SKR-096 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement prompt-to-plan interpretation and clarification service |
| SKR-052 | 6 Luna / Medium | P0 | implemented_pending_verification | Build prompt composer and editable interpretation UI |
| SKR-053 | 6 Luna / Medium | P0 | implemented_pending_verification | Build results and evidence detail views |
| SKR-054 | 6 Luna / Medium | P0 | done | Adapt copied export helpers for CSV, JSON and JSONL |
| SKR-055 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement saved-list snapshots and refresh |
| SKR-056 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Implement evidence-grounded research follow-ups |
| SKR-057 | 6.1 Sol / Medium | P0 | planned | Implement conversational refinement and plan reevaluation |
| SKR-058 | 6 Luna / Medium | P0 | implemented_pending_verification | Build partial results, reconnect and usage UX |
| SKR-059 | 6.1 Sol / Medium | P0 | planned | Adapt LinkedIn discovery and candidate routing |
| SKR-060 | 6.1 Sol / Medium | P0 | planned | Adapt LinkedIn profile, company and post reads |
| SKR-061 | 6.1 Sol / Medium | P0 | planned | Adapt Reddit discussion discovery |
| SKR-062 | 6.1 Sol / Medium | P0 | planned | Adapt Reddit post/comment reading and signal extraction |
| SKR-063 | 6 Luna / Medium | P0 | implemented_pending_verification | Adapt GitHub public research connector |
| SKR-064 | 6 Luna / Medium | P0 | implemented_pending_verification | Adapt RSS/Atom feed connector |
| SKR-065 | 6 Luna / Medium | P0 | implemented_pending_verification | Adapt public YouTube metadata and available transcripts |
| SKR-066 | 6 Luna / Medium | P0 | implemented_pending_verification | Create company/directory extraction presets using copied engine |
| SKR-067 | 6.1 Sol / Medium | P0 | implemented_pending_verification | Verify first complete prompt-to-export slice |
| SKR-068 | 6.1 Sol / Medium | P0 | planned | Verify combined LinkedIn/Reddit research journey |
| SKR-069 | 6.1 Sol / Medium | P0 | planned | Enforce workspace entitlements and abuse limits |
| SKR-070 | 6 Luna / Medium | P0 | implemented_pending_verification | Instrument stages, source health and costs |
| SKR-071 | 6.1 Sol / Medium | P0 | planned | Enforce evidence and export retention |
| SKR-072 | 6.1 Sol / Medium | P0 | planned | Propagate deletion and suppress rediscovery |
| SKR-073 | 6.1 Sol / Medium | P0 | planned | Implement encrypted backups and restore rehearsal |
| SKR-074 | 6.1 Sol / Medium | P0 | planned | Package and deploy bounded hosted pilot |
| SKR-075 | 6 Luna / Medium | P0 | planned | Benchmark parser, full-job latency and resource use |
| SKR-076 | 6.1 Sol / Medium | P0 | planned | Evaluate field, qualification and identity quality |
| SKR-077 | 6.1 Sol / Medium | P0 | planned | Verify tenant boundaries and prompt-injection resistance |
| SKR-078 | 6.1 Sol / Medium | P0 | planned | Verify recovery, rate limits and budget races |
| SKR-079 | 6 Luna / Medium | P0 | planned | Prepare runbook and execute small customer pilot |
| SKR-080 | 6.1 Sol / Medium | P1 | planned | Schedule idempotent saved-research refreshes |
| SKR-081 | 6 Luna / Medium | P1 | planned | Report meaningful changes and optional notifications |
| SKR-082 | 6.1 Sol / Medium | P1 | planned | Connect owner-authorised YouTube Analytics OAuth |
| SKR-083 | 6 Luna / Medium | P1 | planned | Retrieve and summarise owner analytics reports |
| SKR-084 | 6.1 Sol / Medium | P1 | planned | Adapt X discussion/professional connector |
| SKR-085 | 6.1 Sol / Medium | P1 | planned | Adapt Instagram business/creator connector |
| SKR-086 | 6.1 Sol / Medium | P1 | planned | Adapt Facebook company/content connector |
| SKR-087 | 6 Luna / Medium | P1 | planned | Add job/pricing/industry research presets |
| SKR-088 | 6.1 Sol / Medium | P1 | planned | Export qualified records into selected CRM |
| SKR-089 | 6.1 Sol / Medium | P1 | planned | Deliver signed idempotent webhooks |
| SKR-090 | 6.1 Sol / Medium | P1 | planned | Automate billing and entitlements |
| SKR-091 | 6 Luna / Medium | P1 | planned | Add selected language and locale support |
| SKR-092 | 6.1 Sol / Medium | P2 | planned | Adapt first regional-platform connector |
| SKR-093 | 6.1 Sol / Medium | P2 | planned | Expose read-only MCP research interface |
| SKR-094 | 6.1 Sol / Medium | P2 | planned | Evaluate optional semantic retrieval before adding infrastructure |
| SKR-095 | 6.1 Sol / Medium | P2 | planned | Evaluate local companion only if selected routes require it |

## Latest execution checkpoint

- Ticket status totals: **27 done, 35 implemented_pending_verification, 34 planned**. The per-ticket table above reflects the current canonical board.
- Completed Luna ticket in this execution batch: **SKR-054** private CSV/JSON/JSONL evidence-backed export API. **SKR-008** and **SKR-032** remain completed from the earlier batch.
- SKR-058 adds tested workspace-scoped usage accounting and a results-panel cost/budget view. Source-specific reconnect, qualified/near-match evidence views and hosted end-to-end acceptance remain open.
- SKR-063 adds a tested read-only public GitHub API adapter that reuses copied URL guards; persisted research routing remains open. SKR-064 retains its bounded RSS/Atom parser; research-stage routing and persistence remain open. SKR-065 adds tested public YouTube metadata and timestamped WebVTT parsers; caption retrieval and image/runtime verification remain open. SKR-066 adds six fixture-backed page presets over the copied extraction graph and shared model ledger; fetch/evidence integration remains open.
- Sol stabilization evidence: durable planning bootstrap stays opt-in pending grounded model quality; saved-list API and evidence report components are tested; cancellation, budget accounting and isolated browser runtime have real PostgreSQL/container coverage. Browser HTTP-to-render escalation and connection-aware resume remain integration work.
- Fresh keyless live search completed in **8.633 seconds with two references**. No paid Brave key is needed for that route. Result snippets remain unverified.
- User-selected Google sign-in and results were confirmed separately. Do not inspect the user's browser or auth session; earlier browser access was declined.
- Groq remains opt-in; the key is stored locally in the ignored `.env`, but its free-tier confirmation is not enabled. Local Ollama remains the default until that billing assertion is confirmed.

## Sol integration checkpoint — 2026-10-14

SKR-037, SKR-038 and SKR-046 are done against their declared scopes. Discovery now schedules tenant-owned public reads; JS shells alone can escalate to the reviewed container; private saved content reaches the copied graph and scoped unverified claims. The results UI shows quoted observations safely. 164 combined backend checks, 84 web tests, actual Chromium pipeline integration and one real Llama fixture passed. See [integration evidence](completions/PIPELINE-INTEGRATION.md). Continue Sol-owned entitlements, source credential/pipeline/identity/qualification and hosted gates; do not request another model change merely for already-verified component work.
