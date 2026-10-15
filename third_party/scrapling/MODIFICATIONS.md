# Local modifications

Initial copy preserves source files. Record patches in PROVENANCE.json.

SKR-039: the supported synchronous copied challenge solver now shares one
monotonic deadline across recursive attempts and page waiting loops. Short
caller timeouts are retained rather than increased to 60 seconds by StealthConfig.
The application permits one copied fetch attempt inside a hard-lived isolated
container and accounts all routed requests against the existing URL/job budget.
The unused asynchronous solver is not advertised as an integrated capability.
