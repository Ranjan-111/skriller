"""rdt-cli search method copied unchanged; transport and URL constants adapted.
Upstream and licensing declaration: see adjacent NOTICE/PROVENANCE records.
No client initialization, browser/session state, retries or write methods copied.
"""

from typing import Any

DEFAULT_LIMIT = 25
SEARCH_URL = "/search.json"
SUBREDDIT_SEARCH_URL = "/r/{subreddit}/search.json"


class SearchRequest:
    def _get(self, url, params):
        return url, params

    def search(
        self,
        query: str,
        subreddit: str | None = None,
        sort: str = "relevance",
        time_filter: str = "all",
        limit: int = DEFAULT_LIMIT,
        after: str | None = None,
    ) -> dict:
        """Search posts."""
        if subreddit:
            url = SUBREDDIT_SEARCH_URL.format(subreddit=subreddit)
        else:
            url = SEARCH_URL
        params: dict[str, Any] = {
            "q": query,
            "sort": sort,
            "t": time_filter,
            "limit": limit,
            "restrict_sr": "on" if subreddit else "off",
            "raw_json": 1,
        }
        if after:
            params["after"] = after
        return self._get(url, params=params)
