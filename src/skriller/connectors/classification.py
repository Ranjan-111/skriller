"""Data-only page classification using copied detectors; never solves or retries."""

from dataclasses import dataclass
from typing import Literal, get_args
from urllib.parse import urlsplit

from agent_reach.channels.web import _is_antibot_page
from scrapling import Selector
from scrapling.engines._browsers._base import StealthySessionMixin

from skriller.contracts import Source


@dataclass(frozen=True)
class PageClassification:
    status: Literal[
        "readable",
        "challenge",
        "auth_required",
        "access_denied",
        "rate_limited",
        "js_shell",
        "empty_results",
        "empty",
        "unsupported",
        "unavailable",
    ]
    next_method: Literal["extract", "dynamic", "connection", "stop"]
    evidence_kind: Literal["page_read", "empty_results", "none"]
    reason: str

    @property
    def accepts_content(self):
        return self.status in {"readable", "empty_results"}


_AUTH_PATHS = {
    "linkedin": ("/login", "/authwall", "/checkpoint", "/uas/login"),
    "reddit": ("/login", "/account/login"),
    "x": ("/i/flow/login", "/login"),
    "instagram": ("/accounts/login",),
    "facebook": ("/login", "/checkpoint"),
    "github": ("/login", "/session"),
    "youtube": ("/signin",),
}
_EMPTY_TEXT = frozenset(
    {
        "no results",
        "no results found",
        "no matching results",
        "no matches found",
        "no posts found",
        "no people found",
    }
)


def classify_page(
    body: bytes,
    *,
    source: Source,
    final_url: str,
    status: int = 200,
    content_type: str = "text/html",
    document: Selector | None = None,
) -> PageClassification:
    if source not in get_args(Source):
        raise ValueError("Unsupported source identity")
    if status == 429:
        return PageClassification("rate_limited", "stop", "none", "source_backoff")
    if status == 401:
        return PageClassification("auth_required", "connection", "none", "http_unauthorized")
    if status == 403:
        return PageClassification("access_denied", "stop", "none", "http_forbidden")
    if not 200 <= status < 300:
        return PageClassification("unavailable", "stop", "none", "http_unavailable")
    if len(body) > 5 * 1024 * 1024:
        return PageClassification("unsupported", "stop", "none", "classification_input_budget")
    if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        return PageClassification("unsupported", "stop", "none", "unsupported_content")
    if not body.strip():
        return PageClassification("empty", "stop", "none", "empty_response")
    # Direct calls to existing copied detection routines, not recreated algorithms.
    if _is_antibot_page(body):
        return PageClassification("challenge", "stop", "none", "copied_agent_reach_detector")
    sample = body[:128000].decode("utf-8", errors="replace")
    copied_challenge = StealthySessionMixin._detect_cloudflare(sample)
    if copied_challenge and copied_challenge != "embedded":
        return PageClassification("challenge", "stop", "none", "copied_scrapling_detector")
    if content_type == "text/plain":
        text = " ".join(sample.split()).casefold()
        if text in _EMPTY_TEXT:
            return PageClassification(
                "empty_results", "stop", "empty_results", "explicit_empty_response"
            )
        return PageClassification("readable", "extract", "page_read", "readable_plain_text")
    document = document or Selector(body, adaptive=False)
    if len(document.xpath("//*")) > 20000:
        return PageClassification("unsupported", "stop", "none", "classification_element_budget")
    visible = " ".join(
        str(t)
        for t in document.xpath(
            "//body//text()[not(ancestor::script or ancestor::style or ancestor::noscript "
            "or ancestor::*[@hidden or @aria-hidden='true'])]"
        ).getall()
    ).strip()
    visible = " ".join(visible.split())
    lowered = visible.casefold()
    title = " ".join(document.css("title::text").getall()).strip().casefold()
    challenge_structure = bool(
        document.css(
            "#challenge-running, #challenge-form, #cf-challenge-running, iframe[src*='challenges.cloudflare.com']"
        )
    )
    if lowered in {
        "verify you are human",
        "verify you are human before continuing",
        "performing security verification",
    }:
        return PageClassification("challenge", "stop", "none", "challenge_only_body")
    if challenge_structure and (
        "verify you are human" in lowered
        or "just a moment" in title
        or "security verification" in lowered
    ):
        return PageClassification("challenge", "stop", "none", "challenge_shell_structure")
    # An embedded captcha on an otherwise readable contact form is not a gate.
    if copied_challenge == "embedded" and len(visible) < 40:
        return PageClassification("challenge", "stop", "none", "embedded_challenge_without_content")
    path = urlsplit(final_url).path.casefold().rstrip("/") or "/"
    route_auth = any(
        path == prefix or path.startswith(prefix + "/") for prefix in _AUTH_PATHS.get(source, ())
    )
    password_form = bool(document.css("input[type='password']"))
    login_prompt = any(
        word in lowered
        for word in (
            "sign in to continue",
            "log in to continue",
            "login to continue",
            "sign in to view",
            "log in to view",
        )
    )
    if (
        route_auth
        or password_form
        or (login_prompt and len(visible) < 300 and not document.css("article"))
    ):
        return PageClassification("auth_required", "connection", "none", "source_login_wall")
    empty_nodes = document.css("[data-empty-results], .no-results, [role='status']")
    if not document.css("article, [data-result]") and any(
        " ".join(node.get_all_text(separator=" ", strip=True).split()).casefold() in _EMPTY_TEXT
        and not node.xpath("ancestor-or-self::*[@hidden or @aria-hidden='true']")
        for node in empty_nodes
    ):
        return PageClassification("empty_results", "stop", "empty_results", "explicit_result_state")
    if lowered in _EMPTY_TEXT and not document.css("article, [itemtype], [data-result]"):
        return PageClassification(
            "empty_results", "stop", "empty_results", "explicit_empty_response"
        )
    shell = bool(document.css("script, #root, #app, #__next"))
    if not visible or (
        len(visible) < 40
        and lowered in {"loading", "loading...", "please enable javascript", "enable javascript"}
    ):
        if shell:
            return PageClassification("js_shell", "dynamic", "none", "unrendered_application_shell")
        return PageClassification("empty", "stop", "none", "empty_html_body")
    return PageClassification("readable", "extract", "page_read", "visible_source_content")
