"""
Unit tests for SPIDY-AI core.action_loader module.
Verifies action discovery, validation, signature introspection, error resilience,
collision detection, declaration generation, and thread-safe execution.
"""
from __future__ import annotations

import concurrent.futures
import types
from pathlib import Path
import pytest

from core import action_loader
from core.action_loader import (
    ActionRecord,
    ActionRegistry,
    _call_handler,
    _opt_upper,
    _validate,
    discover_actions,
    get_action_registry,
)


def test_opt_upper_valid_and_invalid():
    allowed = ("BLOCKING", "NON_BLOCKING")
    assert _opt_upper("blocking", allowed) == "BLOCKING"
    assert _opt_upper("  non_blocking  ", allowed) == "NON_BLOCKING"
    assert _opt_upper("BLOCKING", allowed) == "BLOCKING"
    assert _opt_upper("INVALID", allowed) is None
    assert _opt_upper("", allowed) is None
    assert _opt_upper(None, allowed) is None


def test_action_record_defaults():
    rec = ActionRecord(name="sample_action")
    assert rec.name == "sample_action"
    assert rec.description == ""
    assert rec.parameters == {"type": "OBJECT", "properties": {}}
    assert rec.handler is None
    assert rec.file == ""
    assert rec.valid is False
    assert rec.error == ""
    assert rec.behavior is None
    assert rec.scheduling is None


def test_validate_no_tool_dict():
    mod = types.ModuleType("empty_module")
    rec = _validate(mod, "empty_action.py")
    assert rec.valid is False
    assert "No module-level TOOL dict" in rec.error
    assert rec.name == "empty_action"


def test_validate_invalid_tool_names():
    # Missing or non-string name
    mod1 = types.ModuleType("mod1")
    mod1.TOOL = {"description": "desc", "handler": lambda: None}  # type: ignore
    rec1 = _validate(mod1, "mod1.py")
    assert rec1.valid is False
    assert "TOOL['name'] missing" in rec1.error

    # Invalid characters in name
    invalid_names = ["tool-name", "123start_num", "tool name", "tool@name", "a" * 65]
    for bad_name in invalid_names:
        mod = types.ModuleType("bad_mod")
        mod.TOOL = {"name": bad_name, "description": "desc", "handler": lambda: None}  # type: ignore
        rec = _validate(mod, "bad_mod.py")
        assert rec.valid is False, f"Expected {bad_name} to be invalid"
        assert "TOOL['name'] missing or not a valid identifier" in rec.error


def test_validate_description_requirements():
    # Missing description
    mod = types.ModuleType("mod")
    mod.TOOL = {"name": "valid_name", "handler": lambda: None}  # type: ignore
    rec = _validate(mod, "mod.py")
    assert rec.valid is False
    assert "TOOL['description'] missing or empty" in rec.error

    # Whitespace-only description
    mod.TOOL["description"] = "   \n  "
    rec = _validate(mod, "mod.py")
    assert rec.valid is False
    assert "TOOL['description'] missing or empty" in rec.error


def test_validate_parameters_requirements():
    mod = types.ModuleType("mod")
    # Parameters not a dict
    mod.TOOL = {  # type: ignore
        "name": "valid_name",
        "description": "Valid description",
        "parameters": "not-a-dict",
        "handler": lambda: None,
    }
    rec = _validate(mod, "mod.py")
    assert rec.valid is False
    assert "TOOL['parameters'] must be a dict" in rec.error

    # Parameters missing type OBJECT
    mod.TOOL["parameters"] = {"type": "STRING"}
    rec = _validate(mod, "mod.py")
    assert rec.valid is False
    assert "TOOL['parameters'] must be a dict with \"type\": \"OBJECT\"" in rec.error


def test_validate_handler_requirements():
    mod = types.ModuleType("mod")
    mod.TOOL = {  # type: ignore
        "name": "valid_name",
        "description": "Valid description",
        "handler": "not-a-callable",
    }
    rec = _validate(mod, "mod.py")
    assert rec.valid is False
    assert "TOOL['handler'] missing or not callable" in rec.error


