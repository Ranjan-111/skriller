"""Pinned rdt-cli get_post_comments method; only transport/URL constants adapted.
See adjacent PROVENANCE.json and NOTICE. No write/auth/retry code is included.
"""
from typing import Any

DEFAULT_LIMIT = 25
POST_COMMENTS_URL = "/r/{subreddit}/comments/{post_id}.json"
POST_COMMENTS_SHORT_URL = "/comments/{post_id}.json"

class ReadRequest:
    def _get(self, url, params):
        return url, params

    def get_post_comments(
        self,
        post_id: str,
        subreddit: str | None = None,
        sort: str = "best",
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict]:
        """Get post and its comments.

        Returns [post_listing, comments_listing].
        """
        if subreddit:
            url = POST_COMMENTS_URL.format(subreddit=subreddit, post_id=post_id)
        else:
            url = POST_COMMENTS_SHORT_URL.format(post_id=post_id)
        params: dict[str, Any] = {"sort": sort, "limit": limit, "raw_json": 1}
        return self._get(url, params=params)
