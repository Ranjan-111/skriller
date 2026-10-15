"""Shared synthetic GitHub public API fixture (no live identifiers)."""


def repo_payload(**overrides):
    value = {
        "id": 1,
        "full_name": "acme/demo",
        "html_url": "https://github.com/acme/demo",
        "description": "Public demo",
        "visibility": "public",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "pushed_at": "2025-01-02T00:00:00Z",
        "stargazers_count": 4,
        "forks_count": 1,
        "open_issues_count": 0,
        "language": "Python",
        "owner": {"login": "acme", "type": "Organization"},
        "private": False,
    }
    value.update(overrides)
    return value
