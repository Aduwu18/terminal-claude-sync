"""
Terminal Claude Client

CLI interface for Claude with Feishu synchronization.
"""
import argparse
import asyncio
import fcntl
import json
import logging
import os
import select
import signal
import socket
import sys
import termios
import tty
from typing import Optional

import aiohttp

from src.native_claude_client import (
    NativeClaudeClient,
    NativeEventType,
    NativeEvent,
)
from src.terminal_session_manager import TerminalSessionManager
from src.config import get_terminal_session_config, get_bridge_config, get_permission_config

logger = logging.getLogger(__name__)


class TerminalClient:
    """
    Terminal Claude Client.

    Provides interactive CLI with Feishu synchronization.
    """

    def __init__(
        self,
        terminal_id: str = None,
        bridge_url: str = "http://localhost:8081",
        cli_mode: str = "print",  # "pty" or "print"
        sync_mode: str = "notify",  # "notify" or "sync"
        user_open_id: str = None,
    ):
        self.terminal_id = terminal_id or self._generate_terminal_id()
        self.bridge_url = bridge_url
        self.cli_mode = cli_mode
        self.sync_mode = sync_mode
        self.user_open_id = user_open_id

        self._native_client: Optional[NativeClaudeClient] = None
        self._ws = None
        self._session_manager: Optional[TerminalSessionManager] = None
        self._running = False
        self._original_termios = None
        self._session = None

    @staticmethod
    def _generate_terminal_id() -> str:
        """Generate unique terminal ID."""
        import time
        hostname = socket.gethostname()
        timestamp = int(time.time())
        return f"{hostname}-{timestamp}"

    async def start(self):
        """Start the terminal client."""
        # Setup signal handlers
        self._setup_signal_handlers()

        # Create terminal session (auto-create Feishu group chat)
        await self._create_session()

        # Connect to bridge via WebSocket
        await self._connect_bridge()

        # Start native Claude client
        await self._start_native_client()

        self._running = True

        # Run main loop based on mode
        if self.cli_mode == "pty":
            await self._run_pty_mode()
        else:
            await self._run_print_mode()

    async def _create_session(self):
        """Create terminal session with Feishu group chat."""
        config = get_terminal_session_config()
        self.user_open_id = self.user_open_id or config.get("user_open_id")

        if not self.user_open_id:
            logger.error("user_open_id not configured")
            print("Error: user_open_id not configured. Set it in config.yaml")
            sys.exit(1)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.bridge_url}/terminal/create",
                    json={
                        "terminal_id": self.terminal_id,
                        "user_open_id": self.user_open_id,
                    },
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._session = data
                        logger.info(f"Terminal session created: {self.terminal_id}")
                        print(f"Terminal session created. Chat ID: {data.get('chat_id')}")
                    else:
                        error = await resp.text()
                        logger.error(f"Failed to create session: {error}")
                        print(f"Error: Failed to create terminal session: {error}")
                        sys.exit(1)
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            print(f"Error: Failed to connect to bridge server: {e}")
            sys.exit(1)

    async def _connect_bridge(self):
        """Connect to bridge server via WebSocket."""
        try:
            self._ws_session = aiohttp.ClientSession()
            self._ws = await self._ws_session.ws_connect(
                f"{self.bridge_url}/ws?terminal_id={self.terminal_id}"
            )
            logger.info("Connected to bridge server")

            # Start message handler
            asyncio.create_task(self._handle_ws_messages())

        except Exception as e:
            logger.warning(f"Failed to connect to bridge: {e}")
            self._ws = None

    async def _handle_ws_messages(self):
        """Handle messages from bridge server."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    await self._process_ws_message(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self._ws.exception()}")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"WebSocket message error: {e}")

    async def _process_ws_message(self, data: dict):
        """Process message from bridge (from Feishu)."""
        msg_type = data.get("type")

        if msg_type == "feishu_message":
            # Message from Feishu, inject into CLI
            message = data.get("message", "")
            if self.cli_mode == "pty" and self._native_client:
                # Inject as user input
                self._native_client.write(message + "\n")
            else:
                # Process in print mode
                await self._process_print_message(message)

        elif msg_type == "permission_response":
            # Permission response from Feishu
            approved = data.get("approved", False)
            if self._native_client:
                await self._native_client.resolve_permission(approved)

    async def _start_native_client(self):
        """Start the native Claude client."""
        working_dir = os.getcwd()

        self._native_client = NativeClaudeClient(
            session_id=self._session.get("session_id") if self._session else None,
            working_dir=working_dir,
            mode=self.cli_mode,
            sync_mode=self.sync_mode,
            bridge_url=self.bridge_url,
            chat_id=self._session.get("chat_id") if self._session else None,
            on_event=self._handle_native_event,
            raw_pty=(self.cli_mode == "pty"),
        )

        await self._native_client.start()

    def _handle_native_event(self, event: NativeEvent):
        """Handle events from native client."""
        if event.event_type == NativeEventType.RAW_OUTPUT:
            # Raw PTY output - just print
            print(event.data.get("output", ""), end="", flush=True)

        elif event.event_type == NativeEventType.PERMISSION_REQUEST:
            # Permission request detected
            tool_name = event.data.get("tool_name", "")
            tool_input = event.data.get("tool_input", {})
            self._handle_permission_request(tool_name, tool_input)

        elif event.event_type == NativeEventType.CONTENT:
            # Content from print mode
            print(event.data.get("text", ""), end="", flush=True)

        elif event.event_type == NativeEventType.TOOL_CALL:
            # Tool call notification
            tool_name = event.data.get("name", "")
            print(f"\n[Tool: {tool_name}]", flush=True)

        elif event.event_type == NativeEventType.COMPLETE:
            # Task completed
            session_id = event.data.get("session_id", "")
            if session_id and self._session:
                self._session["session_id"] = session_id

        elif event.event_type == NativeEventType.ERROR:
            # Error occurred
            print(f"\n[Error: {event.data.get('message', 'Unknown error')}]", flush=True)

    def _handle_permission_request(self, tool_name: str, tool_input: dict):
        """Handle permission request with dual-channel confirmation."""
        config = get_permission_config()
        dual_channel = config.get("dual_channel", True)

        if dual_channel:
            print(f"\n[Claude wants to use {tool_name}]")
            print("[Check Feishu for details or press y/n here]")
        else:
            print(f"\n[Claude wants to use {tool_name}]")
            print(f"Details: {json.dumps(tool_input, indent=2)}")
            print("Allow? [y/n] ", end="", flush=True)

    async def _run_pty_mode(self):
        """Run in PTY mode - raw terminal interaction."""
        # Save original terminal settings
        self._original_termios = termios.tcgetattr(sys.stdin)

        try:
            # Set terminal to raw mode
            tty.setraw(sys.stdin)

            # Make stdin non-blocking
            flags = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
            fcntl.fcntl(sys.stdin, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            loop = asyncio.get_event_loop()

            while self._running:
                try:
                    # Use async stdin reading instead of blocking select
                    char = await loop.run_in_executor(None, self._read_stdin_char)

                    if char:
                        # Forward to native client
                        if self._native_client:
                            self._native_client.write(char)

                        # Check for Ctrl+C
                        if char == "\x03":
                            break
                        # Check for Ctrl+D
                        if char == "\x04":
                            break

                except Exception as e:
                    if self._running:
                        logger.debug(f"Error reading stdin: {e}")

                # Small yield to let other tasks run
                await asyncio.sleep(0.01)

        finally:
            # Restore terminal settings
            if self._original_termios:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._original_termios)

    def _read_stdin_char(self) -> str:
        """Read a single character from stdin (blocking)."""
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if ready:
            try:
                return sys.stdin.read(1)
            except:
                return ""
        return ""

    async def _run_print_mode(self):
        """Run in print mode - each message is a new process."""
        print("\nTerminal Claude Client (Print Mode)")
        print("Type your message and press Enter. Type '/exit' to quit.\n")

        while self._running:
            try:
                # Read user input
                print("You: ", end="", flush=True)
                loop = asyncio.get_event_loop()
                message = await loop.run_in_executor(None, sys.stdin.readline)

                if not message:
                    break

                message = message.strip()

                # Handle commands
                if message == "/exit":
                    break
                elif message == "/help":
                    self._print_help()
                    continue
                elif not message:
                    continue

                # Send to Claude
                print("\nClaude: ", end="", flush=True)

                async for event in self._native_client.chat_stream(message):
                    if event.event_type == NativeEventType.CONTENT:
                        print(event.data.get("text", ""), end="", flush=True)
                    elif event.event_type == NativeEventType.TOOL_CALL:
                        print(f"\n[Tool: {event.data.get('name', '')}]", flush=True)
                    elif event.event_type == NativeEventType.COMPLETE:
                        if event.data.get("cost"):
                            print(f"\n[Cost: ${event.data['cost']:.4f}]", flush=True)

                print()  # Newline after response

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in print mode: {e}")
                print(f"\n[Error: {e}]", flush=True)

    async def _process_print_message(self, message: str):
        """Process message from Feishu in print mode."""
        print(f"\n[Feishu] {message}")
        print("\nClaude: ", end="", flush=True)

        async for event in self._native_client.chat_stream(message):
            if event.event_type == NativeEventType.CONTENT:
                print(event.data.get("text", ""), end="", flush=True)
            elif event.event_type == NativeEventType.COMPLETE:
                print()

    def _print_help(self):
        """Print help message."""
        print("""
