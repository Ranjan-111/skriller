"""Adapted from copied ScrapeGraph-AI utils/data_export.py (MIT).

The original json.dump and csv.DictWriter algorithms are retained; filenames
become private in-memory streams, CSV uses the union schema and empty exports
are real files. JSONL extends the same serialization path. No filesystem path
or source value is logged. Attribution: third_party/scrapegraph-ai/PROVENANCE.json.
"""

import csv
import io
import json
from typing import Literal

Format = Literal["json", "csv", "jsonl"]


def _safe(value):
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


def serialize(rows: list[dict], metadata: dict, format: Format) -> bytes:
    stream = io.StringIO(newline="")
    if format == "json":
        json.dump(
            {"metadata": metadata, "records": rows},
            stream,
            ensure_ascii=False,
            indent=4,
            allow_nan=False,
        )
    elif format == "jsonl":
        stream.write(
            json.dumps({"type": "metadata", **metadata}, ensure_ascii=False, allow_nan=False) + "\n"
        )
        for row in rows:
            stream.write(
                json.dumps({"type": "record", **row}, ensure_ascii=False, allow_nan=False) + "\n"
            )
    elif format == "csv":
        keys = list(metadata["columns"])
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows({key: _safe(row.get(key)) for key in keys} for row in rows)
    else:
        raise ValueError("Unsupported export format")
    return stream.getvalue().encode("utf-8")
