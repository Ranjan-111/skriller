"""Bounded post/comment evidence over the unchanged acquired rdt-cli parser."""

import json
import math
import re
from datetime import UTC, datetime
from typing import Literal

from skriller._vendor.reddit.parser import parse_post_detail
from skriller.connectors.reddit_discovery import (
    DiscoveryData,
    RedditPostReference,
    parse_search_listing,
)
from skriller.connectors.reddit_request import RedditRead, RedditSearch


class RedditComment(DiscoveryData):
    native_id: str
    parent_id: str
    source_url: str
    text: str
    author_handle: str | None
    author_identity: Literal["unknown"] = "unknown"
    published_at: datetime | None
    content_unavailable: bool
    truncated: bool


class RedditThread(DiscoveryData):
    source: Literal["reddit"] = "reddit"
    evidence_kind: Literal["post_comment_read"] = "post_comment_read"
    post: RedditPostReference
    comments: tuple[RedditComment, ...]
    observed_at: datetime
    coverage_complete: bool
    unexpanded_nodes: int
    omitted_comments: int
    buying_intent: Literal["not_inferred"] = "not_inferred"
    subject_identity: Literal["unknown"] = "unknown"


def parse_thread(payload, request: RedditRead, *, observed_at: datetime) -> RedditThread:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("An aware observation time is required")
    try:
        if len(json.dumps(payload, allow_nan=False).encode()) > 1_048_576:
            raise ValueError("Thread exceeds byte bound")
    except (RecursionError, TypeError):
        raise ValueError("Invalid thread structure") from None
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("Expected post and comment listings")
    for listing in payload:
        if (
            not isinstance(listing, dict)
            or listing.get("kind") != "Listing"
            or not isinstance(listing.get("data"), dict)
            or not isinstance(listing["data"].get("children"), list)
        ):
            raise ValueError("Invalid thread listing")
    if len(payload[0]["data"]["children"]) != 1:
        raise ValueError("Exactly one requested post is required")
    posts = parse_search_listing(
        payload[0],
        RedditSearch(query=request.post_id, subreddit=request.subreddit, limit=1),
        observed_at=observed_at,
    )
    if len(posts.posts) != 1 or posts.posts[0].native_id != "t3_" + request.post_id:
        raise ValueError("Returned post differs from the request")
    post = posts.posts[0]
    seen: set[str] = set()
    count = more = 0

    def validate(nodes, parent, depth):
        nonlocal count, more
        if not isinstance(nodes, list) or depth > 6:
            raise ValueError("Comment depth exceeds bound")
        for node in nodes:
            count += 1
            if count > 100 or not isinstance(node, dict):
                raise ValueError("Comment tree exceeds bound")
            data = node.get("data")
            if not isinstance(data, dict) or data.get("parent_id") != parent:
                raise ValueError("Comment parent does not match its nesting")
            if node.get("kind") == "more":
                children = data.get("children", [])
                if not isinstance(children, list) or len(children) > 100:
                    raise ValueError("Invalid omitted comment boundary")
                more += 1
                continue
            comment_id = data.get("id")
            if (
                node.get("kind") != "t1"
                or not isinstance(comment_id, str)
                or not re.fullmatch(r"[a-z0-9]{3,13}", comment_id)
                or comment_id in seen
                or data.get("name") != "t1_" + comment_id
                or data.get("link_id") != post.native_id
                or not isinstance(data.get("body"), str)
                or not isinstance(data.get("author"), str)
            ):
                raise ValueError("Invalid comment resource identity")
            seen.add(comment_id)
            replies = data.get("replies")
            if replies in (None, ""):
                continue
            if (
                not isinstance(replies, dict)
                or replies.get("kind") != "Listing"
                or not isinstance(replies.get("data"), dict)
            ):
                raise ValueError("Invalid replies listing")
            validate(replies["data"].get("children"), "t1_" + comment_id, depth + 1)

    validate(payload[1]["data"]["children"], post.native_id, 0)
    if payload[1]["data"].get("after") or payload[1]["data"].get("before"):
        more += 1
    detail = parse_post_detail(payload)
    output: list[RedditComment] = []
    omitted = 0

    def retain(comments):
        nonlocal omitted
        for comment in comments:
            if comment.author == "[more]":
                continue
            if len(output) >= request.limit:
                omitted += 1
            else:
                unavailable = comment.body in {"[deleted]", "[removed]"}
                timestamp = comment.created_utc
                output.append(
                    RedditComment(
                        native_id=comment.fullname,
                        parent_id=comment.parent_fullname,
                        source_url=post.source_url.rstrip("/") + "/" + comment.id + "/",
                        text="" if unavailable else comment.body[:4096],
                        author_handle=None
                        if comment.author in {"", "[deleted]", "[removed]"}
                        else comment.author[:100],
                        published_at=datetime.fromtimestamp(timestamp, UTC)
                        if math.isfinite(timestamp) and 0 < timestamp <= observed_at.timestamp()
                        else None,
                        content_unavailable=unavailable,
                        truncated=len(comment.body) > 4096,
                    )
                )
            retain(comment.replies)

    retain(detail.comments)
    declared_count = payload[0]["data"]["children"][0]["data"].get("num_comments")
    return RedditThread(
        post=post,
        comments=tuple(output),
        observed_at=observed_at,
        coverage_complete=type(declared_count) is int
        and 0 <= declared_count <= len(output)
        and not (
            more
            or omitted
            or post.truncated
            or post.content_unavailable
            or any(c.truncated or c.content_unavailable for c in output)
        ),
        unexpanded_nodes=more,
        omitted_comments=omitted,
    )
