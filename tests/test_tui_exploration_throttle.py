import time

from termux_coder.ui.app import TermuxCoderApp


def test_exploration_updates_are_coalesced_until_timer_flush():
    app = object.__new__(TermuxCoderApp)
    app._exploration_last_render = time.monotonic()
    app._exploration_render_interval = 0.16
    app._exploration_pending_tasks = {}
    app._exploration_pending_todos = None
    app._exploration_render_dirty = False
    app._exploration_render_scheduled = False

    timers = []
    applied_tasks = []
    applied_todos = []
    headers = []

    app.set_timer = lambda delay, callback: timers.append((delay, callback))
    app._apply_exploration_task = lambda task: applied_tasks.append(task)
    app._apply_exploration_todos = lambda items: applied_todos.append(items)
    app._render_exploration_header = lambda: headers.append(True)

    app.update_exploration_task({"task_id": "core", "status": "running", "token_count": 1})
    app.update_exploration_task({"task_id": "core", "status": "running", "token_count": 2})
    app.update_exploration_task({"task_id": "core", "status": "done", "token_count": 3})
    app.update_exploration_todos([{"todo_id": "core", "title": "Core", "status": "done"}])

    assert len(timers) == 1
    assert applied_tasks == []
    assert applied_todos == []

    timers[0][1]()

    assert len(applied_tasks) == 1
    assert applied_tasks[0]["status"] == "done"
    assert applied_tasks[0]["token_count"] == 3
    assert applied_todos == [[{"todo_id": "core", "title": "Core", "status": "done"}]]
    assert len(headers) == 1
    assert app._exploration_render_dirty is False


def test_exploration_finish_flushes_pending_updates_immediately():
    app = object.__new__(TermuxCoderApp)
    app._exploration_last_render = time.monotonic()
    app._exploration_render_interval = 0.16
    app._exploration_pending_tasks = {}
    app._exploration_pending_todos = None
    app._exploration_render_dirty = False
    app._exploration_render_scheduled = False
    app._exploration_widgets = {}
    app._exploration_todos = []

    applied_tasks = []
    applied_todos = []
    headers = []

    app.set_timer = lambda _delay, _callback: None
    app._apply_exploration_task = lambda task: applied_tasks.append(task)
    app._apply_exploration_todos = lambda items: applied_todos.append(items)
    app._render_exploration_header = lambda: headers.append(True)

    app.update_exploration_task({"task_id": "tools", "status": "done"})
    app.update_exploration_todos([{"todo_id": "tools", "title": "Tools", "status": "done"}])
    app.finish_exploration()

    assert applied_tasks == [{"task_id": "tools", "status": "done"}]
    assert applied_todos == [[{"todo_id": "tools", "title": "Tools", "status": "done"}]]
    assert headers
