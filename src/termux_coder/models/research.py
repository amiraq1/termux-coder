from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WEB_SCHEMES = {"http", "https"}

SourceType = Literal["official_docs", "package_registry", "repository", "other"]
Confidence = Literal["low", "medium", "high"]


def _validate_http_url(value: str, field_name: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in _WEB_SCHEMES:
        raise ValueError(f"{field_name} must use http or https")
    if not parsed.hostname:
        raise ValueError(f"{field_name} must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} contains an invalid port") from exc
    return value


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TaskIntent(BaseModel):
    """The structured intent that decides whether fresh documentation is needed."""

    model_config = ConfigDict(extra="forbid")

    intent_id: str = Field(default_factory=lambda: uuid4().hex, min_length=8, max_length=64)
    task: str = Field(min_length=1, max_length=4000)
    requires_current_docs: bool = False
    search_query: str | None = Field(default=None, max_length=200)
    package_names: list[str] = Field(default_factory=list, max_length=12)
    version_constraints: dict[str, str] = Field(default_factory=dict, max_length=12)

    @field_validator("task", "search_query")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        if _CONTROL_CHARS_RE.search(value):
            raise ValueError("text contains control characters")
        return value

    @field_validator("package_names")
    @classmethod
    def validate_packages(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            value = value.strip()
            if not value or _CONTROL_CHARS_RE.search(value):
                raise ValueError("package names must be non-empty and printable")
            if len(value) > 128:
                raise ValueError("package names must be at most 128 characters")
            cleaned.append(value)
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("package names must be unique")
        return cleaned

    @field_validator("version_constraints")
    @classmethod
    def validate_versions(cls, values: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for package, constraint in values.items():
            package = package.strip()
            constraint = constraint.strip()
            if not package or not constraint:
                raise ValueError("version constraints must have non-empty keys and values")
            if _CONTROL_CHARS_RE.search(package) or _CONTROL_CHARS_RE.search(constraint):
                raise ValueError("version constraints must be printable")
            cleaned[package] = constraint
        return cleaned

    @model_validator(mode="after")
    def validate_research_query(self) -> "TaskIntent":
        if self.requires_current_docs and not self.search_query:
            raise ValueError("search_query is required when current docs are requested")
        return self


class EvidenceItem(BaseModel):
    """A bounded, version-aware excerpt from an untrusted web source."""

    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    source_type: SourceType = "other"
    excerpt: str = Field(min_length=1, max_length=4000)
    package: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=128)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_hash: str | None = None
    version_compatible: bool | None = None
    version_note: str | None = Field(default=None, max_length=500)
    untrusted: Literal[True] = True
    possible_prompt_injection: bool = False

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _validate_http_url(value, "source_url")

    @field_validator("title", "excerpt", "package", "version", "version_note")
    @classmethod
    def validate_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("content must not be empty")
        if _CONTROL_CHARS_RE.search(value):
            raise ValueError("content contains control characters")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")
        return value.astimezone(timezone.utc)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("source_hash must be a lowercase SHA-256 hex digest")
        return value

    @property
    def evidence_hash(self) -> str:
        """Stable fingerprint of the evidence fields used by the planner."""
        return _canonical_hash(
            {
                "source_url": self.source_url,
                "title": self.title,
                "source_type": self.source_type,
                "excerpt": self.excerpt,
                "package": self.package,
                "version": self.version,
                "source_hash": self.source_hash,
                "version_compatible": self.version_compatible,
            }
        )


class ResearchPacket(BaseModel):
    """Validated evidence packet passed from research into planning."""

    model_config = ConfigDict(extra="forbid")

    packet_id: str = Field(default_factory=lambda: uuid4().hex, min_length=8, max_length=64)
    intent_id: str = Field(min_length=8, max_length=64)
    query: str = Field(min_length=1, max_length=200)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=8)
    selected_urls: list[str] = Field(default_factory=list, max_length=8)
    confidence: Confidence = "low"
    requires_more_research: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value or _CONTROL_CHARS_RE.search(value):
            raise ValueError("query must be non-empty and printable")
        return value

    @field_validator("selected_urls")
    @classmethod
    def validate_selected_urls(cls, values: list[str]) -> list[str]:
        cleaned = [_validate_http_url(value, "selected_url") for value in values]
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("selected_urls must be unique")
        return cleaned

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_selection(self) -> "ResearchPacket":
        evidence_urls = {item.source_url for item in self.evidence}
        if not set(self.selected_urls).issubset(evidence_urls):
            raise ValueError("selected_urls must reference URLs present in evidence")
        if self.confidence == "high" and not self.selected_urls:
            raise ValueError("high confidence requires at least one selected source")
        if self.requires_more_research and self.confidence == "high":
            raise ValueError("high confidence cannot require more research")
        return self

    @property
    def packet_hash(self) -> str:
        """Stable fingerprint linking the evidence packet to a future PatchPlan."""
        return _canonical_hash(
            {
                "intent_id": self.intent_id,
                "query": self.query,
                "evidence_hashes": [item.evidence_hash for item in self.evidence],
                "selected_urls": self.selected_urls,
                "confidence": self.confidence,
                "requires_more_research": self.requires_more_research,
            }
        )


__all__ = ["Confidence", "EvidenceItem", "ResearchPacket", "SourceType", "TaskIntent"]
