"""Cold-process smoke probe of copied helpers with all runtime sockets denied."""

import hashlib
import json
import os
import socket
import sys
from pathlib import Path


def denied(*args, **kwargs):
    raise OSError("Runtime network is unavailable in offline cleanup probe")


socket.getaddrinfo = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied

from skriller.contracts import Failure
from skriller.extraction.cleanup import CleanupLimits, PreparedContext, prepare_context

assert os.getuid() != 0
assert "CapEff:\t0000000000000000" in Path("/proc/self/status").read_text()
assert not Path("/var/run/docker.sock").exists()

cache = Path(os.environ["TIKTOKEN_CACHE_DIR"]) / "fb374d419588a4632f3f557e76b4b70aebbca790"
assert hashlib.sha256(cache.read_bytes()).hexdigest() == (
    "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
)
if "--missing-assets" in sys.argv:
    os.environ["TIKTOKEN_CACHE_DIR"] = "/tmp/empty-tokenizer-cache"
html = '<html><head><title>Fixture directory</title><script type="application/ld+json">{"@type":"Organization","name":"Aurora Ledger"}</script></head><body><h1>Aurora Ledger</h1><p>We build synthetic accounting tools.</p></body></html>'
context = prepare_context(html, "https://example.com/about", limits=CleanupLimits(chunk_tokens=128))
if "--missing-assets" in sys.argv:
    assert isinstance(context, Failure) and context.code == "source_unavailable", context
    print(json.dumps({"status": "passed", "missing_assets": "typed_unavailable"}))
    raise SystemExit(0)
assert isinstance(context, PreparedContext), context
assert any("Aurora Ledger" in chunk.text for chunk in context.chunks)
assert any(
    node.kind == "jsonld" and node.structured_value["name"] == "Aurora Ledger"
    for node in context.evidence
)
assert context.coverage_complete
print(
    json.dumps(
        {
            "status": "passed",
            "runtime_network": "denied",
            "copied_chunks": len(context.chunks),
            "preserved_evidence": len(context.evidence),
            "tokenizer_asset_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        }
    )
)
