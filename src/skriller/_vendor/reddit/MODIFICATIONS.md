# Copied parser subset

`models.py` and `parser.py` are byte-for-byte copies of the pinned acquired files recorded in PROVENANCE.json. Only the containing Python namespace and packaging initializer are new. Relative `.models` imports retain the original dependency closure. Authentication, cookie import and network client modules are not imported by this subset. Tests check exact source and runtime file hashes.

2026-10-17: Added `search.py`, copying only `RedditClient.search` (AST unchanged) from the pinned acquired client. The new `SearchRequest._get` returns a URL/parameters pair; fixed relative constants are copied. No upstream network/auth/write transport is included.

2026-10-17: Added `read.py`, copying only `RedditClient.get_post_comments` with its
AST unchanged. `ReadRequest._get` returns the fixed relative post/comment URL and
parameters. The existing parser/models remain unchanged; no morechildren expansion,
upstream authentication, retries or write operations are included.
