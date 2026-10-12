"""Deterministic provider boundaries for product tests, never live fallbacks."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


@dataclass
class FrozenClock:
    instant: datetime = datetime(2026, 10, 12, tzinfo=UTC)

    def now(self):
        return self.instant

    def advance(self, seconds: float):
        if seconds < 0:
            raise ValueError("Clock cannot go backwards")
        self.instant += timedelta(seconds=seconds)


class ReplayProvider:
    """Exact request replay: an unlabelled request is a test failure."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def run(self, request):
        self.calls.append(request)
        if request not in self.responses:
            raise AssertionError(f"Unlabelled provider request: {request}")
        response = self.responses[request]
        if isinstance(response, Exception):
            raise response
        return response


class FixtureServer:
    def __init__(self, routes):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, body = routes.get(self.path, (404, b"fixture missing"))
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def validate_labels(corpus):
    records = corpus["companies"]
    ids = {record["id"] for record in records}
    expected = corpus["expected"]
    labelled = expected["confirmed"] + expected["near_match"] + expected["rejected"]
    if len(labelled) != len(set(labelled)) or set(labelled) != ids:
        raise ValueError("Every entity needs exactly one expected qualification")
    for record in records:
        if (
            not {"id", "name", "industry", "location", "employees", "founder", "url"}
            <= record.keys()
        ):
            raise ValueError("Missing expected evidence labels")
