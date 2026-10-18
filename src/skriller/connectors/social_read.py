"""Small output-contract helpers shared by the attributed social read adapters."""

import json

from pydantic import BaseModel, ConfigDict


class SocialData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def bounded_rows(payload):
    if (
        not isinstance(payload, list)
        or len(json.dumps(payload, allow_nan=False).encode()) > 65536
        or any(not isinstance(row, dict) for row in payload)
    ):
        raise ValueError("A bounded copied read response is required")
    return payload
