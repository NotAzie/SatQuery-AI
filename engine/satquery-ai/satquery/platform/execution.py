"""Dependency-aware local execution infrastructure."""

from __future__ import annotations

import asyncio
import heapq
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from ..errors import ExecutionError, OperationTimeoutError, SatQueryError
from .contracts import (
    ExecutionPlan,
    ExecutionProgress,
    ExecutionResult,
    ExecutionStatus,
    Task,
    TaskExecution,
    TaskStatus,
)
from .observability import log_event, redact_sensitive, trace_context
from .registry import ComponentRegistry
from .execution_journal import ExecutionJournal, TaskOutputEncodingError

TaskHandler = Callable[["TaskContext"], Any]
ProgressCallback = Callable[[ExecutionProgress], Any]


def _execution_policy(task: Task) -> dict[str, Any]:
    return {
        "accept_partial_dependencies": task.accept_partial_dependencies,
        "max_attempts": task.max_attempts,
        "retry_delay_seconds": task.retry_delay_seconds,
        "retry_safe": task.retry_safe,
        "timeout_seconds": task.timeout_seconds,
    }


@dataclass(frozen=True)
class TaskContext:
    task: Task
    dependencies: Mapping[str, Any]
    resources: Mapping[str, Any]
    mission_id: Optional[str]
    investigation_id: Optional[str]
    trace_id: str
    cancellation: ExecutionCancellationToken | None = None


