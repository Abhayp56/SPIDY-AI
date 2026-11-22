"""
Unit tests for SPIDY-AI core.undo module.
Verifies thread-safe undo stack operations, depth limits, label truncation,
exception handling, and concurrency (uniqueness and integrity).
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


def test_concurrent_pushes_within_capacity_uniqueness():
    """Verify concurrent pushes preserve all unique items without corruption or duplicate entries."""
    num_threads = 10
    expected_labels = {f"thread_action_{i}" for i in range(num_threads)}
    barrier = threading.Barrier(num_threads)

    def worker(worker_id: int):
        barrier.wait()
        undo.push_undo(f"thread_action_{worker_id}", lambda: f"reverted_{worker_id}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    hist = undo.history()
    assert len(hist) == num_threads
    # Strict uniqueness: exactly 10 distinct labels, no dropped or duplicated elements
    assert len(set(hist)) == num_threads
    assert set(hist) == expected_labels
    assert undo.can_undo() is True


def test_concurrent_undo_execution():
    """Verify concurrent undo_last invocations pop and execute each entry exactly once."""
    num_items = 10
    executed_callbacks = []
    cb_lock = threading.Lock()

    def make_cb(val: int):
        def _cb() -> str:
            with cb_lock:
                executed_callbacks.append(val)
            return f"undone_{val}"
        return _cb

    for i in range(num_items):
        undo.push_undo(f"action_{i}", make_cb(i))

    results = []
    res_lock = threading.Lock()
    barrier = threading.Barrier(num_items)

    def worker():
        barrier.wait()
        res = undo.undo_last()
        with res_lock:
            results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(num_items)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == num_items
    assert all("Undone: action_" in r for r in results)
    assert len(executed_callbacks) == num_items
    assert set(executed_callbacks) == set(range(num_items))
    assert undo.can_undo() is False
    assert undo.history() == []


def test_concurrent_pushes_exceeding_capacity_integrity():
    """Verify that under high-concurrency over-capacity load, stack maintains MAX_DEPTH and uniqueness."""
    num_threads = 8
    pushes_per_thread = 5
    all_pushed = set()
    pushed_lock = threading.Lock()
    barrier = threading.Barrier(num_threads)

    def worker(worker_id: int):
        barrier.wait()
        for j in range(pushes_per_thread):
            label = f"worker_{worker_id}_task_{j}"
            with pushed_lock:
                all_pushed.add(label)
            undo.push_undo(label, lambda: "ok")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    hist = undo.history()
    # Stack must never exceed MAX_DEPTH
    assert len(hist) == undo.MAX_DEPTH
    # Every surviving entry must be unique and from the pushed set
    assert len(set(hist)) == undo.MAX_DEPTH
    assert set(hist).issubset(all_pushed)