def test_validate_valid_tool_and_options():
    mod = types.ModuleType("mod")
    mod.TOOL = {  # type: ignore
        "name": "valid_action",
        "description": "  A test action description.  ",
        "parameters": {"type": "OBJECT", "properties": {"target": {"type": "STRING"}}},
        "handler": lambda parameters: "ok",
        "behavior": "non_blocking",
        "scheduling": "silent",
    }
    rec = _validate(mod, "valid_mod.py")
    assert rec.valid is True
    assert rec.error == ""
    assert rec.name == "valid_action"
    assert rec.description == "A test action description."
    assert rec.behavior == "NON_BLOCKING"
    assert rec.scheduling == "SILENT"


def test_call_handler_signature_dispatch():
    # 1. Handler taking only parameters
    def h1(parameters):
        return f"h1:{parameters.get('x')}"

    assert _call_handler(h1, {"x": 42}, {"player": "ignored"}) == "h1:42"

    # 2. Handler taking parameters and specific context kwargs
    def h2(parameters, player=None, session_memory=None):
        return f"h2:{parameters.get('y')}:{player}:{session_memory}"

    res2 = _call_handler(h2, {"y": 99}, {"player": "Alice", "session_memory": {"k": "v"}, "speak": "ignored"})
    assert res2 == "h2:99:Alice:{'k': 'v'}"

    # 3. Handler with **kwargs
    def h3(parameters, **kwargs):
        return f"h3:{sorted(kwargs.keys())}"

    res3 = _call_handler(h3, {}, {"player": "P", "speak": "S", "response": "R", "session_memory": "M"})
    assert res3 == "h3:['player', 'response', 'session_memory', 'speak']"


def test_action_registry_declarations_and_scheduling():
    def dummy_handler(parameters):
        return "done"

    rec1 = ActionRecord(
        name="tool_one",
        description="First tool",
        parameters={"type": "OBJECT", "properties": {"q": {"type": "STRING"}}},
        handler=dummy_handler,
        valid=True,
        behavior="NON_BLOCKING",
        scheduling="SILENT",
    )
    rec2 = ActionRecord(
        name="tool_two",
        description="Second tool",
        parameters={"type": "OBJECT", "properties": {}},
        handler=dummy_handler,
        valid=True,
    )

    registry = ActionRegistry({"tool_one": rec1, "tool_two": rec2}, logger=lambda m: None)

    assert registry.has("tool_one") is True
    assert registry.has("tool_two") is True
    assert registry.has("non_existent") is False
    assert registry.names() == {"tool_one", "tool_two"}
    assert registry.scheduling("tool_one") == "SILENT"
    assert registry.scheduling("tool_two") is None

    decls = registry.get_tool_declarations()
    assert len(decls) == 2
    decl_map = {d["name"]: d for d in decls}
    assert decl_map["tool_one"]["behavior"] == "NON_BLOCKING"
    assert "behavior" not in decl_map["tool_two"]


def test_action_registry_run_lifecycle():
    logs = []

    def successful_handler(parameters, **kwargs):
        return f"Echo: {parameters.get('msg')}"

    def none_return_handler(parameters):
        return None

    def crashing_handler(parameters):
        raise ValueError("Invalid state encountered")

    actions = {
        "echo": ActionRecord(name="echo", handler=successful_handler, valid=True),
        "none_action": ActionRecord(name="none_action", handler=none_return_handler, valid=True),
        "crash": ActionRecord(name="crash", handler=crashing_handler, valid=True),
        "invalid": ActionRecord(name="invalid", handler=successful_handler, valid=False),
    }

    registry = ActionRegistry(actions, logger=logs.append)

    # 1. Successful run
    assert registry.run("echo", {"msg": "hello world"}) == "Echo: hello world"

    # 2. None return defaults to 'Done.'
    assert registry.run("none_action", {}) == "Done."

    # 3. Non-existent tool returns clean unavailability message
    assert registry.run("missing_tool", {}) == "Action 'missing_tool' is not available."

    # 4. Invalid tool record returns clean unavailability message
    assert registry.run("invalid", {}) == "Action 'invalid' is not available."

    # 5. Handler crash is safely caught without raising out
    crash_result = registry.run("crash", {})
    assert "Tool 'crash' failed: Invalid state encountered" in crash_result
    assert any("crashed during run()" in log for log in logs)


