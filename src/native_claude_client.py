"""
原生 Claude CLI 客户端

提供两种模式：
1. PTY 模式：完整的交互式体验
2. Print 模式：每条消息独立进程（更稳定，推荐）

支持：
- 权限确认双向处理（CLI 和飞书）
- 飞书同步（提醒模式/同步模式）
"""
import asyncio
import fcntl
import json
import logging
import os
import pty
import re
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)


# ============================================================================
# 权限请求检测模式
# ============================================================================

PERMISSION_PATTERNS = [
    r"Claude wants to use (\w+)(?:\s+with\s+.*)?\.?\s*(?:Allow|Approve)\?",
    r"Permission required for (\w+)",
    r"(\w+) requires confirmation",
    r"Tool call: (\w+).*\n.*\?\s*\[(?:y/n|Y/N)\]",
]


# ============================================================================
# 事件类型
# ============================================================================

class NativeEventType(str, Enum):
    """原生客户端事件类型"""
    STATUS = "status"
    CONTENT = "content"
    TOOL_CALL = "tool_call"
    PERMISSION_REQUEST = "permission_request"
    COMPLETE = "complete"
    ERROR = "error"
    RAW_OUTPUT = "raw_output"


@dataclass
class NativeEvent:
    """原生客户端事件"""
    event_type: NativeEventType
    data: dict
    timestamp: float = field(default_factory=lambda: __import__('time').time())

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ============================================================================
# PTY 模式客户端
# ============================================================================

