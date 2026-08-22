"""
Regression tests for TaskActivityWidget (Phase 2).

Verify the Textual property-collision fix:
  * TaskActivityWidget must not assign to Widget.task (a read-only property
    on MessagePump), otherwise constructing the widget raises
    AttributeError("can't set attribute 'task'") whenever exploration
    renders a task row.
  * Failed/cancelled/timed-out states must use an existing Glyphs field
    (status_offline), not a phantom 'cross' attribute that does not exist
    on the Glyphs object.
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from termux_coder.ui.app import TaskActivityWidget
from termux_coder.ui.glyphs import current_glyphs


class _HostApp(App):
    """Minimal Textual app that mounts a single TaskActivityWidget."""

    def __init__(self) -> None:
        super().__init__()
        self.widget: TaskActivityWidget | None = None

    def compose(self) -> ComposeResult:
        self.widget = TaskActivityWidget()
        yield self.widget


_TERMINAL = ["failed", "timeout", "cancelled", "completed"]
_ALL = ["pending", "running", "completed", "failed", "timeout", "cancelled"]


def _task(status: str = "running", **kw) -> dict:
    t = {
        "task_id": "dissect:turn-1:core",
        "title": "Core module",
        "status": status,
        "token_count": 4200,
        "elapsed_ms": 1250.0,
        "events": ["read_file: src/main.py", "read_file: src/config.py"],
        "error": None,
    }
    t.update(kw)
    return t


@pytest.mark.anyio
async def test_widget_does_not_shadow_reserved_task_property():
    """Phase 2: Widget.task is a read-only Textual property; the widget must not overwrite it."""
    async with _HostApp().run_test() as pilot:
        assert pilot.app.widget is not None
        w = pilot.app.widget
        # 'task' is a read-only property on MessagePump (no setter). The
        # committed code did `self.task = task or {}` which raises
        # AttributeError("can't set attribute 'task'"). Storing in _task_data
        # avoids the collision entirely.
        assert "task" not in w.__dict__
        assert isinstance(getattr(type(w), "task", None), property)


@pytest.mark.parametrize("status", _ALL)
@pytest.mark.anyio
async def test_widget_renders_every_status_without_error(status: str):
    """Phase 2: every status renders — proves no phantom glyph attribute is referenced."""
    async with _HostApp().run_test() as pilot:
        w = pilot.app.widget
        kw = {"error": "boom"} if status in _TERMINAL and status != "completed" else {}
        w.update_task(_task(status, **kw))
        # All fields round-trip into the private storage.
        stored = w._task_data
        assert stored["task_id"] == "dissect:turn-1:core"
        assert stored["title"] == "Core module"
        assert stored["events"] == ["read_file: src/main.py", "read_file: src/config.py"]
        assert stored["token_count"] == 4200
        assert stored["elapsed_ms"] == 1250.0
        assert stored["status"] == status


def test_glyphs_expose_status_offline_not_cross():
    """Phase 2 evidence: Glyphs has NO 'cross' attribute; status_offline is the field to use."""
    g = current_glyphs()
    assert not hasattr(g, "cross"), (
        "Glyphs has no 'cross' attribute — the committed code referenced a phantom glyph"
    )
    assert hasattr(g, "status_offline"), "Glyphs must expose 'status_offline' for terminal failures"


@pytest.mark.anyio
async def test_widget_failed_and_cancelled_use_status_offline_glyph():
    """Phase 2: FAILED / CANCELLED rows render the status_offline marker, not a crash."""
    g = current_glyphs()
    async with _HostApp().run_test() as pilot:
        w = pilot.app.widget

        w.update_task(_task("failed", error="broken"))
        content = getattr(w, "_Static__content", "")
        assert g.status_offline in content

        w.update_task(_task("cancelled", error="aborted"))
        content = getattr(w, "_Static__content", "")
        assert g.status_offline in content

        w.update_task(_task("timeout", error="slow"))
        content = getattr(w, "_Static__content", "")
        assert g.status_offline in content
