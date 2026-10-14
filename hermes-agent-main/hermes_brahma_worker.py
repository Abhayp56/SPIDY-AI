"""
hermes_brahma_worker.py — Standalone Hermes Agent Worker Node for Brahma Web AI

Connects Hermes Agent directly to the Brahma Web AI (Cloud Server / Web UI).
Receives remote execution tasks from Web AI over persistent WebSockets,
executes them autonomously using Hermes Agent tools, and streams real-time
progress updates back to the Web UI.

Usage:
    python hermes_brahma_worker.py [--server ws://127.0.0.1:8000/ws/node] [--token YOUR_TOKEN]
"""

from __future__ import annotations

from pathlib import Path
import sys

# Setup paths
HERMES_DIR = Path(__file__).resolve().parent
BRAHMA_ROOT = HERMES_DIR.parent / "Brahma-Echo-main"
if not BRAHMA_ROOT.exists():
    BRAHMA_ROOT = HERMES_DIR.parent

if str(HERMES_DIR) not in sys.path:
    sys.path.insert(0, str(HERMES_DIR))
if str(BRAHMA_ROOT) not in sys.path:
    sys.path.insert(0, str(BRAHMA_ROOT))

try:
    import hermes_bootstrap  # noqa: F401
except Exception:
    pass

import argparse
import asyncio
import json
import logging
import os
import time
import traceback
from typing import Any, Dict, Optional

import websockets

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("HermesBrahmaWorker")

# Import Brahma protocol & local tool dispatcher
try:
    from core.distributed.protocol import (
        ProtocolTypes,
        MessageEnvelope,
        build_message,
        parse_message,
    )
    from core.distributed.local_tool_dispatcher import LocalToolDispatcher, HeadlessPlayerShim
except Exception as e:
    logger.error(f"Failed to import Brahma distributed protocol: {e}")
    sys.exit(1)

# Import Hermes AIAgent runner
try:
    from run_agent import AIAgent
except Exception as e:
    logger.warning(f"Could not import Hermes AIAgent directly: {e}")
    AIAgent = None


CONFIG_PATH = BRAHMA_ROOT / "config" / "cloud_config.json"
API_KEYS_PATH = BRAHMA_ROOT / "config" / "api_keys.json"