class NativeClaudePTYClient:
    """
    原生 Claude CLI 客户端 (PTY 模式)

    使用 subprocess + PTY 而非 os.fork()，因为 fork 与 asyncio 不兼容。

    支持权限请求处理：当检测到权限请求时，发送事件通知，
    由外部系统（飞书/CLI）确认后注入响应。

    注意：权限等待不在此处阻塞，避免 PTY 缓冲区满导致死锁。
    """

    def __init__(
        self,
        session_id: str = None,
        working_dir: str = None,
        on_output: callable = None,
        raw_mode: bool = False,
        permission_handler: 'PermissionHandler' = None,
    ):
        self.session_id = session_id
        self.working_dir = working_dir or os.getcwd()
        self.on_output = on_output
        self.raw_mode = raw_mode
        self.permission_handler = permission_handler

        self._master_fd = None
        self._slave_fd = None
        self._process = None
        self._output_task = None
        self._running = False

        # 输出缓冲区（用于检测跨块的权限请求）
        self._output_buffer = ""
        self._output_buffer_max = 2000  # 保留最近 2000 字符

        # 待处理的权限响应队列
        self._pending_responses: asyncio.Queue = None

    async def start(self):
        """启动 Claude CLI 进程"""
        self._master_fd, self._slave_fd = pty.openpty()

        try:
            import shutil
            cols, rows = shutil.get_terminal_size()
        except Exception:
            cols, rows = 80, 24

        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

        # 注意：不在此处设置 PTY slave 的 raw mode。
        # 让子进程自己决定终端模式，避免干扰 Ink 框架的输入处理。
        # Ink 框架期望收到 \\n 作为确认，而父进程 raw mode 下 Enter 产生 \\r，
        # 所以我们在 write() 方法中将 \\r 转换为 \\n。

        args = ['claude']
        if self.session_id:
            args.extend(['--resume', self.session_id])

        def setup_ctty():
            # 创建新 session 并设置控制终端
            os.setsid()
            fcntl.ioctl(self._slave_fd, termios.TIOCSCTTY, 0)
            # 设置自己为前台进程组，避免 SIGTTIN/SIGTTOU
            os.tcsetpgrp(self._slave_fd, os.getpgrp())

        self._process = subprocess.Popen(
            args,
            stdin=self._slave_fd,
            stdout=self._slave_fd,
            stderr=self._slave_fd,
            cwd=self.working_dir,
            env={**os.environ, 'TERM': 'xterm-256color'},
            preexec_fn=setup_ctty,
        )

        # 关闭子进程端的 fd
        os.close(self._slave_fd)
        self._slave_fd = None

        # 设置 master fd 为非阻塞
        flags = fcntl.fcntl(self._master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self._master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._running = True

        # 初始化权限响应队列
        self._pending_responses = asyncio.Queue()

        # 开始读取输出
        self._output_task = asyncio.create_task(self._read_output())

        logger.info(f"Claude CLI 已启动 (PID: {self._process.pid}, raw_mode={self.raw_mode})")

    async def _read_output(self):
        """读取 PTY 输出"""
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # 检查子进程是否还在运行
                if self._process:
                    return_code = self._process.poll()
                    if return_code is not None:
                        logger.info(f"Claude CLI 进程已退出: return_code={return_code}")
                        self._running = False
                        break

                data = await loop.run_in_executor(
                    None,
                    self._blocking_read,
                    1024
                )

                if data:
                    output = data.decode('utf-8', errors='replace')

                    # 先转发输出（确保 UI 及时响应）
                    if self.on_output:
                        self.on_output(output)

                    # 检测权限请求（非阻塞，只发送通知）
                    self._check_permission_request(output)

            except OSError as e:
                # EIO (errno 5) 表示 slave 端已关闭，子进程可能退出
                if e.errno == 5:  # EIO
                    logger.debug("PTY slave 已关闭，子进程可能已退出")
                    if self._process:
                        return_code = self._process.poll()
                        if return_code is not None:
                            logger.info(f"Claude CLI 已退出 (EIO): return_code={return_code}")
                    self._running = False
                    break
                elif self._running:
                    logger.warning(f"PTY 读取错误: {e} (errno={e.errno})")
                    break
            except Exception as e:
                if self._running:
                    logger.debug(f"读取输出失败: {e}")
                break

    def _check_permission_request(self, output: str) -> Optional[dict]:
        """
        检测输出中的权限请求（非阻塞）

        只发送通知，不等待响应。响应由外部系统注入。
        """
        if not self.permission_handler:
            return None

        # 更新输出缓冲区
        self._output_buffer += output
        if len(self._output_buffer) > self._output_buffer_max:
            self._output_buffer = self._output_buffer[-self._output_buffer_max:]

        # 检测权限请求
        permission = self.permission_handler.detect_permission_request(self._output_buffer)
        if not permission:
            return None

        tool_name = permission.get("tool_name", "unknown")
        tool_input = permission.get("tool_input", {})

        logger.info(f"检测到权限请求: {tool_name}")

        # 异步发送权限请求到飞书（不阻塞）
        asyncio.create_task(
            self._handle_permission_request(tool_name, tool_input)
        )

        # 清空缓冲区
        self._output_buffer = ""

        return permission

    async def _handle_permission_request(self, tool_name: str, tool_input: dict):
        """处理权限请求（异步，可阻塞等待响应）"""
        try:
            approved = await self.permission_handler.request_confirmation(
                tool_name=tool_name,
                tool_input=tool_input,
                timeout=300.0,
            )

            # 注入响应到 PTY
            response = "y\n" if approved else "n\n"
            self.write(response)
            logger.info(f"已注入权限响应: {response.strip()}")

        except Exception as e:
            logger.error(f"权限确认失败: {e}")
            self.write("n\n")

    def _blocking_read(self, size: int) -> bytes:
        """阻塞读取"""
        import select
        import errno

        if self._master_fd is None:
            return b''

        try:
            ready, _, _ = select.select([self._master_fd], [], [], 0.1)
            if ready:
                return os.read(self._master_fd, size)
            return b''
        except OSError as e:
            raise
        except Exception as e:
            logger.debug(f"_blocking_read 异常: {e}")
            return b''

    def write(self, data: str):
        """写入数据到 PTY

        关键转换：将 CR (\\r) 转换为 LF (\\n)。
        这是因为父进程 raw mode 下 Enter 产生 \\r，
        但子进程 (Ink 框架) 期望 \\n 作为确认。
        """
        if self._master_fd is not None:
            # 将 \r (CR, 0x0D) 转换为 \n (LF, 0x0A)
            data = data.replace('\r', '\n')
            try:
                os.write(self._master_fd, data.encode('utf-8'))
            except OSError as e:
                logger.debug(f"PTY 写入失败: {e}")

    def resize(self, rows: int, cols: int):
        """调整终端大小"""
        if self._master_fd is not None:
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    async def stop(self):
        """停止进程"""
        self._running = False

        if self._output_task:
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass

        if self._process:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            except Exception as e:
                logger.warning(f"停止进程失败: {e}")

        if self._master_fd is not None:
            os.close(self._master_fd)
            self._master_fd = None

        logger.info("Claude CLI 已停止")


class NativeClaudePrintClient:
    """
    原生 Claude CLI 客户端 (Print 模式)
    """

    def __init__(
        self,
        session_id: str = None,
        working_dir: str = None,
    ):
        self.session_id = session_id
        self.working_dir = working_dir or os.getcwd()

    async def chat(self, message: str) -> dict:
        """发送消息"""
        cmd = ['claude', '--print', '--output-format', 'stream-json', '--verbose']

        if self.session_id:
            cmd.extend(['--resume', self.session_id])

        logger.info(f"执行: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
        )

        proc.stdin.write(message.encode())
        proc.stdin.close()
        await proc.stdin.drain()

        lines = []
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            lines.append(line.decode())

        await proc.wait()

        result = {
            "response": "",
            "session_id": None,
            "cost": 0,
            "raw_events": [],
        }

        for line in lines:
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
                result["raw_events"].append(event)

                if event.get("type") == "system":
                    result["session_id"] = event.get("session_id")

                elif event.get("type") == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            result["response"] += block.get("text", "")

                elif event.get("type") == "result":
                    result["session_id"] = event.get("session_id")
                    result["cost"] = event.get("total_cost_usd", 0)
                    if not result["response"]:
                        result["response"] = event.get("result", "")

            except json.JSONDecodeError:
                continue

        if result["session_id"]:
            self.session_id = result["session_id"]

        return result


# ============================================================================
# 权限处理器
# ============================================================================

class PermissionState:
    """权限请求状态"""
    def __init__(self, tool_name: str, tool_input: dict, request_id: str):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.request_id = request_id
        self.future: Optional[asyncio.Future] = None
        self.resolved = False
        self.created_at = __import__('time').time()


class PermissionHandler:
    """
    权限确认双向处理器

    支持从两个渠道获取确认：
    1. 飞书群聊卡片交互
    2. Terminal CLI 直接输入

    使用 Future 实现异步等待，确保 PTY 模式下能阻塞等待确认。
    """

    def __init__(
        self,
        bridge_url: str = None,
        chat_id: str = None,
        terminal_id: str = None,
        on_cli_prompt: Callable[[str, dict], None] = None,
    ):
        self.bridge_url = bridge_url
        self.chat_id = chat_id
        self.terminal_id = terminal_id
        self.on_cli_prompt = on_cli_prompt

        # 当前待处理的权限请求
        self._current_request: Optional[PermissionState] = None
        self._lock = asyncio.Lock()

    def detect_permission_request(self, output: str) -> Optional[dict]:
        """检测权限请求"""
        for pattern in PERMISSION_PATTERNS:
            match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
            if match:
                tool_name = match.group(1)
                tool_input = {}
                input_match = re.search(r"input:\s*(.+?)(?:\n|$)", output, re.DOTALL)
                if input_match:
                    try:
                        tool_input = json.loads(input_match.group(1))
                    except json.JSONDecodeError:
                        tool_input = {"raw": input_match.group(1)}

                return {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "raw_output": output,
                }

        return None

    async def request_confirmation(
        self,
        tool_name: str,
        tool_input: dict,
        timeout: float = 300.0,
    ) -> bool:
        """
        请求权限确认（阻塞等待）

        同时向飞书和 CLI 发送确认请求，谁先响应就使用谁的结果。

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数
            timeout: 超时时间（秒）

        Returns:
            bool: True 表示允许，False 表示拒绝
        """
        async with self._lock:
            # 生成唯一请求 ID
            request_id = f"{self.terminal_id}:{tool_name}:{__import__('time').time()}"

            # 创建权限状态
            self._current_request = PermissionState(
                tool_name=tool_name,
                tool_input=tool_input,
                request_id=request_id,
            )
            self._current_request.future = asyncio.Future()

        try:
            # 发送飞书确认请求（异步，不等待）
            asyncio.create_task(
                self._send_feishu_permission_request(tool_name, tool_input, request_id)
            )

            # 触发 CLI 提示回调
            if self.on_cli_prompt:
                self.on_cli_prompt(tool_name, tool_input)

            logger.info(f"等待权限确认: {tool_name} (timeout={timeout}s)")

            # 等待确认结果
            result = await asyncio.wait_for(
                self._current_request.future,
                timeout=timeout
            )

            logger.info(f"权限确认结果: {tool_name} -> {'approved' if result else 'denied'}")
            return result

        except asyncio.TimeoutError:
            logger.warning(f"权限确认超时: {tool_name}")
            return False
        except asyncio.CancelledError:
            logger.info(f"权限确认被取消: {tool_name}")
            return False
        finally:
            async with self._lock:
                self._current_request = None

    async def _send_feishu_permission_request(
        self,
        tool_name: str,
        tool_input: dict,
        request_id: str,
    ):
        """发送飞书权限请求"""
        if not self.bridge_url or not self.chat_id:
            return

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chat_id": self.chat_id,
                    "terminal_id": self.terminal_id,
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }

                async with session.post(
                    f"{self.bridge_url}/permission/request",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"发送飞书权限请求失败: HTTP {resp.status}")

        except Exception as e:
            logger.debug(f"发送飞书权限请求异常: {e}")

    def resolve_permission(self, approved: bool, request_id: str = None):
        """
        解析权限确认结果（来自飞书或 CLI）

        Args:
            approved: 是否允许
            request_id: 可选的请求 ID，用于匹配特定请求
        """
        if self._current_request and not self._current_request.future.done():
            # 如果指定了 request_id，检查是否匹配
            if request_id and request_id != self._current_request.request_id:
                logger.debug(f"权限请求 ID 不匹配: {request_id} != {self._current_request.request_id}")
                return

            self._current_request.future.set_result(approved)
            self._current_request.resolved = True
            logger.info(f"权限确认已解析: approved={approved}")
        else:
            logger.debug(f"没有待处理的权限请求或已完成")

    def has_pending_request(self) -> bool:
        """检查是否有待处理的权限请求"""
        return (
            self._current_request is not None
            and not self._current_request.future.done()
        )

    def get_current_tool_name(self) -> Optional[str]:
        """获取当前待确认的工具名称"""
        if self._current_request:
            return self._current_request.tool_name
        return None


