"""
Terminal 会话管理器

负责：
1. 创建 Terminal 会话（自动创建飞书群聊）
2. 存储会话信息
3. 解散会话
4. 会话持久化
"""
import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from src.feishu_utils.feishu_utils import (
    create_group_chat,
    disband_group_chat,
    get_chat_info,
    send_terminal_status_card,
    send_card_message,
)
from src.feishu_utils.card_builder import CardBuilder

logger = logging.getLogger(__name__)


@dataclass
class TerminalSession:
    """Terminal 会话数据"""
    terminal_id: str
    chat_id: str
    session_id: Optional[str]
    user_open_id: str
    created_at: str
    status: str
    message_count: int
    hostname: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'TerminalSession':
        return cls(
            terminal_id=data.get("terminal_id", ""),
            chat_id=data.get("chat_id", ""),
            session_id=data.get("session_id"),
            user_open_id=data.get("user_open_id", ""),
            created_at=data.get("created_at", ""),
            status=data.get("status", "idle"),
            message_count=data.get("message_count", 0),
            hostname=data.get("hostname", ""),
        )


class TerminalSessionManager:
    """
    Terminal 会话管理器
    """

    def __init__(
        self,
        storage_path: str = "data/terminal_sessions.json",
        user_open_id: str = None,
        group_name_prefix: str = "💻 Terminal",
        auto_disband_on_exit: bool = True,
    ):
        self._storage_path = Path(storage_path)
        self._sessions: Dict[str, TerminalSession] = {}
        self._user_open_id = user_open_id
        self._group_name_prefix = group_name_prefix
        self._auto_disband_on_exit = auto_disband_on_exit
        self._lock = asyncio.Lock()

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_sessions()

    def _load_sessions(self):
        """从文件加载会话"""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for terminal_id, session_data in data.items():
                        self._sessions[terminal_id] = TerminalSession.from_dict(session_data)
                logger.info(f"已加载 {len(self._sessions)} 个 Terminal 会话")
            except Exception as e:
                logger.error(f"加载会话失败: {e}")

    def _save_sessions(self):
        """保存会话到文件"""
        try:
            data = {
                terminal_id: session.to_dict()
                for terminal_id, session in self._sessions.items()
            }
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存 {len(self._sessions)} 个 Terminal 会话")
        except Exception as e:
            logger.error(f"保存会话失败: {e}")

    @staticmethod
    def generate_terminal_id() -> str:
        """生成终端唯一标识"""
        hostname = socket.gethostname()
        timestamp = int(time.time())
        return f"{hostname}-{timestamp}"

    async def create_session(
        self,
        terminal_id: str,
        user_open_id: str = None,
        session_id: str = None,
    ) -> TerminalSession:
        """创建 Terminal 会话（自动创建飞书群聊）"""
        async with self._lock:
            if terminal_id in self._sessions:
                existing = self._sessions[terminal_id]
                chat_info = get_chat_info(existing.chat_id)
                if chat_info:
                    logger.info(f"会话已存在: {terminal_id}, chat_id: {existing.chat_id}")
                    return existing
                else:
                    del self._sessions[terminal_id]

            if user_open_id is None:
                user_open_id = self._user_open_id
            if not user_open_id:
                raise ValueError("需要提供 user_open_id")

            hostname = terminal_id.rsplit("-", 1)[0] if "-" in terminal_id else socket.gethostname()

            group_name = f"{self._group_name_prefix} {hostname}"
            chat_id = create_group_chat(user_open_id, group_name)
            logger.info(f"创建群聊成功: {group_name} ({chat_id})")

            session = TerminalSession(
                terminal_id=terminal_id,
                chat_id=chat_id,
                session_id=session_id,
                user_open_id=user_open_id,
                created_at=datetime.now().isoformat(),
                status="started",
                message_count=0,
                hostname=hostname,
            )

            self._sessions[terminal_id] = session
            self._save_sessions()

            await self.sync_status(terminal_id, "started", {
                "terminal_id": terminal_id,
                "hostname": hostname,
                "message": "终端已启动，等待输入...",
                "session_id": session_id,
            })

            return session

    async def restore_session(self, terminal_id: str) -> Optional[TerminalSession]:
        """恢复会话"""
        async with self._lock:
            if terminal_id not in self._sessions:
                return None

            session = self._sessions[terminal_id]

            chat_info = get_chat_info(session.chat_id)
            if not chat_info:
                logger.warning(f"群聊 {session.chat_id} 已不存在，删除会话")
                del self._sessions[terminal_id]
                self._save_sessions()
                return None

            session.status = "idle"
            self._save_sessions()

            logger.info(f"恢复会话: {terminal_id}, chat_id: {session.chat_id}")
            return session

    async def close_session(
        self,
        terminal_id: str,
        disband_chat: bool = None,
    ) -> bool:
        """关闭会话（解散群聊）"""
        async with self._lock:
            if terminal_id not in self._sessions:
                logger.warning(f"会话不存在: {terminal_id}")
                return False

            session = self._sessions[terminal_id]

            try:
                await self.sync_status(terminal_id, "stopped", {
                    "terminal_id": terminal_id,
                    "hostname": session.hostname,
                    "message": f"终端已关闭，共处理 {session.message_count} 条消息",
                })
            except Exception as e:
                logger.warning(f"发送停止状态卡片失败: {e}")

            if disband_chat is None:
                disband_chat = self._auto_disband_on_exit

            if disband_chat:
                try:
                    disband_group_chat(session.chat_id)
                    logger.info(f"解散群聊成功: {session.chat_id}")
                except Exception as e:
                    logger.error(f"解散群聊失败: {e}")

            del self._sessions[terminal_id]
            self._save_sessions()

            logger.info(f"关闭会话: {terminal_id}")
            return True

    async def sync_output(self, terminal_id: str, content: str) -> bool:
        """同步输出到群聊"""
        session = self._sessions.get(terminal_id)
        if not session:
            logger.warning(f"会话不存在: {terminal_id}")
            return False

        try:
            builder = CardBuilder()
            builder.add_div(content, "lark_md")
            send_card_message(session.chat_id, builder.build())

            session.message_count += 1
            self._save_sessions()

            return True
        except Exception as e:
            logger.error(f"同步输出失败: {e}")
            return False

    async def sync_status(
        self,
        terminal_id: str,
        status: str,
        details: dict,
    ) -> bool:
        """同步状态到群聊"""
        session = self._sessions.get(terminal_id)
        if not session:
            logger.warning(f"会话不存在: {terminal_id}")
            return False

        try:
            if "terminal_id" not in details:
                details["terminal_id"] = terminal_id
            if "hostname" not in details:
                details["hostname"] = session.hostname

            send_terminal_status_card(session.chat_id, status, details)

            session.status = status
            self._save_sessions()

            return True
        except Exception as e:
            logger.error(f"同步状态失败: {e}")
            return False

    def update_session_id(self, terminal_id: str, session_id: str):
        """更新 Claude 会话 ID"""
        if terminal_id in self._sessions:
            self._sessions[terminal_id].session_id = session_id
            self._save_sessions()

    def get_session(self, terminal_id: str) -> Optional[TerminalSession]:
        """获取会话信息"""
        return self._sessions.get(terminal_id)

    def get_chat_id(self, terminal_id: str) -> Optional[str]:
        """获取群聊 ID"""
        session = self._sessions.get(terminal_id)
        return session.chat_id if session else None

    def get_terminal_id(self, chat_id: str) -> Optional[str]:
        """通过群聊 ID 获取终端 ID"""
        for terminal_id, session in self._sessions.items():
            if session.chat_id == chat_id:
                return terminal_id
        return None

    def list_sessions(self) -> list:
        """列出所有会话"""
        return list(self._sessions.values())


