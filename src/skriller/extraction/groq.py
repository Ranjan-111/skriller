"""Opt-in Groq transport; copied parser and shared local accounting are reused.

Free-tier eligibility is an operator assertion, not something the API can prove.
No retry, fallback, tools, arbitrary endpoint, or paid account activation occurs.
"""

import math

import httpx
from langchain_openai import ChatOpenAI
from openai import APIStatusError
from pydantic import SecretStr
from scrapling.spiders.throttle import parse_retry_after

from skriller.extraction.models import LocalStructuredModel, ModelBounds, ModelUnavailable

GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class BoundedTransport(httpx.AsyncBaseTransport):
    """Bound the body before the official SDK buffers/parses it."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None):
        self.inner = inner or httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        if request.url.host != "api.groq.com" or request.url.scheme != "https":
            raise ValueError("Unapproved model endpoint")
        response = await self.inner.handle_async_request(request)
        try:
            chunks = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 131072:
                    raise ValueError("Model response exceeds transport limit")
                chunks.append(chunk)
            headers = dict(response.headers)
            # Body is already decoded; prevent a second decompression by HTTPX.
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(response.status_code, headers=headers, content=b"".join(chunks))
        finally:
            await response.aclose()

    async def aclose(self):
        await self.inner.aclose()


class GroqStructuredModel(LocalStructuredModel):
    source = "groq"
    host = "api.groq.com"

    def __init__(
        self,
        key: SecretStr,
        *,
        free_tier_confirmed: bool,
        bounds: ModelBounds | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not isinstance(key, SecretStr) or not key.get_secret_value().strip():
            raise ValueError("A server-side Groq secret is required")
        if free_tier_confirmed is not True:
            raise ValueError(
                "Groq requires explicit operator confirmation of free-tier configuration"
            )
        self.bounds = bounds or ModelBounds()
        self.http_client = httpx.AsyncClient(
            transport=BoundedTransport(transport),
            trust_env=False,
            follow_redirects=False,
            timeout=self.bounds.timeout_seconds,
            headers={"Accept-Encoding": "identity"},
        )
        self.model = ChatOpenAI(
            model=GROQ_MODEL,
            api_key=key,
            base_url=GROQ_BASE_URL,
            temperature=0,
            max_retries=0,
            timeout=self.bounds.timeout_seconds,
            http_async_client=self.http_client,
            streaming=False,
        )

    @property
    def model_name(self):
        return GROQ_MODEL

    def invocation_model(self, schema):
        # Best-effort JSON schema accepts richer Pydantic constraints; the copied
        # parser and local schema validator remain authoritative. No repair retry.
        return self.model.bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": False,
                    "schema": schema.model_json_schema(),
                },
            },
            max_completion_tokens=self.bounds.output_tokens,
        )

    def provider_failure(self, error):
        if isinstance(error, APIStatusError) and error.status_code == 429:
            raw = error.response.headers.get("retry-after")
            retry = parse_retry_after({"Retry-After": raw}) if raw else None
            seconds = (
                min(86400, math.ceil(retry))
                if retry is not None and math.isfinite(retry)
                else 86400
            )
            return ModelUnavailable(
                "rate_limited",
                "Model provider rate limit reached.",
                seconds,
            ), {"Retry-After": str(seconds)}
        return ModelUnavailable("source_unavailable", "Model provider is unavailable."), None

    async def aclose(self):
        await self.http_client.aclose()


def structured_model(settings):
    """Operator-only provider choice; credentials never become a browser setting."""
    if settings.model_provider == "ollama":
        return LocalStructuredModel()
    if settings.groq_api_key is None:
        raise ValueError("Configured Groq provider requires GROQ_API_KEY")
    return GroqStructuredModel(
        settings.groq_api_key,
        free_tier_confirmed=settings.groq_free_tier_confirmed,
    )
