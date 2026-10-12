# Local modifications

SKR-044: `tests/test_cleanup_html.py` corrects two baseline assertions. HTML
minification may legally omit `</body>`, so the test now parses the body and
checks its complete paragraph text. The level-2 test expected 21 characters
despite its documented 20-character limit; it now checks exact 20-character
text and length. Original reference files and cleanup engine code are unchanged.
The product never enables level 2. These test-only changes are registered in
`PROVENANCE.json`; pristine baseline evidence is recorded in the SKR-044 report.

Source is copied from `reference/Scrapegraph-ai-main`; LICENSE and source/test hashes are preserved in PROVENANCE.json. Snapshot has no verified upstream commit ID.

SKR-004 adaptations:

- External telemetry is permanently disabled even when legacy environment flags or mutable globals opt in. Direct send functions are inert. No tracing config is read or written in the user's home directory; no persistent tracking identifier is generated. Legacy flag parsing remains for compatibility/regression coverage; invalid flag values are redacted.
- Importing telemetry from an uninstalled source snapshot has a version fallback rather than requiring installed package metadata.
- FetchNode logs operation metadata rather than raw local HTML, credential-bearing source URLs, or failure URLs.
- GenerateAnswerNode logs fixed failure messages instead of model exception text, which can echo raw pages or credentials. Exceptions still propagate to callers; application error presentation must redact them separately.
- BaseGraph logs completion rather than extracted results, parsed documents, or generated scripts.
- Utility and node exports are lazily loaded. Original exported implementations remain available; importing the package does not eagerly import optional OCR, model providers, or code-generation utilities. Code-generation sources are preserved for provenance but are not enabled by a product workflow.

Privacy coverage is in `tests/vendor/test_scrapegraph_import.py`; original telemetry/generation tests remain copied in this snapshot. Provider/API calls are mocked in tests. Live model integration is a later ticket.

- FetchNode defers ChromiumLoader import until the browser branch; local-content extraction imports no browser/proxy machinery.
