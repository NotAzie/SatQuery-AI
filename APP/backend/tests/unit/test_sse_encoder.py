import json

from earth_platform.agent.events import RunCompleted
from earth_platform.streaming.sse import SSEEventEncoder


def test_sse_encoder_uses_event_sequence_as_reconnect_cursor():
    event = RunCompleted(
        session_id="session-1",
        conversation_id="conversation-1",
        run_id="run-1",
        seq=12,
    )
    frame = SSEEventEncoder().encode(event).decode("utf-8")
    lines = frame.splitlines()
    assert lines[0] == "id: 12"
    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload["type"] == "run.completed"
    assert payload["seq"] == 12


def test_sse_encoder_heartbeat_is_a_comment_frame():
    assert SSEEventEncoder().heartbeat() == b": keep-alive\n\n"
