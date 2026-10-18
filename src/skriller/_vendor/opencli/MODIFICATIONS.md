# Selected OpenCLI read subset

Five modules were copied from the pinned snapshot recorded in PROVENANCE.json;
the Apache-2.0 license is retained. Facebook profile/search and the Instagram shared
read-response helper are unchanged. No CLI registry, host bridge, account discovery,
install script, or write command is imported into this subset.

Instagram adaptations enforce an explicitly public account: search drops private or
unknown-visibility entries before applying the limit; profile rejects private or
missing-visibility responses and mismatched usernames. Missing counters remain null,
and absent verification flags remain unknown instead of false. Source extraction,
request URLs, fallback sequence and error handling remain copied from upstream.

This subset is not a production execution sandbox, enabled route, business/creator
owner analytics adapter, or private-account access capability. The fixture probe
injects a closed registry and mocked page; an isolated credential-bound executor,
network/accounting controls and durable evidence integration are still required.
