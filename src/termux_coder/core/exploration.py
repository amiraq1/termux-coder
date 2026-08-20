from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable, Iterable, Literal, List, Set, Optional

from pydantic import BaseModel, Field

TaskStatus = Literal["pending", "running", "completed", "failed", "timeout", "cancelled"]
TodoStatus = Literal["pending", "running", "completed", "failed"]

READ_ONLY_TOOLS = frozenset({"list_dir", "read_file", "search_text", "repo_map"})

class ExplorationTaskSpec(BaseModel):
    task_id: str
    title: str
    scope: str

class ExplorationEvent(BaseModel):
    kind: str
    turn_id: str
    task_id: str
    timestamp: float = Field(default_factory=time.monotonic)
    detail: Optional[str] = None
    related_paths: List[str] = Field(default_factory=list)

class ExplorationTask(BaseModel):
    turn_id: str
    task_id: str
    title: str
    scope: str
    status: TaskStatus = "pending"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    elapsed_ms: float = 0.0
    token_count: int = 0
    events: List[str] = Field(default_factory=list)
    related_paths: Set[str] = Field(default_factory=set)
    error: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    def start(self) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot start task from {self.status}")
        self.status = "running"
        self.started_at = time.monotonic()
        self.finished_at = None
        self.elapsed_ms = 0.0
        self.error = None

    def record(self, line: str, *, tokens: int = 0, paths: Iterable[str] = ()) -> None:
        self.events.append(str(line))
        # Keep only the last 40 events to prevent bloat if needed, but Pydantic list doesn't have maxlen
        if len(self.events) > 40:
            self.events = self.events[-40:]
        self.token_count += max(0, int(tokens))
        for p in paths:
            self.related_paths.add(p)
        self.refresh_elapsed()

    def finish(self, status: TaskStatus = "completed", error: Optional[str] = None) -> None:
        if status not in {"completed", "failed", "timeout", "cancelled"}:
            raise ValueError(f"invalid terminal task status: {status}")
        if self.status in {"failed", "timeout", "cancelled"} and status == "completed":
            raise ValueError(f"Cannot transition from {self.status} to completed")
        self.refresh_elapsed()
        if not self.finished_at:
            self.finished_at = time.monotonic()
        self.refresh_elapsed()
        self.status = status
        self.error = error

    def refresh_elapsed(self) -> None:
        if self.started_at is not None:
            end = self.finished_at or time.monotonic()
            self.elapsed_ms = max(0.0, (end - self.started_at) * 1000)

    def snapshot(self) -> dict[str, Any]:
        self.refresh_elapsed()
        return self.model_dump(mode="json")


class TodoItem(BaseModel):
    todo_id: str
    title: str
    status: TodoStatus = "pending"


Worker = Callable[[ExplorationTask], Awaitable[Any]]
UpdateCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class ExplorationEventStream:
    """Small async fan-out stream for live exploration updates."""

    def __init__(self) -> None:
        self._subscribers: list[UpdateCallback] = []

    def subscribe(self, callback: UpdateCallback) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: UpdateCallback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def publish(self, kind: str, payload: dict[str, Any]) -> None:
        for callback in tuple(self._subscribers):
            result = callback(kind, payload)
            if asyncio.iscoroutine(result):
                await result

    async def __call__(self, kind: str, payload: dict[str, Any]) -> None:
        await self.publish(kind, payload)


