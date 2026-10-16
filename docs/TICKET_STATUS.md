# Ticket execution status

Only tickets with completed scope and verified required checks are marked **done**.

A passing unit suite does not close a required database, browser, container, or live-source gate.

Current counts: 57 done, 24 implemented_pending_verification, 5 in_progress, 10 planned.

User-deferred verification gates:

- Direct account-backed LinkedIn/Reddit reads: keep pending until a required scenario is blocked; indexed search remains available. Session expiration requires reconnection.
- Hosted deployment and private off-host backup custody: keep pending; local implementation and recovery verification continue.
- 2026-10-17: User explicitly deferred remote Stripe/Razorpay plan creation; continue local implementation without requesting provider keys again.

| Ticket | Status | Verified evidence | Remaining acceptance checks |
| --- | --- | --- | --- |
| SKR-001 | done | [report](completions/SKR-001.md) | None |
| SKR-002 | done | [report](completions/SKR-002.md) | None |
| SKR-003 | done | [report](completions/SKR-003.md) | None |
| SKR-004 | done | [report](completions/SKR-004.md) | None |
| SKR-005 | done | [report](completions/SKR-005.md) | None |
| SKR-006 | done | [report](completions/SKR-006.md) | None |
| SKR-007 | done | [report](completions/SKR-007.md) | None |
| SKR-008 | done | [report](completions/SKR-008.md) | None |
| SKR-009 | implemented_pending_verification | [report](completions/SKR-009.md) | Live LinkedIn route validation and isolated backend environment |
| SKR-010 | implemented_pending_verification | [report](completions/SKR-010.md) | Live Reddit validation and missing redistribution license |
| SKR-011 | implemented_pending_verification | [report](completions/SKR-011.md), [report](completions/EXA-KEYLESS.json), [report](completions/EXA-COVERAGE.json) | Commercial SaaS use and result storage/export rights remain unverified; Corpus has no expected-URL labels; broader quality, operator enforcement and pagination remain unvalidated |
| SKR-012 | implemented_pending_verification | [report](completions/SKR-012.md), [report](completions/OLLAMA-llama3.2-3b-benchmark.json) | Select and validate a hosted-pilot model/provider with explicit token/cost and data-handling evidence; Run representative release-scale labelled evaluation; five synthetic records are diagnostic only |
| SKR-013 | done | [report](completions/SKR-013.md) | None |
| SKR-014 | done | [report](completions/SKR-014.md) | None |
| SKR-015 | done | [report](completions/SKR-015.md) | None |
| SKR-016 | done | [report](completions/SKR-016.md) | None |
| SKR-017 | done | [report](completions/SKR-017.md) | None |
| SKR-018 | implemented_pending_verification | [report](completions/SKR-018.md) | Live private S3 service/deployment verification remains user-deferred |
| SKR-019 | done | [report](completions/SKR-019.md), [report](completions/SKR-021.md) | None |
| SKR-020 | done | [report](completions/SKR-020.md) | None |
| SKR-021 | done | [report](completions/SKR-021.md) | None |
| SKR-022 | done | [report](completions/SKR-022.md) | None |
| SKR-023 | done | [report](completions/SKR-023.md) | None |
| SKR-024 | done | [report](completions/SKR-024.md), [report](completions/SKR-022.md) | None |
| SKR-025 | implemented_pending_verification | [report](completions/SKR-025.md), [report](completions/SKR-038.md), [report](completions/SKR-078.md) | Direct account-backed connection rebind/resume and hosted source-operation acceptance remain deferred |
| SKR-026 | done | [report](completions/SKR-026.md), [report](completions/SKR-019.md) | None |
| SKR-027 | implemented_pending_verification | [report](completions/SKR-027.md) | Installed browser/platform adapter end-to-end egress proof; Operational deployment checks |
| SKR-028 | done | [report](completions/SKR-028.md), [report](completions/YOUTUBE-COLLECTION-LIVE.json) | None |
| SKR-029 | done | [report](completions/SKR-029.md) | None |
| SKR-030 | implemented_pending_verification | [report](completions/SKR-030.md), [report](completions/SKR-029.md) | Explicit same-checkpoint direct-source credential rebind/resume remains unimplemented; Account-backed provider authorization and remote revocation acceptance remain user-deferred |
| SKR-031 | done | [report](completions/SKR-031.md) | None |
| SKR-032 | done | [report](completions/SKR-032.md) | None |
| SKR-033 | implemented_pending_verification | [report](completions/SKR-033.md) | Deployment egress027 and providerreview011 gates; full candidate/stage wiring pending |
| SKR-034 | done | [report](completions/SKR-034.md) | None |
| SKR-035 | done | [report](completions/SKR-035.md) | None |
| SKR-036 | implemented_pending_verification | [report](completions/SKR-036.md), [report](completions/PIPELINE-INTEGRATION.md) | Isolated HTTP collecting-worker packaging and production egress verification; Registered source-operation feasibility and hosted source gates |
| SKR-037 | done | [report](completions/SKR-037.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-038 | done | [report](completions/SKR-038.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-039 | done | [report](completions/SKR-039.md), [report](completions/STEALTH-CONTROLLED.json) | None |
| SKR-040 | implemented_pending_verification | [report](completions/SKR-040.md) | Isolated dynamic/stealth browser and hosted provider gateway control plane; Account-backed provider continuity and live configured provider acceptance remain user-deferred |
| SKR-041 | implemented_pending_verification | [report](completions/SKR-041.md) | Authenticated-source cache policy and integration remain open; User-deferred hosted access controls and live private S3 verification remain open |
| SKR-042 | done | [report](completions/SKR-042.md) | None |
| SKR-043 | done | [report](completions/SKR-043.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-044 | done | [report](completions/SKR-044.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-045 | done | [report](completions/SKR-045.md), [report](completions/PIPELINE-INTEGRATION.md), [report](completions/LOCAL-PAGE-PIPELINE-LIVE.json) | None |
| SKR-046 | done | [report](completions/SKR-046.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-047 | done | [report](completions/SKR-047.md) | None |
| SKR-048 | done | [report](completions/SKR-048.md), [report](completions/REPAIR-QUALITY-LOCAL-INITIAL.json), [report](completions/REPAIR-QUALITY-LOCAL-STABLE-ATTRIBUTES.json), [report](completions/REPAIR-QUALITY-LOCAL-ENUM.json), [report](completions/REPAIR-QUALITY-LOCAL.json), [report](completions/REPAIR-REVIEW-LOCAL.json) | None |
| SKR-049 | done | [report](completions/SKR-049.md), [report](completions/IDENTITY-QUALITY-FUTURE-FAILURE.json), [report](completions/IDENTITY-QUALITY-LOCAL.json) | None |
| SKR-050 | done | [report](completions/SKR-050.md) | None |
| SKR-051 | done | [report](completions/SKR-051.md) | None |
| SKR-096 | implemented_pending_verification | [report](completions/SKR-096.md) | Representative local-model semantic acceptance remains failing; Authenticated browser acceptance remains unverified under saved localhost browser restriction |
| SKR-052 | implemented_pending_verification | [report](completions/SKR-052.md) | Authenticated end-to-end browser check of clarification and resubmission remains; browser permission blocks localhost access |
| SKR-053 | done | [report](completions/SKR-053.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-054 | done | [report](completions/SKR-054.md) | None |
| SKR-055 | done | [report](completions/SKR-055.md) | None |
| SKR-056 | done | [report](completions/SKR-056.md) | None |
| SKR-057 | implemented_pending_verification | [report](completions/SKR-057.md) | Authenticated browser refinement/saved-list acceptance remains blocked by saved localhost browser permission |
| SKR-058 | done | [report](completions/SKR-058.md) | None |
| SKR-059 | in_progress | [report](completions/SKR-059.md) | Isolated tenant-owned backend execution with credential rebinding and shared job budget/evidence integration; User-deferred selected account-backed live discovery/coverage acceptance |
| SKR-060 | planned | — | Not started |
| SKR-061 | in_progress | [report](completions/SKR-061.md) | Isolated tenant-owned backend execution with credential rebinding and shared job budget/evidence integration; User-deferred selected account-backed live discovery/coverage acceptance |
| SKR-062 | planned | — | Not started |
| SKR-063 | done | [report](completions/SKR-063.md), [report](completions/GITHUB-COLLECTION-LIVE-REPOSITORY.json), [report](completions/GITHUB-COLLECTION-LIVE-PROFILE.json) | None |
| SKR-064 | done | [report](completions/SKR-064.md), [report](completions/RSS-COLLECTION-LIVE.json) | None |
| SKR-065 | done | [report](completions/SKR-065.md), [report](completions/YOUTUBE-WORKER-LOCAL.json), [report](completions/YOUTUBE-COLLECTION-LIVE.json) | None |
| SKR-066 | done | [report](completions/SKR-066.md) | None |
| SKR-067 | implemented_pending_verification | [report](completions/SKR-067.md) | Full evidenced semantic qualification and prompt-to-accepted-export gate remain open |
| SKR-068 | planned | — | Not started |
| SKR-069 | done | [report](completions/SKR-069.md) | None |
| SKR-070 | done | [report](completions/SKR-070.md) | None |
| SKR-071 | done | [report](completions/SKR-071.md) | None |
| SKR-072 | done | [report](completions/SKR-072.md), [report](completions/LOCAL-BACKUP-RESTORE.json) | None |
| SKR-073 | implemented_pending_verification | [report](completions/SKR-073.md), [report](completions/LOCAL-BACKUP-RESTORE.json), [report](RECOVERY_RUNBOOK.md) | Deploy and verify off-host daily archive and current-journal custody; Verify expiry/key recovery and <=24h RPO / <=4h RTO at actual pilot scale |
| SKR-074 | planned | — | Not started |
| SKR-075 | implemented_pending_verification | [report](completions/SKR-075.md), [report](completions/SKR-075-LOCAL.json) | Hosted full-job/source/model/network and isolated memory benchmark remains open; Two-workspace browser-heavy concurrency and host responsiveness remain unmeasured; Dependencies SKR-040, SKR-067, and SKR-074 are not fully closed |
| SKR-076 | in_progress | [report](completions/SKR-076.md), [report](completions/QUALITY-AGGREGATE-LOCAL.json), [report](completions/REPAIR-QUALITY-LOCAL.json), [report](completions/QUALIFICATION-QUALITY-LOCAL.json), [report](completions/IDENTITY-QUALITY-FUTURE-FAILURE.json), [report](completions/IDENTITY-QUALITY-LOCAL.json) | Representative 200-record source/engine-stratified field/contact corpus and execution remain incomplete; 50-prompt semantic acceptance and broader pilot qualification/merge quality remain open; Account-backed LinkedIn/Reddit acceptance remains user-deferred |
| SKR-077 | implemented_pending_verification | [report](completions/SKR-077.md) | Complete hosted external routes and network policy acceptance remain user-deferred through SKR-027/SKR-074; Direct account executor/reconnect paths and their boundary acceptance are not complete |
| SKR-078 | implemented_pending_verification | [report](completions/SKR-078.md) | Combined account-backed LinkedIn/Reddit journey SKR-068 remains user-deferred; Hosted deployment/recovery/rate-limit checks SKR-074 remain user-deferred; Representative complete-pipeline hosted fault acceptance remains open |
| SKR-079 | implemented_pending_verification | [report](completions/SKR-079.md), [report](SUPPORT_AND_PILOT_RUNBOOK.md) | No repeated real customer pilot has been run across three prospective workspaces; Hosted deployment and direct LinkedIn/Reddit account reads are user-deferred; Accuracy, review time, actual workflow cost, user value, and willingness to pay remain unmeasured |
| SKR-080 | done | [report](completions/SKR-080.md), [report](AUTOMATION_RUNBOOK.md) | None |
| SKR-081 | done | [report](completions/SKR-081.md) | None |
| SKR-082 | implemented_pending_verification | [report](completions/SKR-082.md), [report](completions/SKR-082-083-UI.md), [report](YOUTUBE_ANALYTICS_RUNBOOK.md) | Real configured Google owner consent/channel/refresh/disconnect acceptance; Authenticated live browser/responsive acceptance remains unverified |
| SKR-083 | implemented_pending_verification | [report](completions/SKR-083.md), [report](completions/SKR-082-083-UI.md), [report](YOUTUBE_ANALYTICS_RUNBOOK.md) | Real configured Google owner-channel report and authenticated browser acceptance. |
| SKR-084 | in_progress | [report](completions/SKR-084.md) | Durable discovery/candidate/evidence/source-capacity integration is locally tested; OAuth authorization/renewal, production egress image build acceptance, and live X access/coverage/rate-limit acceptance remain open |
| SKR-085 | planned | — | Not started |
| SKR-086 | planned | — | Not started |
| SKR-087 | done | [report](completions/SKR-087.md) | None |
| SKR-088 | implemented_pending_verification | [report](completions/SKR-088.md), [report](CRM_RUNBOOK.md), [report](CRM_AND_BILLING_DECISIONS.md) | Real configured Salesforce app/test org: API and Lead/custom field permissions, unique external-ID upsert/retry behaviour and live OAuth acceptance. |
| SKR-089 | done | [report](completions/SKR-089.md), [report](AUTOMATION_RUNBOOK.md) | None |
| SKR-090 | in_progress | [report](completions/SKR-090.md), [report](BILLING_RUNBOOK.md), [report](CRM_AND_BILLING_DECISIONS.md) | Refund/full-dispute pause and partial-refund policy are locally implemented/tested; checkout/customer subscription setup, charge-reference dispute resolution (Stripe/Razorpay), sandbox acceptance, and user-deferred remote plan creation remain |
| SKR-091 | planned | — | Not started |
| SKR-092 | planned | — | Not started |
| SKR-093 | done | [report](completions/SKR-093.md), [report](MCP_RUNBOOK.md) | None |
| SKR-094 | planned | — | Not started |
| SKR-095 | planned | — | Not started |
