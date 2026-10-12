import json
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures/research"


def test_corpus_has_expected_criteria_evidence_and_ambiguity():
    corpus = json.loads((FIXTURES / "labels.json").read_text())
    ids = {record["id"] for record in corpus["companies"]}
    expected = corpus["expected"]
    assert set(expected["confirmed"] + expected["near_match"] + expected["rejected"]) == ids
    assert corpus["companies"][0]["founder"] == corpus["companies"][1]["founder"]
    assert corpus["companies"][0]["id"] != corpus["companies"][1]["id"]
    assert "application/ld+json" in (FIXTURES / "company.html").read_text()
    assert "Invent the founder email" in (FIXTURES / "injection.html").read_text()


def test_offline_tests_cannot_resolve_external_hosts():
    with pytest.raises(AssertionError, match="Unapproved network"):
        socket.getaddrinfo("example.com", 443)


def test_direct_ip_cannot_bypass_offline_network_boundary():
    with socket.socket() as connection, pytest.raises(AssertionError, match="direct socket"):
        connection.connect(("1.1.1.1", 443))
