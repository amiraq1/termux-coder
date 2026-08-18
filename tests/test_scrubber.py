import json

from termux_coder.security.audit import AuditLog
from termux_coder.security.scrubber import SecretScrubber


def test_scrub_text_redacts_known_credentials():
    scrubber = SecretScrubber()
    text = (
        "sk-abcdefghijklmnopqrstuvwxyz123456 "
        "ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9 "
        "https://user:secret-pass@example.com/api"
    )

    result = scrubber.scrub(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in result
    assert "eyJhbGciOiJIUzI1NiJ9" not in result
    assert "secret-pass" not in result
    assert "[OPENAI_KEY_REDACTED]" in result
    assert "[GITHUB_TOKEN_REDACTED]" in result
    assert "[BEARER_TOKEN_REDACTED]" in result
    assert "[URL_PASSWORD_REDACTED]" in result


def test_scrub_structured_payload_redacts_sensitive_keys_without_mutation():
    scrubber = SecretScrubber()
    payload = {
        "query": "official docs",
        "api_key": "short-secret-is-still-sensitive",
        "headers": {"Authorization": "Bearer secret-token"},
        "items": [{"password": "p@ssword"}],
    }

    result = scrubber.scrub(payload)

    assert payload["api_key"] == "short-secret-is-still-sensitive"
    assert result["api_key"] == "[REDACTED]"
    assert result["headers"]["Authorization"] == "[REDACTED]"
    assert result["items"][0]["password"] == "[REDACTED]"
    assert result["query"] == "official docs"


def test_audit_log_scrubs_before_jsonl_persistence(tmp_path):
    secret = "gho_abcdefghijklmnopqrstuvwxyz123456"
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)

    audit.log(
        "tool_call",
        tool="web_search",
        api_key="sk-local-test-secret",
        headers={"Authorization": f"Bearer {secret}"},
    )

    raw = path.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert "sk-local-test-secret" not in raw
    assert secret not in raw
    assert record["api_key"] == "[REDACTED]"
    assert record["headers"]["Authorization"] == "[REDACTED]"


def test_normal_text_is_preserved():
    text = "The official documentation page is public and bounded."
    assert SecretScrubber().scrub(text) == text
