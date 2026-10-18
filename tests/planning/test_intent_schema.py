"""The model's generation contract must carry the same quote bounds as parsing."""

from skriller.research.planner import Interpretation


def test_generation_schema_forbids_empty_or_unbounded_intent_quotes():
    schema = Interpretation.model_json_schema()
    properties = schema["properties"]
    constrained = [
        properties["entity_quote"],
        *[properties["rules"]["items"]["prefixItems"][index] for index in (1, 3, 4)],
        properties["sources"]["items"]["prefixItems"][1],
        *properties["fields"]["items"]["prefixItems"],
        properties["unsupported"]["items"],
    ]
    for field in constrained:
        assert field["type"] == "string"
        assert field["minLength"] == 1
        assert field["maxLength"] == 500
