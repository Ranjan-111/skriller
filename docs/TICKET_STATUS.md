# Ticket execution status

Only tickets with completed scope and verified required checks are marked **done**.

A passing unit suite does not close a required database, browser, container, or live-source gate.

Current counts: 47 done, 22 implemented_pending_verification, 2 in_progress, 25 planned.

User-deferred verification gates:

- Direct account-backed LinkedIn/Reddit reads: keep pending until a required scenario is blocked; indexed search remains available. Session expiration requires reconnection.
- Hosted deployment and private off-host backup custody: keep pending; local implementation and recovery verification continue.

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
| SKR-011 | implemented_pending_verification | [report](completions/SKR-011.md), [report](completions/EXA-KEYLESS.json) | Written confirmation of commercial SaaS use and search-result storage/export rights; Broader source-quality and operator/pagination validation |
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
| SKR-025 | implemented_pending_verification | [report](completions/SKR-025.md), [report](completions/SKR-038.md) | Direct account-backed connection rebind/resume and hosted source-operation acceptance remain deferred |
| SKR-026 | done | [report](completions/SKR-026.md), [report](completions/SKR-019.md) | None |
| SKR-027 | implemented_pending_verification | [report](completions/SKR-027.md) | Installed browser/platform adapter end-to-end egress proof; Operational deployment checks |
| SKR-028 | implemented_pending_verification | [report](completions/SKR-028.md) | Installed browser/platform read runtime integration; Credential mount integration |
| SKR-029 | implemented_pending_verification | [report](completions/SKR-029.md) | Source runner secret injection and isolated deployment gates remain open. |
| SKR-030 | implemented_pending_verification | [report](completions/SKR-030.md) | Live source authorization, remote revocation and active runner cancellation remain unverified. |
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
| SKR-041 | implemented_pending_verification | [report](completions/SKR-041.md) | HTTP304 revalidation; Authenticated-source cache policy/integration and hosted private storage verification |
| SKR-042 | done | [report](completions/SKR-042.md) | None |
| SKR-043 | done | [report](completions/SKR-043.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-044 | done | [report](completions/SKR-044.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-045 | done | [report](completions/SKR-045.md), [report](completions/PIPELINE-INTEGRATION.md), [report](completions/LOCAL-PAGE-PIPELINE-LIVE.json) | None |
| SKR-046 | done | [report](completions/SKR-046.md), [report](completions/PIPELINE-INTEGRATION.md) | None |
| SKR-047 | done | [report](completions/SKR-047.md) | None |
| SKR-048 | implemented_pending_verification | [report](completions/SKR-048.md) | Bounded repair-worker orchestration and review of proposed mappings; Representative repair quality benchmark and deployment acceptance |
| SKR-049 | done | [report](completions/SKR-049.md) | None |
| SKR-050 | done | [report](completions/SKR-050.md) | None |
| SKR-051 | implemented_pending_verification | [report](completions/SKR-051.md) | Trusted subject/date review and production source/refresh orchestration remain open. |
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
| SKR-065 | implemented_pending_verification | [report](completions/SKR-065.md), [report](completions/YOUTUBE-WORKER-LOCAL.json) | Representative public-video metadata and caption read remains unverified after a backend failure using the final image |
| SKR-066 | done | [report](completions/SKR-066.md) | None |
| SKR-067 | implemented_pending_verification | [report](completions/SKR-067.md) | Full evidenced semantic qualification and prompt-to-accepted-export gate remain open |
| SKR-068 | planned | — | Not started |
| SKR-069 | done | [report](completions/SKR-069.md) | None |
| SKR-070 | done | [report](completions/SKR-070.md) | None |
| SKR-071 | done | [report](completions/SKR-071.md) | None |
| SKR-072 | done | [report](completions/SKR-072.md), [report](completions/LOCAL-BACKUP-RESTORE.json) | None |
| SKR-073 | implemented_pending_verification | [report](completions/SKR-073.md), [report](completions/LOCAL-BACKUP-RESTORE.json), [report](RECOVERY_RUNBOOK.md) | Deploy and verify off-host daily archive and current-journal custody; Verify expiry/key recovery and <=24h RPO / <=4h RTO at actual pilot scale |
| SKR-074 | planned | — | Not started |
| SKR-075 | planned | — | Not started |
| SKR-076 | planned | — | Not started |
| SKR-077 | planned | — | Not started |
| SKR-078 | planned | — | Not started |
| SKR-079 | planned | — | Not started |
| SKR-080 | planned | — | Not started |
| SKR-081 | planned | — | Not started |
| SKR-082 | planned | — | Not started |
| SKR-083 | planned | — | Not started |
| SKR-084 | planned | — | Not started |
| SKR-085 | planned | — | Not started |
| SKR-086 | planned | — | Not started |
| SKR-087 | planned | — | Not started |
| SKR-088 | planned | — | Not started |
| SKR-089 | planned | — | Not started |
| SKR-090 | planned | — | Not started |
| SKR-091 | planned | — | Not started |
| SKR-092 | planned | — | Not started |
| SKR-093 | planned | — | Not started |
| SKR-094 | planned | — | Not started |
| SKR-095 | planned | — | Not started |