def test_discover_actions_in_temp_directory(tmp_path: Path):
    logs = []

    # 1. Ignored files: starts with _
    (tmp_path / "_helper.py").write_text("FOO = 1\n", encoding="utf-8")
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    # 2. Ignored file: no TOOL dict
    (tmp_path / "not_an_action.py").write_text("def helper(): pass\n", encoding="utf-8")

    # 3. Valid action
    valid_code = """
TOOL = {
    "name": "custom_greeting",
    "description": "Greets a person by name",
    "parameters": {
        "type": "OBJECT",
        "properties": {"name": {"type": "STRING"}}
    },
    "handler": lambda parameters: f"Hello, {parameters.get('name', 'friend')}!"
}
"""
    (tmp_path / "greeting_action.py").write_text(valid_code, encoding="utf-8")

    # 4. Broken action: syntax error
    (tmp_path / "broken_syntax.py").write_text("def syntax_error(:\n", encoding="utf-8")

    registry = discover_actions(tmp_path, reserved_names={"reserved_tool"}, logger=logs.append)

    assert registry.has("custom_greeting") is True
    assert registry.has("not_an_action") is False
    assert registry.has("broken_syntax") is False

    # Execution of the dynamically loaded action
    res = registry.run("custom_greeting", {"name": "Abhay"})
    assert res == "Hello, Abhay!"

    # Verify broken module logged an error without crashing discover_actions
    assert any("Failed to load" in log for log in logs)


def test_discover_actions_reserved_and_duplicate_collision(tmp_path: Path):
    logs = []

    # Action colliding with reserved name
    reserved_code = """
TOOL = {
    "name": "reserved_core",
    "description": "Collides with core tool",
    "parameters": {"type": "OBJECT"},
    "handler": lambda parameters: "ok"
}
"""
    (tmp_path / "a_reserved.py").write_text(reserved_code, encoding="utf-8")

    # Duplicate action names across two files
    dup1 = """
TOOL = {
    "name": "duplicate_tool",
    "description": "First definition",
    "parameters": {"type": "OBJECT"},
    "handler": lambda parameters: "first"
}
"""
    dup2 = """
TOOL = {
    "name": "duplicate_tool",
    "description": "Second definition",
    "parameters": {"type": "OBJECT"},
    "handler": lambda parameters: "second"
}
"""
    (tmp_path / "b_first.py").write_text(dup1, encoding="utf-8")
    (tmp_path / "c_second.py").write_text(dup2, encoding="utf-8")

    registry = discover_actions(tmp_path, reserved_names={"reserved_core"}, logger=logs.append)

    # Reserved tool was rejected
    assert registry.has("reserved_core") is False
    assert any("collides with a reserved core tool" in log for log in logs)

    # Duplicate tool: first loaded, second rejected
    assert registry.has("duplicate_tool") is True
    assert registry.run("duplicate_tool", {}) == "first"
    assert any("already used by action" in log for log in logs)


def test_action_registry_concurrency():
    counter = 0
    lock = concurrent.futures.ThreadPoolExecutor(max_workers=8)

    def counter_handler(parameters):
        nonlocal counter
        return f"val_{parameters.get('id')}"

    rec = ActionRecord(name="concurrent_tool", handler=counter_handler, valid=True)
    registry = ActionRegistry({"concurrent_tool": rec}, logger=lambda m: None)

    def worker(worker_id: int) -> str:
        return registry.run("concurrent_tool", {"id": worker_id})

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(50)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 50
    assert all(r.startswith("val_") for r in results)


def test_get_action_registry_singleton():
    reg1 = get_action_registry()
    reg2 = get_action_registry()
    assert isinstance(reg1, ActionRegistry)
    assert reg1 is reg2