# ============================================================================
# 同步处理器
# ============================================================================

class SyncHandler:
    """
    飞书同步处理器
    """

    def __init__(
        self,
        bridge_url: str = None,
        chat_id: str = None,
        mode: str = "notify",
    ):
        self.bridge_url = bridge_url
        self.chat_id = chat_id
        self.mode = mode

        self._notify_events = {
            NativeEventType.PERMISSION_REQUEST,
            NativeEventType.COMPLETE,
            NativeEventType.ERROR,
        }

    async def sync_event(self, event: NativeEvent):
        """同步事件到飞书"""
        if not self.bridge_url or not self.chat_id:
            return

        if self.mode == "notify" and event.event_type not in self._notify_events:
            return

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chat_id": self.chat_id,
                    "event": event.to_dict(),
                }

                async with session.post(
                    f"{self.bridge_url}/terminal/sync",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    pass

        except Exception as e:
            logger.debug(f"同步事件失败: {e}")


# ============================================================================
# 统一的原生客户端
# ============================================================================

class NativeClaudeClient:
    """
    统一的原生 Claude CLI 客户端
    """

    def __init__(
        self,
        session_id: str = None,
        working_dir: str = None,
        mode: str = "print",
        sync_mode: str = "notify",
        bridge_url: str = None,
        chat_id: str = None,
        terminal_id: str = None,
        on_event: Callable[[NativeEvent], None] = None,
        raw_pty: bool = False,
    ):
        self.session_id = session_id
        self.working_dir = working_dir or os.getcwd()
        self.mode = mode
        self.sync_mode = sync_mode
        self.bridge_url = bridge_url
        self.chat_id = chat_id
        self.terminal_id = terminal_id
        self.on_event = on_event
        self.raw_pty = raw_pty

        self._pty_client: Optional[NativeClaudePTYClient] = None
        self._print_client: Optional[NativeClaudePrintClient] = None

        # 创建权限处理器，传入 terminal_id 用于请求 ID 生成
        self._permission_handler = PermissionHandler(
            bridge_url=bridge_url,
            chat_id=chat_id,
            terminal_id=terminal_id,
            on_cli_prompt=self._on_cli_permission_prompt,
        )

        self._sync_handler = SyncHandler(
            bridge_url=bridge_url,
            chat_id=chat_id,
            mode=sync_mode,
        )

        self._running = False

    async def start(self):
        """启动客户端"""
        if self.mode == "pty":
            self._pty_client = NativeClaudePTYClient(
                session_id=self.session_id,
                working_dir=self.working_dir,
                on_output=self._handle_pty_output,
                raw_mode=self.raw_pty,
                permission_handler=self._permission_handler,
            )
            await self._pty_client.start()
        else:
            self._print_client = NativeClaudePrintClient(
                session_id=self.session_id,
                working_dir=self.working_dir,
            )

        self._running = True
        logger.info(f"NativeClaudeClient 已启动 (mode={self.mode})")

    async def stop(self):
        """停止客户端"""
        self._running = False

        if self._pty_client:
            await self._pty_client.stop()
            self._pty_client = None

        self._print_client = None
        logger.info("NativeClaudeClient 已停止")

    def _handle_pty_output(self, output: str):
        """处理 PTY 输出（仅转发，权限处理由 PTY 客户端完成）"""
        self._emit_event(NativeEvent(
            event_type=NativeEventType.RAW_OUTPUT,
            data={"output": output},
        ))

    def _on_cli_permission_prompt(self, tool_name: str, tool_input: dict):
        """CLI 权限提示回调"""
        self._emit_event(NativeEvent(
            event_type=NativeEventType.PERMISSION_REQUEST,
            data={
                "tool_name": tool_name,
                "tool_input": tool_input,
            },
        ))

    def _emit_event(self, event: NativeEvent):
        """发送事件"""
        if self.on_event:
            self.on_event(event)

        asyncio.create_task(self._sync_handler.sync_event(event))

    async def chat(self, message: str) -> dict:
        """发送消息"""
        if self.mode == "pty":
            if self._pty_client:
                self._pty_client.write(message + "\n")
                return {"status": "sent"}
            return {"status": "error", "error": "PTY client not initialized"}
        else:
            if self._print_client:
                result = await self._print_client.chat(message)

                if result.get("session_id"):
                    self.session_id = result["session_id"]

                return result
            return {"status": "error", "error": "Print client not initialized"}

    async def chat_stream(self, message: str) -> AsyncGenerator[NativeEvent, None]:
        """发送消息（流式模式）"""
        if self.mode == "pty":
            if self._pty_client:
                self._pty_client.write(message + "\n")
                yield NativeEvent(
                    event_type=NativeEventType.STATUS,
                    data={"text": "消息已发送"},
                )
            return
        else:
            if not self._print_client:
                yield NativeEvent(
                    event_type=NativeEventType.ERROR,
                    data={"message": "Print client not initialized"},
                )
                return

            yield NativeEvent(
                event_type=NativeEventType.STATUS,
                data={"text": "正在处理..."},
            )

            result = await self._print_client.chat(message)

            if result.get("session_id"):
                self.session_id = result["session_id"]

            for raw_event in result.get("raw_events", []):
                event_type = raw_event.get("type")

                if event_type == "assistant":
                    msg = raw_event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            yield NativeEvent(
                                event_type=NativeEventType.CONTENT,
                                data={"text": block.get("text", "")},
                            )

                        elif block.get("type") == "tool_use":
                            yield NativeEvent(
                                event_type=NativeEventType.TOOL_CALL,
                                data={
                                    "name": block.get("name", ""),
                                    "input": block.get("input", {}),
                                },
                            )

                elif event_type == "result":
                    yield NativeEvent(
                        event_type=NativeEventType.COMPLETE,
                        data={
                            "session_id": raw_event.get("session_id", ""),
                            "content": raw_event.get("result", ""),
                            "cost": raw_event.get("total_cost_usd", 0),
                        },
                    )

            if not any(e.get("type") == "result" for e in result.get("raw_events", [])):
                yield NativeEvent(
                    event_type=NativeEventType.COMPLETE,
                    data={
                        "session_id": self.session_id or "",
                        "content": result.get("response", ""),
                    },
                )

    def write(self, data: str):
        """写入数据（PTY 模式）"""
        if self._pty_client:
            self._pty_client.write(data)

    def resolve_permission(self, approved: bool, request_id: str = None):
        """
        解析权限确认结果（来自飞书）

        Args:
            approved: 是否允许
            request_id: 可选的请求 ID，用于匹配特定请求
        """
        # 通知权限处理器，如果有等待中的请求会被解析
        # PTY 客户端会在 request_confirmation() 返回后自动注入 y/n
        self._permission_handler.resolve_permission(approved, request_id)

    def has_pending_permission(self) -> bool:
        """检查是否有待处理的权限请求"""
        return self._permission_handler.has_pending_request()