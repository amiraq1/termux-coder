import json

from termux_coder.security.audit import AuditLog


def test_audit_writes_jsonl(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.log("patch_applied", path="a.py")
    line = (tmp_path / "audit.jsonl").read_text().strip()
    assert json.loads(line)["event"] == "patch_applied"
