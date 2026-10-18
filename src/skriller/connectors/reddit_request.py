"""Existing bounded Reddit request contracts shared with the isolated worker."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoveryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RedditCursor(DiscoveryData):
    after: str = Field(pattern=r"^t3_[a-z0-9]{3,13}$")


class RedditSearch(DiscoveryData):
    user_agent: str = Field(
        default="linux:skriller-research:v0.1 (bounded OAuth read)",
        min_length=16,
        max_length=256,
        pattern=r"^[ -~]+$",
    )
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    subreddit: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,32}$")
    sort: Literal["relevance", "hot", "top", "new", "comments"] = "relevance"
    time_filter: Literal["all", "hour", "day", "week", "month", "year"] = "all"
    limit: int = Field(default=10, ge=1, le=25)
    cursor: RedditCursor | None = None

    def backend_arguments(self):
        """Exact reviewed rdt-cli search signature, never arbitrary tool args."""
        return {
            "query": self.query,
            "subreddit": self.subreddit,
            "sort": self.sort,
            "time_filter": self.time_filter,
            "limit": self.limit,
            "after": self.cursor.after if self.cursor else None,
        }


class RedditRead(DiscoveryData):
    """One post and a bounded comment tree; no arbitrary URL or expansion token."""

    operation: Literal["read_post"] = "read_post"
    post_id: str = Field(pattern=r"^[a-z0-9]{3,13}$")
    subreddit: str = Field(pattern=r"^[A-Za-z0-9_]{1,32}$")
    sort: Literal["best", "top", "new", "old", "controversial", "qa"] = "best"
    limit: int = Field(default=25, ge=1, le=100)
    user_agent: str = Field(
        default="linux:skriller-research:v0.1 (bounded OAuth read)",
        min_length=16,
        max_length=256,
        pattern=r"^[ -~]+$",
    )

    def backend_arguments(self):
        return {
            "post_id": self.post_id,
            "subreddit": self.subreddit,
            "sort": self.sort,
            "limit": self.limit,
        }
