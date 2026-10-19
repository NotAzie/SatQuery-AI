import asyncio

from satquery.errors import NetworkError
from satquery.platform.contracts import (
    ExecutionPlan,
    ExecutionStatus,
    Task,
    TaskStatus,
)
from satquery.platform.execution import (
    ExecutionCancellationToken,
    ExecutionEngine,
    TaskContext,
)
from satquery.platform.registry import ComponentRegistry
from satquery.platform.workflows import (
    WorkflowCompilationContext,
    WorkflowCompilerRegistry,
)


def test_execution_orders_dependencies_and_reports_progress():
    async def run():
        registry = ComponentRegistry()
        active = 0
        peak_active = 0
        progress = []

        async def branch(context: TaskContext):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return context.task.task_id

        def combine(context: TaskContext):
            return tuple(sorted(context.dependencies.values()))

        registry.register("branch", branch)
        registry.register("combine", combine)
        engine = ExecutionEngine(
            registry,
            max_concurrency=2,
            progress_callback=progress.append,
        )
        plan = ExecutionPlan(
            mission_id="mission-1",
            tasks=(
                Task(task_id="a", handler="branch"),
                Task(task_id="b", handler="branch"),
                Task(task_id="c", handler="combine", depends_on=("a", "b")),
            ),
        )

        result = await engine.execute(plan)
        assert result.status == ExecutionStatus.SUCCEEDED
        assert [item.status for item in result.tasks] == [TaskStatus.SUCCEEDED] * 3
        assert result.tasks[2].output == ("a", "b")
        assert peak_active == 2
        assert result.trace_id
        assert len(progress) == 6
        assert progress[-1].completed_tasks == 3
        running = [item for item in progress if item.status == TaskStatus.RUNNING]
        assert [item.completed_tasks for item in running] == [0, 0, 2]

    asyncio.run(run())


def test_failures_are_isolated_and_dependents_are_skipped():
    async def run():
        registry = ComponentRegistry()

        def fail(_context):
            raise ValueError("broken branch")

        registry.register("fail", fail)
        registry.register("ok", lambda _context: "independent")
        plan = ExecutionPlan(
            tasks=(
                Task(task_id="bad", handler="fail"),
                Task(task_id="independent", handler="ok"),
                Task(task_id="blocked", handler="ok", depends_on=("bad",)),
            )
        )
        result = await ExecutionEngine(registry, max_concurrency=2).execute(plan)

        assert result.status == ExecutionStatus.PARTIAL
        assert [task.status for task in result.tasks] == [
            TaskStatus.FAILED,
            TaskStatus.SUCCEEDED,
            TaskStatus.SKIPPED,
        ]

    asyncio.run(run())


def test_partial_evidence_stage_receives_only_successful_dependency_outputs():
    async def run():
        registry = ComponentRegistry()

        def fail(_context):
            raise ValueError("unavailable source")

        registry.register("fail", fail)
        registry.register("observe", lambda context: context.task.task_id)
        registry.register("assess", lambda context: tuple(sorted(context.dependencies)))
        plan = ExecutionPlan(
            tasks=(
                Task(task_id="source-a", handler="fail"),
                Task(task_id="source-b", handler="observe"),
                Task(
                    task_id="assessment",
                    handler="assess",
                    depends_on=("source-a", "source-b"),
                    accept_partial_dependencies=True,
                ),
            )
        )
        result = await ExecutionEngine(registry).execute(plan)

        assert result.status == ExecutionStatus.PARTIAL
        assert result.tasks[-1].status == TaskStatus.SUCCEEDED
        assert result.tasks[-1].output == ("source-b",)
        assert result.tasks[-1].handler == "assess"
        assert result.tasks[-1].depends_on == ("source-a", "source-b")

    asyncio.run(run())


def test_scheduler_releases_completed_branch_without_waiting_for_peer_branch():
    async def run():
        registry = ComponentRegistry()
        order = []

        async def slow(_context):
            await asyncio.sleep(0.06)
            order.append("slow")
            return "slow"

        def fast(_context):
            order.append("fast")
            return "fast"

        def downstream(_context):
            order.append("downstream")
            return "ready"

        registry.register("slow", slow)
        registry.register("fast", fast)
        registry.register("downstream", downstream)
        result = await ExecutionEngine(registry, max_concurrency=2).execute(
            ExecutionPlan(tasks=(
                Task(task_id="slow", handler="slow"),
                Task(task_id="fast", handler="fast"),
                Task(task_id="fast-next", handler="downstream", depends_on=("fast",)),
            ))
        )

        assert result.status == ExecutionStatus.SUCCEEDED
        assert order.index("downstream") < order.index("slow")

    asyncio.run(run())


def test_cancellation_token_cancels_running_and_unstarted_tasks():
    async def run():
        registry = ComponentRegistry()
        started = asyncio.Event()

        async def wait_until_cancelled(_context):
            started.set()
            await asyncio.Event().wait()

        registry.register("wait", wait_until_cancelled)
        token = ExecutionCancellationToken()
        engine = ExecutionEngine(registry, max_concurrency=1)
        execution = asyncio.create_task(engine.execute(
            ExecutionPlan(tasks=(
                Task(task_id="active", handler="wait"),
                Task(task_id="queued", handler="wait"),
            )),
            cancellation=token,
        ))
        await started.wait()
        token.cancel("operator requested stop")
        result = await execution

        assert result.status == ExecutionStatus.CANCELLED
        assert [item.status for item in result.tasks] == [
            TaskStatus.CANCELLED, TaskStatus.CANCELLED
        ]

    asyncio.run(run())


