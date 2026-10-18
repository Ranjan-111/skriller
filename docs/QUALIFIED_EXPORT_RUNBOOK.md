# Qualified record downloads

The results panel now offers confirmed-record CSV and JSON downloads separately
from unverified source-list downloads. It uses the existing private export backend;
no extraction, qualification or serialization algorithm was rewritten.

The browser submits the current plan and at most 100 currently confirmed entity IDs.
It never selects near matches or unverified records implicitly. The backend performs
fresh qualification/evidence checks and exports only accepted fields. The metadata
response must match the requested format/schema, contain a valid reference, an
unexpired timestamp and a bounded row count. Files download through bearer-authenticated
requests with no token in the URL. Private headers remain enforced by the server.

The UI disables duplicate clicks while pending and aborts/discards work after plan,
workspace, candidate-selection changes or unmount. It validates MIME type and limits
file streaming to 8 MiB and 15 seconds. Failed or expired downloads require an explicit
retry; the panel does not automatically create another export. Blob URLs use fixed
filenames, are released after download and never enter persisted storage.

Local evidence: five focused client/component checks plus 53 results regressions
pass (58 total). A real PostgreSQL/API integration check verifies checkpointed
qualification groups -> confirmed selection -> private CSV -> matching entity IDs,
evidence metadata and stale excluded-selection rejection. That fixture uses reviewed
facts, not actual-model output, and therefore does not close semantic quality or the
complete model-driven prompt-to-export gate. TypeScript and formatting pass; the
mechanical UI detector reports no findings. Authenticated visual browser acceptance
remains unverified under the saved restriction.

Latest qualified-export production web build (`next build --webpack`, standalone) passed after these changes. No deployment was performed.