Commands:
  /exit    - Exit the client
  /help    - Show this help message

Just type your message and press Enter to chat with Claude.
""")

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self._running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def stop(self):
        """Stop the terminal client."""
        self._running = False

        # Stop native client
        if self._native_client:
            await self._native_client.stop()

        # Close WebSocket
        if self._ws:
            await self._ws.close()
        if hasattr(self, "_ws_session"):
            await self._ws_session.close()

        # Close terminal session
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{self.bridge_url}/terminal/close",
                    json={"terminal_id": self.terminal_id},
                )
        except Exception as e:
            logger.warning(f"Failed to close session: {e}")

        logger.info("Terminal client stopped")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Terminal Claude Client with Feishu Sync")
    parser.add_argument(
        "--terminal-id",
        default=None,
        help="Terminal ID (auto-generated if not specified)",
    )
    parser.add_argument(
        "--bridge-url",
        default="http://localhost:8081",
        help="Bridge server URL",
    )
    parser.add_argument(
        "--cli-mode",
        choices=["pty", "print"],
        default="print",
        help="CLI mode: pty (interactive) or print (each message is new process)",
    )
    parser.add_argument(
        "--sync-mode",
        choices=["notify", "sync"],
        default="notify",
        help="Sync mode: notify (key events only) or sync (full output)",
    )
    parser.add_argument(
        "--user-open-id",
        default=None,
        help="Feishu user open_id",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create and start client
    client = TerminalClient(
        terminal_id=args.terminal_id,
        bridge_url=args.bridge_url,
        cli_mode=args.cli_mode,
        sync_mode=args.sync_mode,
        user_open_id=args.user_open_id,
    )

    try:
        await client.start()
    except KeyboardInterrupt:
        pass
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())