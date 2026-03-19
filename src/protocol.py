"""
通信协议定义

简化的协议，仅用于 Terminal CLI 与 Bridge 之间的通信
"""
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum
import json
import uuid
import time


class StreamEventType(str, Enum):
    """流式事件类型枚举"""
    HEARTBEAT = "heartbeat"      # 心跳
    STATUS = "status"            # 状态更新
    TOOL_CALL = "tool_call"      # 工具调用
    CONTENT = "content"          # 内容片段
    COMPLETE = "complete"        # 完成
    ERROR = "error"              # 错误


@dataclass
class StreamEvent:
    """流式事件"""
    event_type: StreamEventType
    data: dict
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> 'StreamEvent':
        return cls(
            event_type=StreamEventType(data["event_type"]),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", time.time()),
        )

    # 便捷工厂方法
    @classmethod
    def heartbeat(cls) -> 'StreamEvent':
        return cls(event_type=StreamEventType.HEARTBEAT, data={})

    @classmethod
    def status(cls, text: str, details: str = None) -> 'StreamEvent':
        data = {"text": text}
        if details:
            data["details"] = details
        return cls(event_type=StreamEventType.STATUS, data=data)

    @classmethod
    def tool_call(cls, name: str, input: dict) -> 'StreamEvent':
        return cls(event_type=StreamEventType.TOOL_CALL, data={"name": name, "input": input})

    @classmethod
    def content(cls, text: str) -> 'StreamEvent':
        return cls(event_type=StreamEventType.CONTENT, data={"text": text})

    @classmethod
    def complete(cls, session_id: str, content: str = "") -> 'StreamEvent':
        return cls(event_type=StreamEventType.COMPLETE, data={"session_id": session_id, "content": content})

    @classmethod
    def error(cls, message: str, error_type: str = None) -> 'StreamEvent':
        data = {"message": message}
        if error_type:
            data["error_type"] = error_type
        return cls(event_type=StreamEventType.ERROR, data=data)