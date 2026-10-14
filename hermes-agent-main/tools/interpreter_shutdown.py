"""
tools/interpreter_shutdown.py — Interpreter shutdown detection.
"""
import sys

def interpreter_shutting_down(*args, **kwargs) -> bool:
    return sys.is_finalizing() if hasattr(sys, "is_finalizing") else False
