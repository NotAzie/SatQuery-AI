import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from satquery.errors import ExecutionError, ValidationError
from satquery.platform.config import PlatformConfig
from satquery.platform.contracts import (
    ExecutionPlan,
    ExecutionStatus,
    Mission,
    ObservationSearchResult,
    PerceptionResult,
    Task,
    TaskExecution,
    TaskStatus,
)
from satquery.platform.execution import ExecutionEngine
from satquery.platform.execution_journal import (
    PydanticTaskOutputCodec,
    SQLiteExecutionJournal,
    TaskOutputCodecRegistry,
)
from satquery.platform.registry import ComponentRegistry
from satquery.platform.runtime import PlatformRuntime


@pytest.fixture
def execution_database():
    database = Path(__file__).parents[1] / f".execution-test-{uuid4().hex}.sqlite"
    try:
        yield database
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{database}{suffix}").unlink(missing_ok=True)


def test_sqlite_journal_resumes_successful_tasks_after_engine_recreation(execution_database):
    database = execution_database
    plan = ExecutionPlan(
        plan_id="stable-execution",
        tasks=(
            Task(task_id="acquire", handler="acquire"),
            Task(
                task_id="assess", handler="assess", depends_on=("acquire",),
                retry_safe=True,
            ),
        ),
    )
    acquisition_runs = 0
    assessment_runs = 0

    def acquire(_context):
        nonlocal acquisition_runs
        acquisition_runs += 1
        return {"observation_ids": ["observation-1"]}

    def assess(context):
        nonlocal assessment_runs
        assessment_runs += 1
        if assessment_runs == 1:
            raise ValueError("temporary evaluation failure")
        return {"assessed": context.dependencies["acquire"]}

    first_handlers = ComponentRegistry()
    first_handlers.register("acquire", acquire)
    first_handlers.register("assess", assess)
    first = asyncio.run(ExecutionEngine(
        first_handlers, journal=SQLiteExecutionJournal(database)
    ).execute(plan))
    assert first.status == ExecutionStatus.PARTIAL
    assert acquisition_runs == 1

    second_handlers = ComponentRegistry()
    second_handlers.register("acquire", acquire)
    second_handlers.register("assess", assess)
    journal_after_restart = SQLiteExecutionJournal(database)
    resumed = asyncio.run(ExecutionEngine(
        second_handlers, journal=journal_after_restart
    ).execute(plan, resume=True))

    assert resumed.status == ExecutionStatus.SUCCEEDED
    assert acquisition_runs == 1
    assert assessment_runs == 2
    assert resumed.tasks[0].output == {"observation_ids": ["observation-1"]}
    assert resumed.tasks[1].output == {
        "assessed": {"observation_ids": ["observation-1"]}
    }
    events = journal_after_restart.events(plan.plan_id)
    assert [item["sequence"] for item in events] == sorted(
        item["sequence"] for item in events
    )
    assert any(item["event_type"] == "execution.resumed" for item in events)
    assert any(item["event_type"] == "task.checkpointed" for item in events)
    assert events[0]["previous_event_sha256"] == "0" * 64
    assert all(item["event_sha256"] for item in events)


def test_resume_refuses_to_replay_uncertain_non_retry_safe_side_effect(execution_database):
    database = execution_database
    plan = ExecutionPlan(
        plan_id="unsafe-execution",
        tasks=(Task(task_id="acquire", handler="acquire"),),
    )
    handlers = ComponentRegistry()

    def failed_acquisition(_context):
        raise ValueError("the remote request may have had a side effect")

    handlers.register("acquire", failed_acquisition)
    journal = SQLiteExecutionJournal(database)
    result = asyncio.run(ExecutionEngine(handlers, journal=journal).execute(plan))
    assert result.status == ExecutionStatus.FAILED

    with pytest.raises(ExecutionError, match="not declared retry-safe"):
        asyncio.run(ExecutionEngine(handlers, journal=SQLiteExecutionJournal(database)).execute(
            plan, resume=True
        ))


def test_journal_rejects_reuse_of_plan_id_for_changed_plan(execution_database):
    journal = SQLiteExecutionJournal(execution_database)
    original = ExecutionPlan(
        plan_id="same-id", tasks=(Task(task_id="a", handler="first"),)
    )
    changed = ExecutionPlan(
        plan_id="same-id", tasks=(Task(task_id="a", handler="changed"),)
    )
    journal.begin(original, resume=False)
    with pytest.raises(ValidationError, match="different content"):
        journal.begin(changed, resume=True)


