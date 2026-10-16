# Optional source-read research MCP interface

Run the interface explicitly after signing into Skriller and choosing an existing workspace. It is not auto-registered and does not provide direct access to a source account or the user's host browser.

```sh
uv run python -m skriller.mcp_runtime \
  --api-base http://127.0.0.1:8000 \
  --workspace-id WORKSPACE_UUID \
  --token-file /absolute/private/path/firebase-id-token
```

The token file must be a regular file owned by the current OS user, readable only by that owner (for example mode0600), at most8192 bytes, containing a current Firebase **ID token**. A Firebase public configuration API key is not an authentication token. Supply the token from your own authenticated session; do not paste it into chat, command arguments, source code or MCP tool arguments. The runtime reads the private file at startup and sends the token only in the Authorization header to the fixed API origin. Expired/revoked identity tokens are denied by the normal API; update the private file and restart explicitly when required. It does not extract or renew browser sessions.

Remote API origins require HTTPS. Plain HTTP is allowed only for local loopback. URL credentials, query strings, fragments and base paths are rejected. Redirects and environment proxies are disabled. Tool arguments cannot override the API origin, bearer token or configured workspace. HTTP calls have time/output bounds and no automatic retries. Repeated submission requires the same explicit request key to use the normal server idempotency path.

## Tool surface

| Tool | Operation |
| --- | --- |
| `list_conversations` | Read up to100 conversations in the selected workspace. |
| `submit_research` | Submit a bounded prompt into an existing conversation using the normal job/entitlement path. Requires `conversation_id`, `prompt`, `request_key`; optional normal sources and result limit1–25. |
| `get_research` | Read `status`, `results`, `plan` or `usage` for a normal workspace research job. |
| `list_saved_lists` | Read up to100 saved-list headers in the selected workspace. |
| `read_saved_snapshot` | Read a list's immutable positive revision or `latest`. |
| `read_evidence` | Read one evidence citation that the normal research API authorises. |

Research submission creates the same product jobs as the website; source-read-only means that this interface has no social posting, DM, source edit or remote sync operations. It also has no arbitrary command, tool URL, source credential, analytics grant, billing or external export tool. Saved source content is returned as data, never executed as instructions. Authentication, suppression/erasure, tenant access, source availability and spending limits remain enforced by the product API/worker.

An MCP client should read the returned job ID and poll `get_research`; the interface does not run an unbounded polling loop. A denied request yields a fixed error code, not server error bodies or credentials. Large responses fail at the256KiB boundary instead of truncating evidence into misleading JSON.

## Local evidence

The actual MCP SDK protocol was tested against the real authenticated API and PostgreSQL job/admission/budget/checkpoint paths using a controlled source. The installed stdio client also launched the actual runtime in a child process and completed initialization/tool listing. The copied server's original doctor tests still pass, and its product handler is verified not to instantiate host source configuration. No external client was registered and no real user's token was read. Hosted deployment and direct source-account verification retain their existing separate gates.