def test_runtime_cancellation_transitions_running_investigation_to_cancelled():
    from satquery.platform.config import PlatformConfig
    from satquery.platform.contracts import Mission
    from satquery.platform.runtime import PlatformRuntime

    async def run():
        runtime = PlatformRuntime(config=PlatformConfig.load(overrides={"profile": "testing"}))
        mission = Mission(name="Cancellation", objective="Test execution cancellation")
        runtime.mission_service.create(mission)
        started = asyncio.Event()

        async def block(_context):
            started.set()
            await asyncio.Event().wait()

        runtime.register_task_handler("fixture.block", block)
        investigation = runtime.mission_service.create_investigation(
            mission.mission_id,
            (Task(task_id="block", handler="fixture.block"),),
        )
        executing = asyncio.create_task(
            runtime.execute_investigation(investigation.investigation_id)
        )
        await started.wait()
        request = runtime.cancel_investigation(investigation.investigation_id)
        result = await executing

        assert request["status"] == "cancellation_requested"
        assert result.status == ExecutionStatus.CANCELLED
        assert runtime.investigation_service.get(
            investigation.investigation_id
        ).status.value == "cancelled"

    asyncio.run(run())


def test_resume_without_a_prior_execution_does_not_change_pending_lifecycle():
    from satquery.errors import ValidationError
    from satquery.platform.config import PlatformConfig
    from satquery.platform.contracts import Mission
    from satquery.platform.runtime import PlatformRuntime

    async def run():
        runtime = PlatformRuntime(config=PlatformConfig.load(
            overrides={"profile": "testing"}
        ))
        mission = Mission(name="No checkpoint", objective="Reject invalid resumption")
        runtime.mission_service.create(mission)
        investigation = runtime.mission_service.create_investigation(
            mission.mission_id,
            (Task(task_id="observe", handler="fixture.observe"),),
        )
        try:
            await runtime.execute_investigation(investigation.investigation_id, resume=True)
        except ValidationError as exc:
            assert "No durable execution" in str(exc)
        else:
            raise AssertionError("resume must require a prior journal record")
        assert runtime.investigation_service.get(
            investigation.investigation_id
        ).status.value == "pending"

    asyncio.run(run())


def test_workflow_compiler_registry_requires_an_explicit_registered_version():
    from satquery.errors import ExtensionError
    from satquery.platform.contracts import Investigation

    class FixtureCompiler:
        workflow_id = "fixture.workflow"
        version = "2.1.0"

        def compile(self, context):
            return ExecutionPlan(
                mission_id=context.investigation.mission_id,
                investigation_id=context.investigation.investigation_id,
                tasks=(Task(task_id="fixture", handler="fixture.handler"),),
            )

    investigation = Investigation(mission_id="mission-fixture")
    registry = WorkflowCompilerRegistry()
    compiler = FixtureCompiler()
    registry.register(compiler)

    plan = registry.compile(
        compiler.workflow_id,
        compiler.version,
        WorkflowCompilationContext(investigation=investigation),
    )
    assert plan.investigation_id == investigation.investigation_id
    assert registry.versions() == (("fixture.workflow", "2.1.0"),)
    try:
        registry.compile(compiler.workflow_id, "2.0.0", WorkflowCompilationContext(
            investigation=investigation
        ))
    except ExtensionError:
        pass
    else:
        raise AssertionError("an unregistered workflow version must not compile")


def test_progress_observer_failure_does_not_fail_scientific_task():
    async def run():
        registry = ComponentRegistry()
        registry.register("observe", lambda _context: "completed")

        def broken_observer(_event):
            raise RuntimeError("observer unavailable")

        result = await ExecutionEngine(
            registry, progress_callback=broken_observer
        ).execute(ExecutionPlan(tasks=(Task(task_id="task", handler="observe"),)))

        assert result.status == ExecutionStatus.SUCCEEDED
        assert result.tasks[0].output == "completed"

    asyncio.run(run())


def test_recoverable_failures_retry_only_when_task_is_retry_safe():
    async def run():
        registry = ComponentRegistry()
        attempts = 0

        def transient(_context):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise NetworkError("temporary")
            return "recovered"

        registry.register("transient", transient)
        plan = ExecutionPlan(
            tasks=(
                Task(
                    task_id="retry",
                    handler="transient",
                    max_attempts=2,
                    retry_safe=True,
                ),
            )
        )
        result = await ExecutionEngine(registry).execute(plan)

        assert result.status == ExecutionStatus.SUCCEEDED
        assert result.tasks[0].attempts == 2
        assert result.tasks[0].output == "recovered"

    asyncio.run(run())


def test_async_task_timeout_is_reported_as_failure():
    async def run():
        registry = ComponentRegistry()

        async def slow(_context):
            await asyncio.sleep(1)

        registry.register("slow", slow)
        result = await ExecutionEngine(registry).execute(
            ExecutionPlan(
                tasks=(
                    Task(
                        task_id="slow",
                        handler="slow",
                        timeout_seconds=0.01,
                    ),
                )
            )
        )

        assert result.status == ExecutionStatus.FAILED
        assert "exceeded" in result.tasks[0].error

    asyncio.run(run())