class ExplorationManager:
    """Bounded read-only task manager for repository exploration."""

    def __init__(
        self,
        turn_id: str,
        *,
        max_tasks: int = 6,
        max_events_per_task: int = 40,
        on_update: UpdateCallback | None = None,
    ) -> None:
        if max_tasks < 1:
            raise ValueError("max_tasks must be positive")
        if max_events_per_task < 1:
            raise ValueError("max_events_per_task must be positive")
        self.turn_id = turn_id
        self.max_tasks = max_tasks
        self.max_events_per_task = max_events_per_task
        self.on_update = on_update
        self.tasks: dict[str, ExplorationTask] = {}
        self.todos: list[TodoItem] = []
        self._cancelled = False

    def configure(self, specs: Iterable[ExplorationTaskSpec]) -> list[ExplorationTask]:
        specs = list(specs)
        if len(specs) > self.max_tasks:
            raise ValueError(f"at most {self.max_tasks} exploration tasks are allowed")
        if len({spec.task_id for spec in specs}) != len(specs):
            raise ValueError("exploration task ids must be unique")
        self.tasks = {
            spec.task_id: ExplorationTask(
                turn_id=self.turn_id,
                task_id=spec.task_id,
                title=spec.title,
                scope=spec.scope,
            )
            for spec in specs
        }
        self.todos = [TodoItem(todo_id=spec.task_id, title=spec.title) for spec in specs]
        return list(self.tasks.values())

    def set_todo_status(self, todo_id: str, status: TodoStatus) -> None:
        for item in self.todos:
            if item.todo_id == todo_id:
                item.status = status
                return
        raise KeyError(f"unknown todo: {todo_id}")

    def task(self, task_id: str) -> ExplorationTask:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown exploration task: {task_id}") from exc

    async def _notify(self, kind: str, **payload: Any) -> None:
        if self.on_update is None:
            return
        result = self.on_update(kind, payload)
        if asyncio.iscoroutine(result):
            await result

    async def _notify_todos(self) -> None:
        await self._notify(
            "exploration_todos",
            items=[item.model_dump(mode="json") for item in self.todos],
        )

    async def start_task(self, task_id: str) -> ExplorationTask:
        task = self.task(task_id)
        task.start()
        self.set_todo_status(task_id, "running")
        await self._notify_todos()
        await self._notify("exploration_task_start", task=task.snapshot())
        return task

    async def record_tool(
        self,
        task_id: str,
        tool: str,
        detail: str = "",
        *,
        tokens: int = 0,
        paths: Iterable[str] = (),
    ) -> None:
        if tool not in READ_ONLY_TOOLS:
            raise PermissionError(f"exploration is read-only; tool denied: {tool}")
        task = self.task(task_id)
        task.record(f"{tool.upper()} {detail}".strip(), tokens=tokens, paths=paths)
        await self._notify(
            "exploration_tool_result",
            task_id=task_id,
            tool=tool,
            detail=detail,
            tokens=max(0, int(tokens)),
            paths=list(paths),
            task=task.snapshot(),
        )

    async def finish_task(
        self,
        task_id: str,
        *,
        status: TaskStatus = "completed",
        error: str | None = None,
    ) -> None:
        task = self.task(task_id)
        task.finish(status, error)
        self.set_todo_status(task_id, "completed" if status == "completed" else "failed")
        await self._notify_todos()
        await self._notify("exploration_task_end", task=task.snapshot())

    def cancel(self) -> None:
        self._cancelled = True

    async def run(
        self,
        specs: Iterable[ExplorationTaskSpec],
        worker: Worker,
    ) -> list[Any]:
        self._cancelled = False
        tasks = self.configure(specs)
        semaphore = asyncio.Semaphore(self.max_tasks)

        async def guarded(task: ExplorationTask) -> Any:
            if self._cancelled:
                task.finish("cancelled")
                self.set_todo_status(task.task_id, "failed")
                await self._notify_todos()
                return None
            async with semaphore:
                if self._cancelled:
                    task.finish("cancelled")
                    self.set_todo_status(task.task_id, "failed")
                    await self._notify_todos()
                    return None
                await self.start_task(task.task_id)
                try:
                    result = await worker(task)
                except asyncio.CancelledError:
                    await self.finish_task(task.task_id, status="cancelled")
                    raise
                except TimeoutError:
                    await self.finish_task(task.task_id, status="timeout", error="timeout after execution limit")
                    # don't re-raise timeout for exploration task, just mark failed
                    return None
                except Exception as exc:
                    await self.finish_task(task.task_id, status="failed", error=str(exc))
                    return None # Don't raise, just fail task
                await self.finish_task(task.task_id)
                return result

        return list(await asyncio.gather(*(guarded(task) for task in tasks)))

    def snapshot(self) -> dict[str, Any]:
        return {
            "tasks": [task.snapshot() for task in self.tasks.values()],
            "todos": [item.model_dump(mode="json") for item in self.todos],
            "cancelled": self._cancelled,
        }

__all__ = [
    "ExplorationEventStream",
    "ExplorationManager",
    "ExplorationTask",
    "ExplorationTaskSpec",
    "ExplorationEvent",
    "READ_ONLY_TOOLS",
    "TodoItem",
]
