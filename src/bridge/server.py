"""
Bridge Server

HTTP/WebSocket server for Terminal CLI <-> Feishu communication.

Features:
- WebSocket endpoint for bidirectional communication
- Terminal session management (create/close/sync)
- Permission handling (request/response from Feishu)
- Health checks
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Any

from aiohttp import web, WSMsgType

from src.terminal_session_manager import (
    TerminalSessionManager,
    get_terminal_session_manager,
)
from src.native_claude_client import NativeClaudeClient, NativeEventType
from src.feishu_utils.card_builder import build_permission_card
from src.feishu_utils.feishu_utils import send_card_message

logger = logging.getLogger(__name__)


class BridgeServer:
    """
    Bridge Server for Terminal CLI.

    Endpoints:
        GET  /health              - Health check
        GET  /status              - Detailed status
        GET  /ws                  - WebSocket connection
        POST /terminal/create     - Create terminal session
        POST /terminal/close      - Close terminal session
        POST /terminal/sync       - Sync output/status
        POST /permission/request  - Permission request from CLI
        POST /permission/response - Permission response from Feishu
    """

    def __init__(self, port: int = 8082):
        self.port = port
        self.app = web.Application()
        self._setup_routes()

        self._session_manager: Optional[TerminalSessionManager] = None
        self._native_clients: Dict[str, NativeClaudeClient] = {}
        self._permission_futures: Dict[str, asyncio.Future] = {}
        self._ws_connections: Dict[str, web.WebSocketResponse] = {}

    def _setup_routes(self):
        """Setup HTTP routes."""
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_get("/status", self._handle_status)
        self.app.router.add_get("/ws", self._handle_websocket)
        self.app.router.add_post("/terminal/create", self._handle_terminal_create)
        self.app.router.add_post("/terminal/close", self._handle_terminal_close)
        self.app.router.add_post("/terminal/sync", self._handle_terminal_sync)
        self.app.router.add_post("/permission/request", self._handle_permission_request)
        self.app.router.add_post("/permission/response", self._handle_permission_response)

    async def start(self):
        """Start the server."""
        self._session_manager = get_terminal_session_manager()

        runner = web.AppRunner(self.app)
        await runner.setup()

        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()

        logger.info(f"Bridge Server started on port {self.port}")

        # Keep running
        while True:
            await asyncio.sleep(3600)

    # =========================================================================
    # HTTP Handlers
    # =========================================================================

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "service": "terminal-bridge",
            "port": self.port,
        })

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Detailed status endpoint."""
        sessions = self._session_manager.list_sessions() if self._session_manager else []

        return web.json_response({
            "status": "ok",
            "active_sessions": len(sessions),
            "active_clients": len(self._native_clients),
            "pending_permissions": len(self._permission_futures),
            "ws_connections": len(self._ws_connections),
            "sessions": [
                {
                    "terminal_id": s.terminal_id,
                    "chat_id": s.chat_id,
                    "status": s.status,
                    "message_count": s.message_count,
                }
                for s in sessions
            ],
        })

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for bidirectional communication."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        terminal_id = request.query.get("terminal_id")
        if not terminal_id:
            await ws.close(code=4000, message=b"terminal_id required")
            return ws

        self._ws_connections[terminal_id] = ws
        logger.info(f"WebSocket connected: {terminal_id}")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_ws_message(terminal_id, data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from {terminal_id}")
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
        finally:
            self._ws_connections.pop(terminal_id, None)
            logger.info(f"WebSocket disconnected: {terminal_id}")

        return ws

    async def _handle_ws_message(self, terminal_id: str, data: dict):
        """Handle WebSocket message from Terminal CLI."""
        msg_type = data.get("type")

        if msg_type == "input":
            # User input from terminal, forward to native client if exists
            client = self._native_clients.get(terminal_id)
            if client:
                client.write(data.get("data", ""))

        elif msg_type == "permission_response":
            # Permission response from terminal user
            approved = data.get("approved", False)
            request_id = data.get("request_id")
            if request_id and request_id in self._permission_futures:
                self._permission_futures[request_id].set_result(approved)

        elif msg_type == "resize":
            # Terminal resize event
            client = self._native_clients.get(terminal_id)
            if client and hasattr(client, "_pty_client") and client._pty_client:
                client._pty_client.resize(
                    data.get("rows", 24),
                    data.get("cols", 80),
                )

    async def _handle_terminal_create(self, request: web.Request) -> web.Response:
        """Create terminal session (auto-create Feishu group chat)."""
        try:
            data = await request.json()
            terminal_id = data.get("terminal_id")
            user_open_id = data.get("user_open_id")
            session_id = data.get("session_id")

            if not terminal_id:
                return web.json_response(
                    {"error": "terminal_id required"},
                    status=400,
                )

            session = await self._session_manager.create_session(
                terminal_id=terminal_id,
                user_open_id=user_open_id,
                session_id=session_id,
            )

            return web.json_response({
                "status": "ok",
                "terminal_id": session.terminal_id,
                "chat_id": session.chat_id,
                "session_id": session.session_id,
            })

        except Exception as e:
            logger.error(f"Create terminal session failed: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500,
            )

    async def _handle_terminal_close(self, request: web.Request) -> web.Response:
        """Close terminal session (disband Feishu group chat)."""
        try:
            data = await request.json()
            terminal_id = data.get("terminal_id")
            disband_chat = data.get("disband_chat", True)

            if not terminal_id:
                return web.json_response(
                    {"error": "terminal_id required"},
                    status=400,
                )

            # Stop native client if exists
            if terminal_id in self._native_clients:
                await self._native_clients[terminal_id].stop()
                del self._native_clients[terminal_id]

            success = await self._session_manager.close_session(
                terminal_id=terminal_id,
                disband_chat=disband_chat,
            )

            return web.json_response({
                "status": "ok" if success else "not_found",
                "terminal_id": terminal_id,
            })

        except Exception as e:
            logger.error(f"Close terminal session failed: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500,
            )

    async def _handle_terminal_sync(self, request: web.Request) -> web.Response:
        """Sync output/status to Feishu group chat."""
        try:
            data = await request.json()
            terminal_id = data.get("terminal_id")
            sync_type = data.get("sync_type", "output")  # "output" or "status"
            content = data.get("content", "")

            if not terminal_id:
                return web.json_response(
                    {"error": "terminal_id required"},
                    status=400,
                )

            if sync_type == "status":
                status = data.get("status", "running")
                details = data.get("details", {})
                success = await self._session_manager.sync_status(
                    terminal_id, status, details
                )
            else:
                success = await self._session_manager.sync_output(
                    terminal_id, content
                )

            return web.json_response({
                "status": "ok" if success else "failed",
            })

        except Exception as e:
            logger.error(f"Sync to Feishu failed: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500,
            )

    async def _handle_permission_request(self, request: web.Request) -> web.Response:
        """Permission request from native client to Feishu."""
        try:
            data = await request.json()
            terminal_id = data.get("terminal_id")
            tool_name = data.get("tool_name")
            tool_input = data.get("tool_input", {})
            timeout = data.get("timeout", 300)

            session = self._session_manager.get_session(terminal_id)
            if not session:
                return web.json_response(
                    {"error": "session not found"},
                    status=404,
                )

            # Send permission card to Feishu
            card = build_permission_card(tool_name, tool_input, session.chat_id)
            send_card_message(session.chat_id, card)

            # Create future for response
            request_id = f"{terminal_id}:{tool_name}"
            future = asyncio.Future()
            self._permission_futures[request_id] = future

            try:
                # Wait for response from Feishu or timeout
                approved = await asyncio.wait_for(future, timeout=timeout)
                return web.json_response({
                    "approved": approved,
                })
            except asyncio.TimeoutError:
                return web.json_response({
                    "approved": False,
                    "error": "timeout",
                })
            finally:
                self._permission_futures.pop(request_id, None)

        except Exception as e:
            logger.error(f"Permission request failed: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500,
            )

    async def _handle_permission_response(self, request: web.Request) -> web.Response:
        """Permission response from Feishu to native client."""
        try:
            data = await request.json()
            chat_id = data.get("chat_id")
            action = data.get("action")
            approved = action == "permission_approve"

            # Find terminal_id by chat_id
            terminal_id = self._session_manager.get_terminal_id(chat_id)
            if not terminal_id:
                return web.json_response(
                    {"error": "session not found"},
                    status=404,
                )

            # Resolve pending permission futures for this terminal
            for request_id, future in list(self._permission_futures.items()):
                if request_id.startswith(f"{terminal_id}:"):
                    if not future.done():
                        future.set_result(approved)

            # Also forward to WebSocket if connected
            ws = self._ws_connections.get(terminal_id)
            if ws:
                await ws.send_json({
                    "type": "permission_response",
                    "approved": approved,
                })

            # Also forward to native client
            client = self._native_clients.get(terminal_id)
            if client:
                await client.resolve_permission(approved)

            return web.json_response({"status": "ok"})

        except Exception as e:
            logger.error(f"Permission response failed: {e}")
            return web.json_response(
                {"error": str(e)},
                status=500,
            )

    # =========================================================================
    # Native Client Management
    # =========================================================================

    def register_native_client(self, terminal_id: str, client: NativeClaudeClient):
        """Register a native client for a terminal."""
        self._native_clients[terminal_id] = client

    def unregister_native_client(self, terminal_id: str):
        """Unregister a native client."""
        self._native_clients.pop(terminal_id, None)

    async def send_to_terminal(self, terminal_id: str, data: dict):
        """Send data to terminal via WebSocket."""
        ws = self._ws_connections.get(terminal_id)
        if ws:
            await ws.send_json(data)


# Global instance
_bridge_server: Optional[BridgeServer] = None


def get_bridge_server() -> BridgeServer:
    """Get global bridge server instance."""
    global _bridge_server
    if _bridge_server is None:
        from src.config import get_bridge_config
        config = get_bridge_config()
        _bridge_server = BridgeServer(port=config.get("port", 8082))
    return _bridge_server


async def run_bridge_server():
    """Run the bridge server."""
    server = get_bridge_server()
    await server.start()