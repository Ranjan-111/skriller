"""Evidence-preserving bounds around copied ScrapeGraph cleanup/chunk helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from agent_reach.utils.url import normalize_public_http_url
from bs4 import BeautifulSoup
from scrapegraphai.utils.cleanup_html import cleanup_html
from scrapegraphai.utils.convert_to_md import convert_to_md
from scrapegraphai.utils.split_text_into_chunks import split_text_into_chunks
from scrapegraphai.utils.tokenizer import num_tokens_calculus
from scrapling import Selector

from skriller.contracts import Failure


@dataclass(frozen=True)
class CleanupLimits:
    max_input_bytes: int = 2 * 1024 * 1024
    chunk_tokens: int = 1024
    max_chunks: int = 8
    max_evidence_nodes: int = 128
    max_evidence_characters: int = 32768

    def __post_init__(self):
        bounds = {
            "max_input_bytes": (1, 2 * 1024 * 1024),
            "chunk_tokens": (32, 4096),
            "max_chunks": (1, 32),
            "max_evidence_nodes": (1, 512),
            "max_evidence_characters": (64, 65536),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise ValueError("Cleanup limits exceed supported bounds")


@dataclass(frozen=True)
class EvidenceNode:
    evidence_id: str
    locator: str
    quote: str
    kind: str
    structured_value: Any = None


@dataclass(frozen=True)
class ContextChunk:
    chunk_id: str
    text: str
    estimated_tokens: int


@dataclass(frozen=True)
class PreparedContext:
    source_url: str
    source_sha256: str
    title: str
    chunks: tuple[ContextChunk, ...]
    evidence: tuple[EvidenceNode, ...]
    input_bytes: int
    total_chunks: int
    omitted_chunks: int
    omitted_evidence_nodes: int
    omitted_scripts: int
    issues: tuple[str, ...]
    tokenizer: str = "copied_gpt4o_estimate"
    content_kind: str = "untrusted_source"
    coverage_scope: str = "body_text_title_jsonld"

    @property
    def coverage_complete(self) -> bool:
        return (
            not self.omitted_chunks and not self.omitted_evidence_nodes and not self.omitted_scripts
        )

    def model_payload(self) -> dict[str, Any]:
        """Data-only envelope; caller keeps its trusted instructions separate.

        Full original evidence quotes remain for validation and are not secretly
        appended beyond the bounded chunks. Preparing context is not analysis.
        """
        return {
            "content_kind": "untrusted_source",
            "coverage_scope": self.coverage_scope,
            "source_url": self.source_url,
            "source_sha256": self.source_sha256,
            "chunks": [{"chunk_id": chunk.chunk_id, "text": chunk.text} for chunk in self.chunks],
            "omitted_chunks": self.omitted_chunks,
            "omitted_evidence_nodes": self.omitted_evidence_nodes,
            "omitted_scripts": self.omitted_scripts,
            "issues": list(self.issues),
            "coverage_complete": self.coverage_complete,
        }


def prepare_context(
    html: str, source_url: str, *, limits: CleanupLimits | None = None
) -> PreparedContext | Failure:
    """No source fetching, model requests, script execution or reduction level2."""
    limits = limits or CleanupLimits()
    if len(source_url) > 2048:
        return Failure(
            code="budget_exhausted", message="Source URL exceeds context metadata budget"
        )
    try:
        source_url = normalize_public_http_url(source_url)
    except ValueError:
        return Failure(code="access_denied", message="Cleanup requires a public HTTP(S) source URL")
    try:
        raw = html.encode("utf-8")
    except UnicodeError:
        return Failure(code="schema_invalid", message="Source is not valid UTF-8 text")
    if len(raw) > limits.max_input_bytes:
        return Failure(
            code="budget_exhausted",
            message="Source exceeds cleanup input budget; content was not processed",
        )
    digest = sha256(raw).hexdigest()
    soup = BeautifulSoup(html, "html.parser")
    document = Selector(html or "<html><body></body></html>", adaptive=False)
    evidence: list[EvidenceNode] = []
    evidence_characters = 0
    omitted_nodes = 0
    issues: list[str] = []
    jsonld_context: list[str] = []

    def retain(locator: str, quote: str, kind: str, structured: Any = None) -> bool:
        nonlocal evidence_characters, omitted_nodes
        if (
            len(evidence) >= limits.max_evidence_nodes
            or evidence_characters + len(quote) > limits.max_evidence_characters
        ):
            omitted_nodes += 1
            return False
        identifier = sha256(f"{digest}:{locator}".encode()).hexdigest()
        evidence.append(EvidenceNode(identifier, locator, quote, kind, structured))
        evidence_characters += len(quote)
        return True

    # Capture structured data from head and body before any destructive cleanup.
    for node in document.xpath(
        '//script[translate(@type,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="application/ld+json"]'
    ):
        quote = str(node.get_all_text(ignore_tags=(), strip=True))
        locator = node.generate_full_xpath_selector
        parsed = None
        try:
            parsed = json.loads(quote)
        except (ValueError, RecursionError):
            issues.append("invalid_jsonld")
        if retain(locator, quote, "jsonld", parsed):
            jsonld_context.append("JSON-LD source data:\n" + quote)

    for node in document.xpath(
        "//head/title | //body[not(*)] | //body//*[not(self::script or self::style) and (self::p or self::h1 or self::h2 or self::h3 or self::li or self::td or self::th or not(*))]"
    ):
        quote = str(node.get_all_text(separator=" ", strip=True))
        if quote:
            retain(node.generate_full_xpath_selector, quote, "text")

    # Script data is evidence, never executable policy. Non-JSONLD scripts are
    # visibly excluded; the copied regex script extractor never sees their code.
    scripts = soup.find_all("script")
    omitted_scripts = sum(
        str(script.get("type", "")).casefold() != "application/ld+json" for script in scripts
    )
    for script in scripts:
        script.decompose()
    for style in soup.find_all("style"):
        style.decompose()
    if soup.body is None:
        issues.append("missing_body_repaired")
        body = soup.new_tag("body")
        parent = soup.html or soup
        for node in list(parent.contents):
            if getattr(node, "name", None) != "head":
                body.append(node.extract())
        parent.append(body)

    try:
        # The copied helper's annotation says str, but its actual result is a
        # five-item tuple. Preserve this contract and do not use reduce_html(2).
        cleaned = cleanup_html(str(soup), source_url)
        if not isinstance(cleaned, tuple) or len(cleaned) != 5:
            raise ValueError("Unexpected copied cleanup return shape")
        title, body_html, _links, _images, _script_data = cleaned
        markdown = convert_to_md(body_html, source_url)
        combined = "\n\n".join([f"Title: {title}", *jsonld_context, markdown])
        chunks = split_text_into_chunks(combined, limits.chunk_tokens, use_semchunk=True)
        selected: list[ContextChunk] = []
        omitted_chunks = max(0, len(chunks) - limits.max_chunks)
        for index, chunk in enumerate(chunks[: limits.max_chunks]):
            tokens = num_tokens_calculus(chunk)
            if tokens > limits.chunk_tokens:
                omitted_chunks += 1
                issues.append("oversized_copied_chunk_omitted")
                continue
            selected.append(ContextChunk(f"{digest}:{index}", chunk, tokens))
    except OSError:
        return Failure(
            code="source_unavailable", message="Cleanup or tokenizer assets are unavailable"
        )
    except (ValueError, TypeError, RecursionError, RuntimeError):
        # Never expose upstream exceptions that embed the raw page in messages.
        return Failure(
            code="schema_invalid",
            message="Source cleanup or copied tokenizer could not prepare bounded context",
        )
    if omitted_chunks:
        issues.append("context_chunks_omitted")
    if omitted_nodes:
        issues.append("evidence_nodes_omitted")
    if omitted_scripts:
        issues.append("non_jsonld_scripts_omitted")
    # Title is a convenience label; full text is in bounded context/evidence.
    return PreparedContext(
        source_url,
        digest,
        str(title)[:500],
        tuple(selected),
        tuple(evidence),
        len(raw),
        len(chunks),
        omitted_chunks,
        omitted_nodes,
        omitted_scripts,
        tuple(dict.fromkeys(issues)),
    )
