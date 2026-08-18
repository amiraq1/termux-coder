from scripts import threat_audit


def test_truth_audit_classifies_repository_evidence(monkeypatch):
    monkeypatch.setattr(threat_audit, "_collect_count", lambda: "249")
    monkeypatch.setattr(threat_audit, "_latest_commit", lambda _paths: "abc1234 2026-08-18")
    monkeypatch.setattr(
        threat_audit,
        "_run_targeted_tests",
        lambda _threat: ("PASS", "targeted tests passed"),
    )

    report, stats = threat_audit.audit(verify=True)

    assert "| T1 | Path traversal and symlink escape | **IMPLEMENTED** |" in report
    assert "| T4 | Secrets written to audit logs | **IMPLEMENTED** |" in report
    assert "| T15 | Network stream interception | **PARTIAL** |" in report
    assert "IMPLEMENTED: `7`" in report
    assert stats == {"IMPLEMENTED": 7, "PARTIAL": 1, "PLANNED": 3}


def test_truth_audit_does_not_treat_missing_proof_as_implemented(monkeypatch):
    missing = threat_audit.Threat(
        "TX",
        "Synthetic missing threat",
        ("does/not/exist.py",),
        ("tests/does_not_exist.py",),
    )
    monkeypatch.setattr(threat_audit, "THREATS", (missing,))
    monkeypatch.setattr(threat_audit, "_collect_count", lambda: "0")

    report, stats = threat_audit.audit(verify=False)

    assert "| TX | Synthetic missing threat | **PLANNED** |" in report
    assert stats == {"IMPLEMENTED": 0, "PARTIAL": 0, "PLANNED": 1}
