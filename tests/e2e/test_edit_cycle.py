from __future__ import annotations

import asyncio
import hashlib
import json

from termux_coder.core.trace import TraceStore
from termux_coder.providers.mock import MockResponse
from termux_coder.tools import fs

from conftest import E2EUI, build_orchestrator


def patch_text(old: str, new: str) -> str:
    return f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE"


def run(coro):
    return asyncio.run(coro)


def test_turn_bundle_e2e_preserves_metadata_across_verify(e2e_components, tmp_path):
    async def scenario():
        components = e2e_components
        components["registry"].register(
            "read_file",
            "Read a workspace file",
            fs.ReadFileArgs,
            fs.read_file,
        )
        trace = TraceStore(tmp_path / "traces.jsonl")
        patch = patch_text('return "Hello, " + name', 'return f"Hello, {name}!"')
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool("read-1", "read_file", {"path": "main.py"}),
                MockResponse.with_tool(
                    "patch-1",
                    "apply_patch",
                    {"path": "main.py", "patch": patch},
                ),
                MockResponse.text("Done."),
            ],
            trace_store=trace,
        )
        messages = [{
            "role": "user",
            "content": "Read main.py and update it safely",
            "turn_id": "turn-e2e",
            "task_id": "task-e2e",
        }]
        result = await orch.run_turn(messages)

        assert result.state.value == "idle"
        assert 'f"Hello, {name}!"' in (components["workspace"] / "main.py").read_text()

        bundle_messages = [
            message for message in messages if message.get("role") in {"assistant", "tool"}
        ]
        assert bundle_messages
        assert all(message.get("turn_id") == "turn-e2e" for message in bundle_messages)
        assert all(message.get("task_id") == "task-e2e" for message in bundle_messages)
        path_messages = [
            message for message in bundle_messages if message.get("related_paths")
        ]
        assert path_messages
        assert all("main.py" in message["related_paths"] for message in path_messages)
        assert any(
            message.get("tool_call_id", "").startswith("verify:turn-e2e:")
            for message in bundle_messages
        )

        audit_records = [
            json.loads(line)
            for line in components["audit"].path.read_text().splitlines()
            if line.strip()
        ]
        verification = [
            record for record in audit_records if record["event"] == "verification_result"
        ]
        assert verification
        assert verification[-1]["turn_id"] == "turn-e2e"
        assert verification[-1]["task_id"] == "task-e2e"
        assert verification[-1]["related_paths"] == ["main.py"]

        trace_records = trace.read("turn-e2e")
        assert trace_records
        assert all(record.get("task_id") == "task-e2e" for record in trace_records)
        assert any(
            record.get("event") == "tool_result"
            and "main.py" in record.get("related_paths", [])
            for record in trace_records
        )

    run(scenario())


def test_successful_edit_cycle(e2e_components):
    async def scenario():
        components = e2e_components
        patch = patch_text('return "Hello, " + name', 'return f"Hello, {name}!"')
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool("c1", "apply_patch", {"path": "main.py", "patch": patch}),
                MockResponse.text("Done."),
            ],
        )
        messages = [{"role": "user", "content": "Improve greet"}]
        result = await orch.run_turn(messages)

        assert result.state.value == "idle"
        assert 'f"Hello, {name}!"' in (components["workspace"] / "main.py").read_text()
        assert any(kind == "patch_applied" for kind, _ in components["ui"].events)
        assert any(kind == "verification_result" for kind, _ in components["ui"].events)
        assert [m["role"] for m in messages] == ["user", "assistant", "tool", "tool", "assistant"]

    run(scenario())


def test_rejection_does_not_modify_file(e2e_components):
    async def scenario():
        components = e2e_components
        original = (components["workspace"] / "main.py").read_text()
        components["ui"] = E2EUI(approve=False)
        components["ctx"].ui = components["ui"]
        patch = patch_text('return "Hello, " + name', "MALICIOUS")
        orch = build_orchestrator(
            components,
            [MockResponse.with_tool("c2", "apply_patch", {"path": "main.py", "patch": patch})],
            ui=components["ui"],
        )
        result = await orch.run_turn([{"role": "user", "content": "edit"}])
        assert result.state.value == "cancelled"
        assert (components["workspace"] / "main.py").read_text() == original

    run(scenario())


def test_external_change_after_preview_is_refused(e2e_components):
    async def scenario():
        components = e2e_components
        path = components["workspace"] / "main.py"
        patch = patch_text('return "Hello, " + name', 'return "Changed"')

        def mutate_before_approval(_kind, _payload):
            path.write_text(path.read_text() + "\n# external change\n")

        ui = E2EUI(approve=True, before_approval=mutate_before_approval)
        components["ctx"].ui = ui
        orch = build_orchestrator(
            components,
            [MockResponse.with_tool("c3", "apply_patch", {"path": "main.py", "patch": patch})],
            ui=ui,
        )
        result = await orch.run_turn([{"role": "user", "content": "edit"}])
        content = path.read_text()
        assert result.state.value == "idle"
        assert "external change" in content
        assert 'return "Changed"' not in content

    run(scenario())