def load_worker_config() -> Dict[str, Any]:
    default_cfg = {
        "cloud_server_url": "ws://127.0.0.1:8000/ws/node",
        "auth_token": "brahma_secret_cloud_token_2026",
        "device_name": "Hermes-Laptop-Worker",
        "reconnect_interval": 3,
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                default_cfg.update(cfg)
        except Exception as e:
            logger.warning(f"Failed to read {CONFIG_PATH}: {e}")
    return default_cfg


def load_llm_credentials() -> Dict[str, str]:
    """Load LLM credentials for Hermes (OpenRouter primary, Gemini fallback)."""
    keys = {}
    if API_KEYS_PATH.exists():
        try:
            with open(API_KEYS_PATH, "r", encoding="utf-8") as f:
                keys = json.load(f)
        except Exception:
            pass

    openrouter_key = keys.get("openrouter_api_key", "").strip() or os.environ.get("OPENROUTER_API_KEY", "").strip()
    gemini_key = keys.get("gemini_api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()

    if openrouter_key:
        return {
            "api_key": openrouter_key,
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "nousresearch/hermes-3-llama-3.1-405b:free",
        }
    elif gemini_key:
        return {
            "api_key": gemini_key,
            "provider": "google",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash",
        }
    return {}


class HermesWorkerNode:
    """Hermes Agent worker node connected to Brahma Web AI Cloud Server."""

    def __init__(self, server_url: str, token: str, device_name: str):
        self.server_url = server_url
        self.token = token
        self.device_name = device_name
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.dispatcher = LocalToolDispatcher()
        self.is_running = True

    async def start(self):
        logger.info(f"Starting Hermes Worker Node connecting to '{self.server_url}'...")
        while self.is_running:
            try:
                async with websockets.connect(
                    self.server_url,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self.ws = ws
                    logger.info("Connected to Brahma Cloud Server! Sending Auth packet...")
                    await self._send_auth()
                    await self._receive_loop()
            except asyncio.CancelledError:
                logger.info("Hermes Worker Node stopping...")
                break
            except Exception as e:
                logger.warning(f"WebSocket connection lost: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)

    async def _send_auth(self):
        auth_msg = build_message(
            ProtocolTypes.AUTH,
            {
                "token": self.token,
                "device_name": self.device_name,
                "capabilities": ["hermes_agent", "terminal", "python", "browser", "desktop"],
            },
        )
        await self.ws.send(auth_msg.to_json())

    async def _send_progress(self, request_id: str, text: str):
        if not self.ws:
            return
        msg = build_message(
            ProtocolTypes.TOOL_PROGRESS,
            {"progress": text},
            request_id=request_id,
        )
        try:
            await self.ws.send(msg.to_json())
        except Exception as e:
            logger.warning(f"Failed to send progress update: {e}")

    async def _receive_loop(self):
        async for raw_msg in self.ws:
            try:
                env = parse_message(raw_msg)
                logger.info(f"Received message type='{env.type}' req_id='{env.request_id}'")

                if env.type == ProtocolTypes.AUTH_ACK:
                    logger.info("✅ Auth acknowledged! Hermes Node registered and ready for Web AI commands.")

                elif env.type == ProtocolTypes.PING:
                    pong = build_message(ProtocolTypes.PONG, {}, request_id=env.request_id)
                    await self.ws.send(pong.to_json())

                elif env.type == ProtocolTypes.EXECUTE_TOOL:
                    asyncio.create_task(self._handle_tool_execution(env))

            except Exception as e:
                logger.error(f"Error handling message: {e}\n{traceback.format_exc()}")

    async def _handle_tool_execution(self, env: MessageEnvelope):
        tool_name = env.payload.get("tool_name", "hermes_agent")
        args = env.payload.get("args", {})
        req_id = env.request_id

        logger.info(f"Executing tool '{tool_name}' for Web AI request {req_id}...")
        await self._send_progress(req_id, f"Hermes Node accepted task: {tool_name}")

        loop = asyncio.get_running_loop()

        try:
            # If tool is hermes_agent or NL task, run Hermes AIAgent loop
            if tool_name in {"hermes_agent", "hermes_task", "run_hermes_agent"} or AIAgent and tool_name not in self.dispatcher._get_tool_handler(tool_name).__name__ if self.dispatcher._get_tool_handler(tool_name) else False:
                task_prompt = args.get("task") or args.get("prompt") or args.get("description") or json.dumps(args)
                result = await loop.run_in_executor(
                    None,
                    lambda: self._run_hermes_task(task_prompt, req_id)
                )
            else:
                # Dispatch local tool execution
                result = await self.dispatcher.execute(tool_name, args)

            result_msg = build_message(
                ProtocolTypes.TOOL_RESULT,
                {
                    "success": result.get("success", True),
                    "result": result.get("result"),
                    "error": result.get("error"),
                },
                request_id=req_id,
            )
            await self.ws.send(result_msg.to_json())
            logger.info(f"Task {req_id} complete. Result sent to Web AI.")

        except Exception as e:
            err_msg = str(e)
            logger.error(f"Task {req_id} failed: {err_msg}")
            result_msg = build_message(
                ProtocolTypes.TOOL_RESULT,
                {
                    "success": False,
                    "result": None,
                    "error": err_msg,
                },
                request_id=req_id,
            )
            await self.ws.send(result_msg.to_json())

    def _run_hermes_task(self, prompt: str, request_id: str) -> Dict[str, Any]:
        """Runs Hermes AIAgent for multi-step task execution."""
        if not AIAgent:
            return {"success": False, "result": None, "error": "Hermes AIAgent module not available."}

        creds = load_llm_credentials()
        if not creds:
            return {
                "success": False,
                "result": None,
                "error": "No LLM API key configured for Hermes. Please add openrouter_api_key or gemini_api_key in config/api_keys.json.",
            }

        def _on_progress(text: str):
            logger.info(f"[Hermes Progress] {text}")
            if self.ws and self.ws.open:
                try:
                    msg = build_message(
                        ProtocolTypes.TOOL_PROGRESS,
                        {"progress": f"[Hermes Agent] {text}"},
                        request_id=request_id,
                    )
                    asyncio.run_coroutine_threadsafe(self.ws.send(msg.to_json()), asyncio.get_event_loop())
                except Exception:
                    pass

        agent_kwargs = {
            "model": creds["model"],
            "api_key": creds["api_key"],
            "provider": creds["provider"],
            "base_url": creds["base_url"],
            "max_iterations": 25,
            "status_callback": lambda t: _on_progress(f"Status: {t}"),
            "tool_progress_callback": lambda t: _on_progress(f"Tool: {t}"),
        }

        try:
            agent = AIAgent(**agent_kwargs)
            res = agent.run_conversation(prompt)
            return {"success": True, "result": str(res) if res else "Hermes completed task.", "error": None}
        except Exception as exc:
            return {"success": False, "result": None, "error": f"Hermes execution error: {exc}"}


def main():
    parser = argparse.ArgumentParser(description="Hermes Agent Worker for Brahma Web AI")
    parser.add_argument("--server", default=None, help="WebSocket URL of Brahma Cloud Server")
    parser.add_argument("--token", default=None, help="Auth token for Brahma Cloud")
    args = parser.parse_args()

    cfg = load_worker_config()
    server_url = args.server or cfg["cloud_server_url"]
    token = args.token or cfg["auth_token"]
    device_name = cfg["device_name"]

    node = HermesWorkerNode(server_url=server_url, token=token, device_name=device_name)
    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        logger.info("Hermes Worker stopped by user.")


if __name__ == "__main__":
    main()
