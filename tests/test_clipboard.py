"""
tests/test_clipboard.py
Unit tests for core.clipboard_engine: semantic classification, smart history,
JSON formatting, AI repair helpers, and thread safety.
"""

from __future__ import annotations

import collections
import concurrent.futures
import json
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from core.clipboard_engine import (
    ClipboardEngine,
    ClipboardItem,
    get_clipboard_engine,
)


@pytest.fixture
def standalone_engine():
    """Provides a fresh ClipboardEngine instance with background monitoring stopped."""
    with patch("pyperclip.paste", return_value=""):
        engine = ClipboardEngine(max_history=5)
        engine.stop_monitoring()
    yield engine
    engine.stop_monitoring()


# ---------------------------------------------------------------------------
# ClipboardItem dataclass tests
# ---------------------------------------------------------------------------

def test_clipboard_item_init_and_properties():
    content = "Hello, world!\nSecond line"
    item = ClipboardItem(content=content, category="text")

    assert item.char_count == len(content)
    assert item.lines_count == 2
    assert item.preview == "Hello, world!"
    assert item.category == "text"


def test_clipboard_item_preview_truncation():
    long_line = "A" * 80
    item = ClipboardItem(content=long_line, category="text")

    assert len(item.preview) == 63  # 60 chars + "..."
    assert item.preview.endswith("...")
    assert item.preview.startswith("A" * 60)


def test_clipboard_item_empty_content():
    item = ClipboardItem(content="", category="empty")

    assert item.char_count == 0
    assert item.lines_count == 0
    assert item.preview == ""


def test_clipboard_item_to_dict():
    content = "Sample content for dictionary conversion."
    item = ClipboardItem(content=content, category="text")
    d = item.to_dict()

    assert d["category"] == "text"
    assert d["preview"] == content
    assert d["char_count"] == len(content)
    assert d["lines_count"] == 1
    assert "timestamp" in d
    assert d["content"] == content


def test_clipboard_item_to_dict_long_content_truncated():
    long_content = "X" * 400
    item = ClipboardItem(content=long_content, category="text")
    d = item.to_dict()

    assert len(d["content"]) == 303  # 300 chars + "..."
    assert d["content"].endswith("...")


# ---------------------------------------------------------------------------
# Semantic Content Classification tests
# ---------------------------------------------------------------------------

def test_classify_content_empty_and_whitespace():
    assert ClipboardEngine.classify_content("") == "empty"
    assert ClipboardEngine.classify_content("   \t\n\r  ") == "empty"


def test_classify_content_urls():
    assert ClipboardEngine.classify_content("https://github.com/Abhayp56/SPIDY-AI") == "url"
    assert ClipboardEngine.classify_content("http://localhost:8000/api/v1/health") == "url"
    assert ClipboardEngine.classify_content("https://example.com/search?q=openmausbot#top") == "url"


def test_classify_content_stack_traces_and_errors():
    traceback_sample = (
        "Traceback (most recent call last):\n"
        "  File \"main.py\", line 120, in <module>\n"
        "    app.run()\n"
        "ValueError: invalid port"
    )
    assert ClipboardEngine.classify_content(traceback_sample) == "stack_trace"

    error_line = "Exception: Connection timed out after 3000ms"
    assert ClipboardEngine.classify_content(error_line) == "stack_trace"

    file_line = 'File "core/undo.py", line 45, in undo_last'
    assert ClipboardEngine.classify_content(file_line) == "stack_trace"

    err_prefix = "ERR!: failed to compile typescript bundle"
    assert ClipboardEngine.classify_content(err_prefix) == "stack_trace"


def test_classify_content_json():
    valid_obj = '{"status": "ok", "code": 200, "data": [1, 2, 3]}'
    assert ClipboardEngine.classify_content(valid_obj) == "json"

    valid_arr = '[{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]'
    assert ClipboardEngine.classify_content(valid_arr) == "json"

    # Malformed brackets should not classify as json
    invalid_json = '{"key": incomplete json'
    assert ClipboardEngine.classify_content(invalid_json) != "json"


def test_classify_content_file_paths():
    win_path = r"C:\Users\Asus\Projects\SPIDY-AI\core\undo.py"
    assert ClipboardEngine.classify_content(win_path) == "file_path"

    unix_path = "/usr/local/bin/spidy_daemon"
    assert ClipboardEngine.classify_content(unix_path) == "file_path"


def test_classify_content_commands():
    assert ClipboardEngine.classify_content("git commit -m 'feat: initial test suite'") == "command"
    assert ClipboardEngine.classify_content("docker run -d --name spidy -p 8000:8000 app") == "command"
    assert ClipboardEngine.classify_content("npm run build --clean") == "command"
    assert ClipboardEngine.classify_content("pip install -r requirements-dev.txt") == "command"
    assert ClipboardEngine.classify_content("cargo build --release") == "command"
    assert ClipboardEngine.classify_content("python -m pytest -v") == "command"


def test_classify_content_code():
    py_func = (
        "def compute_metrics(records):\n"
        "    return sum(r.score for r in records)"
    )
    assert ClipboardEngine.classify_content(py_func) == "code"

    py_class = "class AutonomousContributionEngine:\n    pass"
    assert ClipboardEngine.classify_content(py_class) == "code"

    py_import = "from core.undo import undo_last"
    assert ClipboardEngine.classify_content(py_import) == "code"

    js_code = "const handleClick = () => console.log('event');"
    assert ClipboardEngine.classify_content(js_code) == "code"