def test_output_codecs_require_exact_versioned_contracts():
    from satquery.platform.contracts import ObservationSearchResult

    codecs = TaskOutputCodecRegistry()
    codecs.register(PydanticTaskOutputCodec(
        "satquery.observation-search-result", "1.0.0", ObservationSearchResult
    ))
    encoded = ObservationSearchResult(observations=())
    codec_id, version, payload = codecs.encode(encoded)
    restored = codecs.decode(codec_id, version, payload)
    assert restored == encoded
    codecs.register(PydanticTaskOutputCodec(
        "satquery.observation-search-result", "0.9.0", ObservationSearchResult
    ), for_encoding=False)
    assert codecs.decode("satquery.observation-search-result", "0.9.0", payload) == encoded
    with pytest.raises(ValidationError, match="unavailable"):
        codecs.decode(codec_id, "2.0.0", payload)
    with pytest.raises(TypeError, match="No execution output codec"):
        codecs.encode(("order-sensitive", "tuple"))


def test_perception_result_output_codec_version_tracks_temporal_diagnostics():
    codecs = TaskOutputCodecRegistry.platform_defaults()

    codec_id, version, payload = codecs.encode(PerceptionResult(
        query_fingerprint="query-version-test",
        temporal_differences=(),
    ))

    assert codec_id == "satquery.perception-result"
    assert version == "2.0.0"
    assert PerceptionResult.model_validate(payload).query_fingerprint == "query-version-test"


def test_platform_investigation_resumes_from_durable_lifecycle_and_checkpoints(
    execution_database,
):
    config = PlatformConfig.load(overrides={
        "profile": "testing",
        "storage": {"earth_memory_path": str(execution_database)},
    })
    acquisition_runs = 0
    evaluation_runs = 0

    def acquire(_context):
        nonlocal acquisition_runs
        acquisition_runs += 1
        return {"observation": "retained-acquisition"}

    def evaluate(context):
        nonlocal evaluation_runs
        evaluation_runs += 1
        if evaluation_runs == 1:
            raise ValueError("restart after transient evaluation failure")
        return {"used": context.dependencies["acquire"]}

    async def run():
        first_runtime = PlatformRuntime(config=config)
        first_runtime.register_task_handler("fixture.acquire", acquire)
        first_runtime.register_task_handler("fixture.evaluate", evaluate)
        mission = Mission(name="Durable resume", objective="Resume a scientific workflow")
        first_runtime.mission_service.create(mission)
        investigation = first_runtime.mission_service.create_investigation(
            mission.mission_id,
            (
                Task(task_id="acquire", handler="fixture.acquire"),
                Task(
                    task_id="evaluate", handler="fixture.evaluate",
                    depends_on=("acquire",), retry_safe=True,
                ),
            ),
        )
        partial = await first_runtime.execute_investigation(investigation.investigation_id)
        assert partial.status == ExecutionStatus.PARTIAL
        await first_runtime.close()

        restarted_runtime = PlatformRuntime(config=config)
        restarted_runtime.register_task_handler("fixture.acquire", acquire)
        restarted_runtime.register_task_handler("fixture.evaluate", evaluate)
        assert restarted_runtime.investigation_service.get(
            investigation.investigation_id
        ).status.value == "partial"
        complete = await restarted_runtime.execute_investigation(
            investigation.investigation_id, resume=True
        )
        assert complete.status == ExecutionStatus.SUCCEEDED
        assert acquisition_runs == 1
        assert evaluation_runs == 2
        assert restarted_runtime.execution_events(complete.plan_id)[-1]["event_type"] == (
            "execution.finished"
        )
        await restarted_runtime.close()

    asyncio.run(run())


def test_typed_output_checkpoint_is_rehydrated_without_type_guessing(execution_database):
    plan = ExecutionPlan(
        plan_id="typed-output", tasks=(Task(task_id="search", handler="search"),)
    )
    journal = SQLiteExecutionJournal(execution_database)
    journal.begin(plan, resume=False)
    output = ObservationSearchResult(observations=(), matched=0)
    journal.checkpoint(plan, TaskExecution(
        task_id="search", handler="search", status=TaskStatus.SUCCEEDED,
        attempts=1, output=output, duration_seconds=0.0,
    ))

    reopened = SQLiteExecutionJournal(execution_database)
    restored = reopened.checkpoints(plan.plan_id)["search"].output
    assert isinstance(restored, ObservationSearchResult)
    assert restored == output
