import configparser
import functools
import importlib.metadata
import json
import logging
import os
from typing import Callable, Dict
try:
    VERSION = importlib.metadata.version("scrapegraphai")
except importlib.metadata.PackageNotFoundError:
    VERSION = "source-snapshot"
TRACK_URL = "https://sgai-oss-tracing.onrender.com/v1/telemetry"
TIMEOUT = 2
DEFAULT_CONFIG_LOCATION = os.path.expanduser("~/.scrapegraphai.conf")

logger = logging.getLogger(__name__)

def _load_config(config_location: str) -> configparser.ConfigParser:
    # The product does not persist upstream tracking identifiers or config.
    config = configparser.ConfigParser()
    config["DEFAULT"] = {"telemetry_enabled": "false", "anonymous_id": "disabled"}
    return config


def _parse_bool(value: str) -> bool:
    """Parse a boolean from a string using configparser's accepted spellings.

    Accepts the same values as the config file does, so
    ``SCRAPEGRAPHAI_TELEMETRY_ENABLED=false`` and ``telemetry_enabled = false``
    behave identically. Raises ValueError on anything unrecognised.
    """
    try:
        return configparser.ConfigParser.BOOLEAN_STATES[value.strip().lower()]
    except KeyError:
        raise ValueError(f"invalid boolean value: {value!r}")


def _check_config_and_environ_for_telemetry_flag(default_value: bool, config_obj):
    telemetry_enabled = default_value
    if "telemetry_enabled" in config_obj["DEFAULT"]:
        try:
            telemetry_enabled = config_obj.getboolean("DEFAULT", "telemetry_enabled")
        except Exception:
            pass

    env_value = os.environ.get("SCRAPEGRAPHAI_TELEMETRY_ENABLED")
    if env_value is not None:
        try:
            telemetry_enabled = _parse_bool(env_value)
        except ValueError:
            logger.warning(
                "SCRAPEGRAPHAI_TELEMETRY_ENABLED is set to %r, which is not a "
                "recognised boolean. Telemetry is left at %s. Use one of: "
                "true/false, yes/no, on/off, 1/0.",
                "[redacted]",
                telemetry_enabled,
            )

    return telemetry_enabled


config = _load_config(DEFAULT_CONFIG_LOCATION)
g_telemetry_enabled = False  # External telemetry is disabled in this product fork.
g_anonymous_id = config["DEFAULT"]["anonymous_id"]
CALL_COUNTER = 0
MAX_COUNT_SESSION = 1000


def disable_telemetry():
    global g_telemetry_enabled
    g_telemetry_enabled = False


def is_telemetry_enabled() -> bool:
    return False


def _build_telemetry_payload(
    prompt: str | None,
    schema: dict | None,
    content: str | None,
    response: dict | str | None,
    llm_model: str | None,
    source: list[str] | None,
) -> dict | None:
    """Build telemetry payload dict. Returns None if required fields are missing."""
    url = source[0] if isinstance(source, list) and source else None

    if isinstance(content, list):
        content = "\n".join(str(c) for c in content)

    json_schema = None
    if isinstance(schema, dict):
        try:
            json_schema = json.dumps(schema)
        except (TypeError, ValueError):
            json_schema = None
    elif schema is not None:
        json_schema = str(schema)

    llm_response = None
    if isinstance(response, dict):
        try:
            llm_response = json.dumps(response)
        except (TypeError, ValueError):
            llm_response = None
    elif response is not None:
        llm_response = str(response)

    if not all([prompt, json_schema, content, llm_response, url]):
        return None

    return {
        "user_prompt": prompt,
        "json_schema": json_schema,
        "website_content": content,
        "llm_response": llm_response,
        "llm_model": llm_model or "unknown",
        "url": url,
    }


def _send_telemetry(payload: dict):
    """Send telemetry payload to the tracing endpoint."""
    # Never transmit prompts, source pages, credentials or answers externally.
    return None


def _send_telemetry_threaded(payload: dict):
    """Disabled in the product fork, including direct caller invocation."""
    return None


def log_event(event: str, properties: Dict[str, any]):
    pass


def log_graph_execution(
    graph_name: str,
    source: str,
    prompt: str,
    schema: dict,
    llm_model: str,
    embedder_model: str,
    source_type: str,
    execution_time: float,
    content: str = None,
    response: dict = None,
    error_node: str = None,
    exception: str = None,
    total_tokens: int = None,
):
    if not is_telemetry_enabled():
        return

    if error_node is not None:
        return

    payload = _build_telemetry_payload(
        prompt=prompt,
        schema=schema,
        content=content,
        response=response,
        llm_model=llm_model,
        source=source,
    )
    if payload is None:
        logger.debug("Telemetry skipped: missing required fields")
        return

    _send_telemetry_threaded(payload)


def capture_function_usage(call_fn: Callable) -> Callable:
    @functools.wraps(call_fn)
    def wrapped_fn(*args, **kwargs):
        try:
            return call_fn(*args, **kwargs)
        finally:
            if is_telemetry_enabled():
                log_event("function_usage", {"function_name": call_fn.__name__})
    return wrapped_fn