def test_classify_content_plain_text():
    text = "The system will automatically run the contribution routine at 8:30 PM."
    assert ClipboardEngine.classify_content(text) == "text"


# ---------------------------------------------------------------------------
# ClipboardEngine state, history bounds & eviction tests
# ---------------------------------------------------------------------------

def test_engine_history_bounds_and_fifo_eviction(standalone_engine):
    for i in range(10):
        item = ClipboardItem(content=f"Item {i}", category="text")
        standalone_engine._history.appendleft(item)

    assert len(standalone_engine._history) == 5
    assert standalone_engine._history[0].content == "Item 9"
    assert standalone_engine._history[-1].content == "Item 5"


def test_engine_get_history_limit(standalone_engine):
    for i in range(5):
        standalone_engine._history.appendleft(
            ClipboardItem(content=f"Record {i}", category="text")
        )

    with patch.object(standalone_engine, "_poll_clipboard", return_value=None):
        history_limited = standalone_engine.get_history(limit=2)
        assert len(history_limited) == 2
        assert history_limited[0]["content"] == "Record 4"

        history_all = standalone_engine.get_history(limit=10)
        assert len(history_all) == 5


def test_engine_deduplication_on_poll(standalone_engine):
    with patch("pyperclip.paste", return_value="identical string"):
        with patch("core.clipboard_engine._HAS_PYPERCLIP", True):
            item1 = standalone_engine._poll_clipboard()
            assert item1 is not None
            assert len(standalone_engine._history) == 1

            item2 = standalone_engine._poll_clipboard()
            assert item2 is None
            assert len(standalone_engine._history) == 1


# ---------------------------------------------------------------------------
# JSON Formatting & AI operations tests
# ---------------------------------------------------------------------------

def test_format_json_success(standalone_engine):
    raw_json = '{"a": 1, "b": [2, 3]}'
    item = ClipboardItem(content=raw_json, category="json")
    standalone_engine._history.appendleft(item)

    with patch.object(standalone_engine, "get_current", return_value=item):
        with patch.object(standalone_engine, "set_content", return_value=True) as mock_set:
            success, msg = standalone_engine.format_json()

            assert success is True
            assert "Prettified JSON" in msg
            mock_set.assert_called_once()
            called_arg = mock_set.call_args[0][0]
            expected = json.dumps(json.loads(raw_json), indent=2)
            assert called_arg == expected


def test_format_json_empty_clipboard(standalone_engine):
    with patch.object(standalone_engine, "get_current", return_value=None):
        success, msg = standalone_engine.format_json()
        assert success is False
        assert msg == "Clipboard is empty."


def test_format_json_invalid_json(standalone_engine):
    invalid_item = ClipboardItem(content="{invalid: json content", category="text")
    with patch.object(standalone_engine, "get_current", return_value=invalid_item):
        success, msg = standalone_engine.format_json()
        assert success is False
        assert "not valid JSON" in msg


def test_explain_content_empty_clipboard(standalone_engine):
    with patch.object(standalone_engine, "get_current", return_value=None):
        explanation = standalone_engine.explain_content()
        assert explanation == "The clipboard is currently empty."


def test_fix_code_or_error_empty_clipboard(standalone_engine):
    with patch.object(standalone_engine, "get_current", return_value=None):
        success, msg = standalone_engine.fix_code_or_error()
        assert success is False
        assert "Clipboard is empty" in msg


def test_fix_code_or_error_with_ai_response(standalone_engine):
    broken_code = "def faulty(\n    return 42"
    item = ClipboardItem(content=broken_code, category="code")

    ai_reply = (
        "DIAGNOSIS: Missing closing parenthesis in function definition.\n"
        "FIX:\n"
        "```python\n"
        "def faulty():\n"
        "    return 42\n"
        "```"
    )

    with patch.object(standalone_engine, "get_current", return_value=item):
        with patch("core.gemini.text", return_value=ai_reply):
            with patch.object(standalone_engine, "set_content", return_value=True) as mock_set:
                success, msg = standalone_engine.fix_code_or_error()

                assert success is True
                assert "Fixed code copied to clipboard!" in msg
                mock_set.assert_called_once_with("def faulty():\n    return 42")


def test_fix_code_or_error_ai_empty_response(standalone_engine):
    broken_code = "def faulty(): pass"
    item = ClipboardItem(content=broken_code, category="code")

    with patch.object(standalone_engine, "get_current", return_value=item):
        with patch("core.gemini.text", return_value=""):
            success, msg = standalone_engine.fix_code_or_error()
            assert success is False
            assert "Unable to generate fix" in msg


# ---------------------------------------------------------------------------
# Concurrency & Singleton tests
# ---------------------------------------------------------------------------

def test_concurrent_history_access(standalone_engine):
    num_threads = 8
    iterations_per_thread = 50

    with patch.object(standalone_engine, "_poll_clipboard", return_value=None):
        def worker(worker_id):
            for i in range(iterations_per_thread):
                item = ClipboardItem(
                    content=f"Worker-{worker_id}-Item-{i}",
                    category="text"
                )
                with standalone_engine._lock:
                    standalone_engine._history.appendleft(item)
                _ = standalone_engine.get_history(limit=3)

        threads = [
            threading.Thread(target=worker, args=(tid,))
            for tid in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not any(t.is_alive() for t in threads)
        assert len(standalone_engine._history) == standalone_engine._history.maxlen


def test_get_clipboard_engine_singleton():
    with patch("pyperclip.paste", return_value=""):
        inst1 = get_clipboard_engine()
        inst2 = get_clipboard_engine()
        assert inst1 is inst2
        inst1.stop_monitoring()
