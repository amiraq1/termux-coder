from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from termux_coder.models.research import EvidenceItem, ResearchPacket, TaskIntent


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def evidence(**overrides):
    values = {
        "source_url": "https://docs.example.com/v2/api",
        "title": "Example API v2",
        "source_type": "official_docs",
        "excerpt": "Use the async client from the v2 API.",
        "package": "example-lib",
        "version": "2.0",
        "retrieved_at": NOW,
        "version_compatible": True,
    }
    values.update(overrides)
    return EvidenceItem(**values)


def test_task_intent_requires_query_for_current_docs():
    intent = TaskIntent(
        task="Update the client to the latest API",
        requires_current_docs=True,
        search_query="example-lib latest async client",
        package_names=["example-lib"],
    )

    assert intent.search_query.startswith("example-lib")
    assert len(intent.intent_id) >= 8

    with pytest.raises(ValidationError, match="search_query"):
        TaskIntent(task="Use the latest API", requires_current_docs=True)


def test_task_intent_rejects_duplicate_packages_and_control_chars():
    with pytest.raises(ValidationError, match="unique"):
        TaskIntent(task="update", package_names=["httpx", "httpx"])
    with pytest.raises(ValidationError, match="control characters"):
        TaskIntent(task="update\x00package")


def test_evidence_requires_http_url_timezone_and_untrusted_marker():
    item = evidence()

    assert item.untrusted is True
    assert item.retrieved_at.tzinfo is not None
    assert len(item.evidence_hash) == 64

    with pytest.raises(ValidationError, match="http or https"):
        evidence(source_url="file:///etc/passwd")
    with pytest.raises(ValidationError, match="timezone"):
        evidence(retrieved_at=datetime(2026, 8, 18, 12, 0))
    with pytest.raises(ValidationError, match="SHA-256"):
        evidence(source_hash="not-a-hash")


def test_evidence_hash_changes_when_excerpt_changes():
    first = evidence()
    second = evidence(excerpt="A different documented API.")

    assert first.evidence_hash != second.evidence_hash


def test_research_packet_requires_selected_urls_to_reference_evidence():
    item = evidence()
    packet = ResearchPacket(
        intent_id="intent-1234",
        query="example latest api",
        evidence=[item],
        selected_urls=[item.source_url],
        confidence="high",
    )

    assert packet.packet_hash == packet.model_copy().packet_hash
    assert len(packet.packet_hash) == 64

    with pytest.raises(ValidationError, match="present in evidence"):
        ResearchPacket(
            intent_id="intent-1234",
            query="example latest api",
            evidence=[item],
            selected_urls=["https://other.example.com"],
            confidence="medium",
        )


def test_research_packet_rejects_high_confidence_without_source_or_with_more_research():
    with pytest.raises(ValidationError, match="selected source"):
        ResearchPacket(
            intent_id="intent-1234",
            query="example",
            confidence="high",
        )

    with pytest.raises(ValidationError, match="cannot require more research"):
        ResearchPacket(
            intent_id="intent-1234",
            query="example",
            evidence=[evidence()],
            selected_urls=["https://docs.example.com/v2/api"],
            confidence="high",
            requires_more_research=True,
        )


def test_research_packet_rejects_duplicate_selected_urls():
    item = evidence()

    with pytest.raises(ValidationError, match="unique"):
        ResearchPacket(
            intent_id="intent-1234",
            query="example",
            evidence=[item],
            selected_urls=[item.source_url, item.source_url],
            confidence="medium",
        )