# 全局单例
_session_manager: Optional[TerminalSessionManager] = None


def get_terminal_session_manager() -> TerminalSessionManager:
    """获取全局会话管理器单例"""
    global _session_manager
    if _session_manager is None:
        from src.config import get_terminal_session_config

        config = get_terminal_session_config()
        data_dir = config.get("data_dir", "data")
        storage_path = f"{data_dir}/terminal_sessions.json"
        _session_manager = TerminalSessionManager(
            storage_path=storage_path,
            user_open_id=config.get("user_open_id"),
            group_name_prefix=config.get("group_name_prefix", "💻 Terminal"),
            auto_disband_on_exit=config.get("auto_disband_on_exit", True),
        )
    return _session_manager


def init_terminal_session_manager(
    user_open_id: str = None,
    group_name_prefix: str = "💻 Terminal",
    auto_disband_on_exit: bool = True,
    storage_path: str = None,
) -> TerminalSessionManager:
    """初始化会话管理器"""
    global _session_manager
    if storage_path is None:
        storage_path = "data/terminal_sessions.json"
    _session_manager = TerminalSessionManager(
        storage_path=storage_path,
        user_open_id=user_open_id,
        group_name_prefix=group_name_prefix,
        auto_disband_on_exit=auto_disband_on_exit,
    )
    return _session_manager