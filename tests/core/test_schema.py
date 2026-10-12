from skriller.api import create_app
from skriller.settings import Settings


def test_api_contract_references_resolve_and_limits_are_published():
    schema = create_app(Settings(environment="test")).openapi()
    components = schema["components"]["schemas"]

    def check(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert node["$ref"].split("/")[-1] in components
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)
    assert components["Limits"]["properties"]["result_limit"]["maximum"] == 100
    assert components["SearchPlan"]["additionalProperties"] is False