def test_rollback_restores_content_and_mode(e2e_components):
    async def scenario():
        components = e2e_components
        path = components["workspace"] / "main.py"
        original = path.read_text()
        patch = patch_text('return "Hello, " + name', 'return "Changed"')
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool("c4", "apply_patch", {"path": "main.py", "patch": patch}),
                MockResponse.text("patched"),
            ],
        )
        result = await orch.run_turn([{"role": "user", "content": "edit"}])
        assert result.state.value == "idle"
        assert "Changed" in path.read_text()

        # rollback is separately policy-gated and uses the same approval contract.
        rollback = build_orchestrator(
            components,
            [MockResponse.with_tool("c5", "rollback_patch", {"path": "main.py"}), MockResponse.text("rolled back")],
        )
        result = await rollback.run_turn([{"role": "user", "content": "undo"}])
        assert result.state.value == "idle"
        assert path.read_text() == original

    run(scenario())


def test_multi_file_patch_plan_cycle(e2e_components):
    async def scenario():
        components = e2e_components
        util = components["workspace"] / "util.py"
        util.write_text("value = 2\n", encoding="utf-8")
        components["state"].read_files.add("util.py")
        components["state"].read_hashes["util.py"] = hashlib.sha256(
            util.read_bytes()
        ).hexdigest()
        patches = [
            {
                "path": "main.py",
                "patch": patch_text('return "Hello, " + name', 'return f"Hi, {name}"'),
                "reason": "update greeting",
            },
            {
                "path": "util.py",
                "patch": patch_text("value = 2", "value = 20"),
                "reason": "update shared value",
            },
        ]
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool(
                    "plan1",
                    "apply_patch_plan",
                    {"summary": "update greeting and value", "operations": patches},
                ),
                MockResponse.text("Done."),
            ],
        )
        result = await orch.run_turn([{"role": "user", "content": "update both files"}])

        assert result.state.value == "idle"
        assert 'f"Hi, {name}"' in (components["workspace"] / "main.py").read_text()
        assert (components["workspace"] / "util.py").read_text() == "value = 20\n"

    run(scenario())


def test_multi_file_plan_rolls_back_when_verification_fails(e2e_components):
    async def scenario():
        components = e2e_components
        workspace = components["workspace"]
        original = (workspace / "main.py").read_text()
        (workspace / "fail_test.py").write_text("def test_failure():\n    assert False\n", encoding="utf-8")
        (workspace / ".termux-coder.toml").write_text(
            "[verification]\ncommand = [\"python\", \"-m\", \"pytest\", \"-q\", \"fail_test.py\"]\ntimeout_s = 10\n",
            encoding="utf-8",
        )
        patch = patch_text('return "Hello, " + name', 'return "Broken"')
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool(
                    "plan2",
                    "apply_patch_plan",
                    {
                        "summary": "intentionally failing verification",
                        "operations": [
                            {"path": "main.py", "patch": patch, "reason": "test rollback"}
                        ],
                    },
                )
            ],
        )
        messages = [{
            "role": "user",
            "content": "Apply and verify the change in main.py",
            "turn_id": "turn-rollback",
            "task_id": "task-restore",
        }]
        result = await orch.run_turn(messages)

        assert result.state.value == "failed"
        assert (workspace / "main.py").read_text() == original
        assert any(kind == "patch_plan_rollback" for kind, _ in components["ui"].events)
        assert components["state"].applied_patches == []

        bundle_messages = [
            message for message in messages if message.get("role") in {"assistant", "tool"}
        ]
        assert bundle_messages
        assert all(message.get("task_id") == "task-restore" for message in bundle_messages)
        assert any("main.py" in message.get("related_paths", []) for message in bundle_messages)
        assert not any("changed_paths" in message for message in bundle_messages)

    run(scenario())


def test_verification_skipped_is_terminal_and_does_not_retry_mutation(e2e_components):
    async def scenario():
        components = e2e_components
        (components["workspace"] / ".termux-coder.toml").unlink()
        patch = patch_text('return "Hello, " + name', 'return "Changed"')
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool("skip1", "apply_patch", {"path": "main.py", "patch": patch}),
                MockResponse.with_tool("skip2", "apply_patch", {"path": "main.py", "patch": patch}),
            ],
        )

        result = await orch.run_turn([{"role": "user", "content": "edit and verify"}])

        assert result.state.value == "failed"
        assert result.error.startswith("verification skipped:")
        assert [item.tool for item in result.tool_results] == ["apply_patch"]
        assert any(kind == "verification_required" for kind, _ in components["ui"].events)

    run(scenario())


def test_read_only_first_edit_request_recovers_to_patch(e2e_components):
    async def scenario():
        components = e2e_components
        patch = patch_text('return "Hello, " + name', 'return "Recovered"')
        orch = build_orchestrator(
            components,
            [
                MockResponse.with_tool("map1", "list_dir", {"path": "."}),
                MockResponse.text("The repository map is ready, but the requested edit is not applied yet."),
                MockResponse.with_tool("patch1", "apply_patch", {"path": "main.py", "patch": patch}),
                MockResponse.text("Done after the approved patch."),
            ],
        )

        result = await orch.run_turn([{"role": "user", "content": "Inspect the repository and update main.py safely"}])

        assert result.state.value == "idle"
        assert 'return "Recovered"' in (components["workspace"] / "main.py").read_text()
        assert any(kind == "edit_recovery_retry" for kind, _ in components["ui"].events)
        assert any(kind == "preview_ready" for kind, _ in components["ui"].events)
        assert any(kind == "verification_result" for kind, _ in components["ui"].events)

    run(scenario())