class ExecutionCancellationToken:
    """Cooperative cancellation signal shared by a running workflow and its owner."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "Cancellation requested by the operator.") -> None:
        if not self._event.is_set():
            self.reason = reason
            self._event.set()

    async def wait(self) -> None:
        await self._event.wait()


class ExecutionEngine:
    """Runs independent task branches concurrently; it does not plan reasoning."""

    def __init__(
        self,
        handlers: Optional[ComponentRegistry[TaskHandler]] = None,
        *,
        max_concurrency: Optional[int] = None,
        progress_callback: Optional[ProgressCallback] = None,
        platform_config: Any = None,
        journal: ExecutionJournal | None = None,
    ) -> None:
        if max_concurrency is None and platform_config is not None:
            max_concurrency = platform_config.execution.max_concurrency
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be greater than zero or None")
        self.handlers = handlers if handlers is not None else ComponentRegistry()
        self.max_concurrency = max_concurrency
        self.progress_callback = progress_callback
        self.journal = journal

    async def execute(
        self,
        plan: ExecutionPlan,
        *,
        resources: Optional[Mapping[str, Any]] = None,
        cancellation: ExecutionCancellationToken | None = None,
        resume: bool = False,
    ) -> ExecutionResult:
        if resume and self.journal is None:
            raise ExecutionError("Execution resumption requires a configured execution journal.")
        previous_events = (
            self.journal.events(plan.plan_id)
            if resume and self.journal is not None else ()
        )
        checkpoints = self.journal.begin(plan, resume=resume) if self.journal else {}
        if resume:
            uncertain = {
                event["payload"].get("task_id")
                for event in previous_events
                if event["event_type"] in {"task.running", "task.failed", "task.cancelled"}
            }.difference(checkpoints)
            unsafe = sorted(
                task_id for task_id in uncertain
                if task_id in {task.task_id for task in plan.tasks}
                and not next(task for task in plan.tasks if task.task_id == task_id).retry_safe
            )
            if unsafe:
                raise ExecutionError(
                    "Resumption would replay a task whose side effects are not declared retry-safe.",
                    context={"tasks": unsafe},
                )
        trace_id = uuid.uuid4().hex
        started_at = datetime.now(timezone.utc)
        started_clock = time.perf_counter()
        concurrency = plan.max_concurrency or self.max_concurrency or (os.cpu_count() or 1)
        process_cpu_started = time.process_time()
        semaphore = asyncio.Semaphore(concurrency)
        tasks_by_id = {task.task_id: task for task in plan.tasks}
        results: dict[str, TaskExecution] = dict(checkpoints)
        unknown_checkpoints = set(results).difference(tasks_by_id)
        if unknown_checkpoints:
            raise ExecutionError(
                "Execution journal contains checkpoints outside the current plan.",
                context={"tasks": sorted(unknown_checkpoints)},
            )
        completed_count = len(results)

        with trace_context(trace_id):
            log_event(
                "execution.started",
                plan_id=plan.plan_id,
                mission_id=plan.mission_id,
                investigation_id=plan.investigation_id,
                task_count=len(plan.tasks),
                max_concurrency=concurrency,
                parameters=redact_sensitive(plan.metadata),
            )
            if self.journal:
                self.journal.record_event(plan.plan_id, "execution.scheduler_started", {
                    "trace_id": trace_id,
                    "resumed_task_ids": sorted(results),
                    "total_tasks": len(plan.tasks),
                })
            pending_dependencies = {
                task_id: set(task.depends_on).difference(results)
                for task_id, task in tasks_by_id.items()
            }
            rejected_dependencies = {task_id: False for task_id in tasks_by_id}
            dependents: dict[str, list[str]] = {task_id: [] for task_id in tasks_by_id}
            for task in plan.tasks:
                for dependency in task.depends_on:
                    dependents[dependency].append(task.task_id)
            for values in dependents.values():
                values.sort()
            ready = [
                (task_id, task_id)
                for task_id, dependencies in pending_dependencies.items()
                if not dependencies and task_id not in results
            ]
            heapq.heapify(ready)
            remaining = set(tasks_by_id).difference(results)
            running: dict[asyncio.Task, Task] = {}
            cancellation_waiter = (
                asyncio.create_task(cancellation.wait()) if cancellation else None
            )

            async def finish(task: Task, outcome: TaskExecution) -> None:
                nonlocal completed_count
                if self.journal and outcome.status == TaskStatus.SUCCEEDED:
                    try:
                        self.journal.checkpoint(plan, outcome)
                    except TaskOutputEncodingError as exc:
                        self.journal.record_event(
                            plan.plan_id,
                            "task.checkpoint_unavailable",
                            {"task_id": task.task_id, "reason": str(exc)},
                        )
                if self.journal:
                    self.journal.record_event(
                        plan.plan_id,
                        f"task.{outcome.status.value}",
                        {
                            "task_id": task.task_id,
                            "trace_id": trace_id,
                            "attempts": outcome.attempts,
                            "error": redact_sensitive(outcome.error),
                            "duration_seconds": outcome.duration_seconds,
                        },
                    )
                results[task.task_id] = outcome
                remaining.discard(task.task_id)
                completed_count += 1
                await self._report(
                    task, outcome.status, completed_count, len(plan.tasks),
                    plan, trace_id,
                )
                for child_id in dependents[task.task_id]:
                    child = tasks_by_id[child_id]
                    if outcome.status == TaskStatus.CANCELLED or (
                        outcome.status in {TaskStatus.FAILED, TaskStatus.SKIPPED}
                        and not child.accept_partial_dependencies
                    ):
                        rejected_dependencies[child_id] = True
                    pending_dependencies[child_id].discard(task.task_id)
                    if pending_dependencies[child_id]:
                        continue
                    if rejected_dependencies[child_id]:
                        await finish(
                            child,
                            TaskExecution(
                                task_id=child.task_id,
                                handler=child.handler,
                                description=child.description,
                                depends_on=child.depends_on,
                                parameters=redact_sensitive(child.parameters),
                                execution_policy=_execution_policy(child),
                                status=TaskStatus.SKIPPED,
                                attempts=0,
                                error="A dependency did not satisfy this task's execution policy.",
                                duration_seconds=0,
                            ),
                        )
                    else:
                        heapq.heappush(ready, (child.task_id, child.task_id))

            try:
                while ready or running:
                    if cancellation and cancellation.is_cancelled:
                        break
                    while ready and len(running) < concurrency:
                        _, task_id = heapq.heappop(ready)
                        task = tasks_by_id[task_id]
                        dependencies = {
                            dependency: results[dependency].output
                            for dependency in task.depends_on
                            if results[dependency].status == TaskStatus.SUCCEEDED
                        }
                        future = asyncio.create_task(self._run_task(
                            task, dependencies, plan, trace_id, completed_count,
                            semaphore, resources or {}, cancellation,
                        ))
                        running[future] = task
                    if not running:
                        if remaining:
                            raise ExecutionError(
                                "Execution stalled with unresolved tasks.",
                                context={"plan_id": plan.plan_id, "tasks": sorted(remaining)},
                            )
                        break
                    waiters = set(running)
                    if cancellation_waiter is not None:
                        waiters.add(cancellation_waiter)
                    done, _ = await asyncio.wait(
                        waiters, return_when=asyncio.FIRST_COMPLETED
                    )
                    cancellation_requested = (
                        cancellation_waiter is not None
                        and cancellation_waiter in done
                    )
                    completed_futures = sorted(
                        (item for item in done if item in running),
                        key=lambda item: running[item].task_id,
                    )
                    for future in completed_futures:
                        task = running.pop(future)
                        try:
                            outcome = future.result()
                        except asyncio.CancelledError:
                            outcome = TaskExecution(
                                task_id=task.task_id, handler=task.handler,
                                description=task.description, depends_on=task.depends_on,
                                parameters=redact_sensitive(task.parameters),
                                execution_policy=_execution_policy(task),
                                status=TaskStatus.CANCELLED, attempts=0,
                                error="Execution was cancelled.", duration_seconds=0,
                            )
                        except BaseException as exc:
                            outcome = TaskExecution(
                                task_id=task.task_id, handler=task.handler,
                                description=task.description, depends_on=task.depends_on,
                                parameters=redact_sensitive(task.parameters),
                                execution_policy=_execution_policy(task),
                                status=TaskStatus.FAILED, attempts=0,
                                error=str(exc), duration_seconds=0,
                            )
                        await finish(task, outcome)
                    if cancellation_requested:
                        break
            except asyncio.CancelledError:
                if cancellation is not None:
                    cancellation.cancel("Execution task was cancelled by its caller.")
            finally:
                if cancellation_waiter is not None and not cancellation_waiter.done():
                    cancellation_waiter.cancel()
                    await asyncio.gather(cancellation_waiter, return_exceptions=True)

            if remaining:
                for future, task in tuple(running.items()):
                    future.cancel()
                await asyncio.gather(*running, return_exceptions=True)
                # Capture tasks that completed concurrently with cancellation
                # before recording the remaining nodes as cancelled.
                for future, task in tuple(running.items()):
                    if future.done() and not future.cancelled():
                        try:
                            outcome = future.result()
                        except BaseException:
                            outcome = None
                        if outcome is not None:
                            await finish(task, outcome)
                for task_id in sorted(remaining):
                    task = tasks_by_id[task_id]
                    await finish(
                        task,
                        TaskExecution(
                            task_id=task_id, handler=task.handler,
                            description=task.description, depends_on=task.depends_on,
                            parameters=redact_sensitive(task.parameters),
                            execution_policy=_execution_policy(task),
                            status=TaskStatus.CANCELLED, attempts=0,
                            error=(cancellation.reason if cancellation else "Execution cancelled."),
                            duration_seconds=0,
                        ),
                    )

            ordered_results = tuple(results[task.task_id] for task in plan.tasks)
            statuses = {result.status for result in ordered_results}
            if TaskStatus.CANCELLED in statuses:
                status = ExecutionStatus.CANCELLED
            elif TaskStatus.FAILED in statuses:
                status = ExecutionStatus.PARTIAL if any(
                    result.status == TaskStatus.SUCCEEDED for result in ordered_results
                ) else ExecutionStatus.FAILED
            else:
                status = ExecutionStatus.SUCCEEDED
            finished_at = datetime.now(timezone.utc)
            result = ExecutionResult(
                plan_id=plan.plan_id,
                status=status,
                tasks=ordered_results,
                metadata=redact_sensitive(plan.metadata),
                started_at=started_at,
                finished_at=finished_at,
                trace_id=trace_id,
            )
            log_event(
                "execution.finished",
                plan_id=plan.plan_id,
                mission_id=plan.mission_id,
                investigation_id=plan.investigation_id,
                status=status.value,
                duration_seconds=time.perf_counter() - started_clock,
                task_count=len(plan.tasks),
                failed_tasks=[
                    task.task_id
                    for task in ordered_results
                    if task.status == TaskStatus.FAILED
                ],
                warnings=list(result.warnings),
                resource_usage={
                    "process_cpu_seconds_delta": time.process_time() - process_cpu_started
                },
            )
            if self.journal:
                self.journal.record_event(plan.plan_id, "execution.finished", {
                    "trace_id": trace_id,
                    "status": status.value,
                    "finished_at": finished_at.isoformat(),
                })
            return result

    async def _run_task(
        self,
        task: Task,
        dependencies: Mapping[str, Any],
        plan: ExecutionPlan,
        trace_id: str,
        completed_count: int,
        semaphore: asyncio.Semaphore,
        resources: Mapping[str, Any],
        cancellation: ExecutionCancellationToken | None,
    ) -> TaskExecution:
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        process_cpu_started = time.process_time()
        context = TaskContext(
            task=task,
            dependencies=dependencies,
            resources=resources,
            mission_id=plan.mission_id,
            investigation_id=plan.investigation_id,
            trace_id=trace_id,
            cancellation=cancellation,
        )
        attempt = 0
        await self._report(
            task,
            TaskStatus.RUNNING,
            completed_count,
            len(plan.tasks),
            plan,
            trace_id,
        )
        try:
            handler = self.handlers.get(task.handler)
            async with semaphore:
                for attempt in range(1, task.max_attempts + 1):
                    try:
                        operation = self._invoke(handler, context)
                        output = (
                            await operation
                            if task.timeout_seconds is None
                            else await asyncio.wait_for(
                                operation, timeout=task.timeout_seconds
                            )
                        )
                    except asyncio.TimeoutError as exc:
                        error = OperationTimeoutError(
                            f"Task {task.task_id!r} exceeded "
                            f"{task.timeout_seconds:g} seconds.",
                            context={"task": task.task_id, "handler": task.handler},
                        )
                        if not task.retry_safe or attempt == task.max_attempts:
                            raise error from exc
                        await asyncio.sleep(task.retry_delay_seconds)
                    except SatQueryError as exc:
                        if (
                            not exc.recoverable
                            or not task.retry_safe
                            or attempt == task.max_attempts
                        ):
                            raise
                        await asyncio.sleep(task.retry_delay_seconds)
                    else:
                        duration = time.perf_counter() - started
                        outcome = TaskExecution(
                            task_id=task.task_id,
                            handler=task.handler,
                            description=task.description,
                            depends_on=task.depends_on,
                            parameters=redact_sensitive(task.parameters),
                            execution_policy=_execution_policy(task),
                            status=TaskStatus.SUCCEEDED,
                            attempts=attempt,
                            output=output,
                            started_at=started_at,
                            duration_seconds=duration,
                        )
                        log_event(
                            "task.succeeded",
                            plan_id=plan.plan_id,
                            mission_id=plan.mission_id,
                            investigation_id=plan.investigation_id,
                            task_id=task.task_id,
                            handler=task.handler,
                            connector=task.parameters.get("connector_id"),
                            tool=task.parameters.get("tool_id"),
                            model=task.parameters.get("model_id"),
                            duration_seconds=duration,
                            attempts=attempt,
                            parameters=redact_sensitive(task.parameters),
                            dataset_versions=task.parameters.get("dataset_versions", []),
                            warnings=list(getattr(output, "warnings", ())),
                            resource_usage={
                                "process_cpu_seconds_delta": time.process_time()
                                - process_cpu_started
                            },
                        )
                        return outcome
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            duration = time.perf_counter() - started
            log_event(
                "task.failed",
                level=logging.ERROR,
                plan_id=plan.plan_id,
                mission_id=plan.mission_id,
                investigation_id=plan.investigation_id,
                task_id=task.task_id,
                handler=task.handler,
                connector=task.parameters.get("connector_id"),
                tool=task.parameters.get("tool_id"),
                model=task.parameters.get("model_id"),
                duration_seconds=duration,
                attempts=attempt,
                error=str(exc),
                error_type=type(exc).__name__,
                parameters=redact_sensitive(task.parameters),
                dataset_versions=task.parameters.get("dataset_versions", []),
                warnings=[],
                resource_usage={
                    "process_cpu_seconds_delta": time.process_time() - process_cpu_started
                },
            )
            return TaskExecution(
                task_id=task.task_id,
                handler=task.handler,
                description=task.description,
                depends_on=task.depends_on,
                parameters=redact_sensitive(task.parameters),
                execution_policy=_execution_policy(task),
                status=TaskStatus.FAILED,
                attempts=attempt,
                error=str(exc),
                started_at=started_at,
                duration_seconds=duration,
            )
        raise AssertionError("Task retry loop exited without a result or error")

    @staticmethod
    async def _invoke(handler: TaskHandler, context: TaskContext) -> Any:
        if inspect.iscoroutinefunction(handler):
            return await handler(context)  # type: ignore[misc]
        result = await asyncio.to_thread(handler, context)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _report(
        self,
        task: Task,
        status: TaskStatus,
        completed: int,
        total: int,
        plan: ExecutionPlan,
        trace_id: str,
    ) -> None:
        if self.journal:
            self.journal.record_event(
                plan.plan_id,
                f"task.{status.value}",
                {
                    "task_id": task.task_id,
                    "trace_id": trace_id,
                    "completed_tasks": completed,
                    "total_tasks": total,
                },
            )
        if self.progress_callback is None:
            return
        event = ExecutionProgress(
            trace_id=trace_id,
            mission_id=plan.mission_id,
            investigation_id=plan.investigation_id,
            task_id=task.task_id,
            status=status,
            completed_tasks=completed,
            total_tasks=total,
        )
        try:
            callback_result = self.progress_callback(event)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            log_event(
                "execution.progress_callback_failed",
                level=logging.WARNING,
                plan_id=plan.plan_id,
                investigation_id=plan.investigation_id,
                task_id=task.task_id,
                handler=task.handler,
                error_type=type(exc).__name__,
            )
