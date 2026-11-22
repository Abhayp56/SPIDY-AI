"""
Unit tests for SPIDY-AI core.undo module.
Verifies thread-safe undo stack operations, depth limits, label truncation,
exception handling, and concurrency.
"""
from __future__ import annotations

import threading
import pytest
from core import undo


@pytest.fixture(autouse=True)
def reset_undo_stack():
    """Ensure every test begins and ends with an empty undo stack."""
    undo.clear()
    yield
    undo.clear()


def test_initial_state_empty():
    assert undo.can_undo() is False
    assert undo.peek() == ""
    assert undo.history() == []
    result = undo.undo_last()
    assert "There is nothing to undo" in result


def test_push_and_peek():
    undo.push_undo("volume -> 50%", lambda: "reverted volume")
    assert undo.can_undo() is True
    assert undo.peek() == "volume -> 50%"
    assert undo.history() == ["volume -> 50%"]


def test_push_invalid_callable_ignored():
    undo.push_undo("invalid_none", None)  # type: ignore
    undo.push_undo("invalid_string", "not-a-callable")  # type: ignore
    assert undo.can_undo() is False
    assert undo.history() == []


def test_label_truncation():
    long_label = "a" * 200
    undo.push_undo(long_label, lambda: "ok")
    assert len(undo.peek()) == 120
    assert undo.peek() == "a" * 120


def test_undo_last_with_detail():
    called = []

    def mock_undo() -> str:
        called.append(True)
        return "file moved back"

    undo.push_undo("move file", mock_undo)
    result = undo.undo_last()

    assert called == [True]
    assert result == "Undone: move file. file moved back"
    assert undo.can_undo() is False


def test_undo_last_without_detail():
    undo.push_undo("mute microphone", lambda: "")
    result = undo.undo_last()
    assert result == "Undone: mute microphone."
    assert undo.can_undo() is False


def test_undo_last_exception_handling():
    def failing_callback() -> str:
        raise RuntimeError("device disconnected")

    undo.push_undo("disconnect bluetooth", failing_callback)
    result = undo.undo_last()

    assert "Could not undo 'disconnect bluetooth': device disconnected" in result
    assert undo.can_undo() is False


def test_max_depth_eviction():
    for i in range(15):
        undo.push_undo(f"step_{i}", lambda: "ok")

    hist = undo.history()
    assert len(hist) == undo.MAX_DEPTH
    assert hist[0] == "step_14"
    assert hist[-1] == "step_5"


def test_clear_stack():
    undo.push_undo("action 1", lambda: "ok")
    undo.push_undo("action 2", lambda: "ok")
    assert undo.can_undo() is True

    undo.clear()
    assert undo.can_undo() is False
    assert undo.history() == []


def test_concurrent_pushes_thread_safety():
    num_threads = 5
    pushes_per_thread = 10

    def worker(worker_id: int):
        for j in range(pushes_per_thread):
            undo.push_undo(f"worker_{worker_id}_task_{j}", lambda: "ok")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # The stack should never exceed MAX_DEPTH and internal structure must remain valid
    assert undo.can_undo() is True
    assert len(undo.history()) == undo.MAX_DEPTH
