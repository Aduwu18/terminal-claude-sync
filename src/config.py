"""
配置管理模块

支持从 config.yaml 加载配置，支持环境变量覆盖
"""
import os
import yaml
from pathlib import Path
from typing import Optional, List


_config: Optional[dict] = None


def get_config_path() -> Path:
    """获取配置文件路径"""
    return Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    """加载配置文件（带缓存）"""
    global _config
    if _config is None:
        config_path = get_config_path()
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                _config = yaml.safe_load(f) or {}
        else:
            _config = {}
    return _config


def reload_config() -> dict:
    """重新加载配置文件"""
    global _config
    _config = None
    return load_config()


def get_terminal_session_config() -> dict:
    """
    获取 Terminal 会话配置

    Returns:
        dict: {
            "enabled": bool,
            "auto_create_chat": bool,
            "auto_disband_on_exit": bool,
            "user_open_id": str,
            "group_name_prefix": str,
            "data_dir": str
        }
    """
    config = load_config()
    terminal_config = config.get("terminal_session", {})

    # 支持环境变量覆盖 data_dir（适用于只读挂载的容器场景）
    data_dir = os.getenv("TERMINAL_DATA_DIR") or terminal_config.get("data_dir", "data")

    return {
        "enabled": terminal_config.get("enabled", True),
        "auto_create_chat": terminal_config.get("auto_create_chat", True),
        "auto_disband_on_exit": terminal_config.get("auto_disband_on_exit", True),
        "user_open_id": os.getenv("FEISHU_USER_OPEN_ID") or terminal_config.get("user_open_id", ""),
        "group_name_prefix": terminal_config.get("group_name_prefix", "💻 Terminal"),
        "data_dir": data_dir,
    }


def get_bridge_config() -> dict:
    """
    获取 Bridge 服务配置

    Returns:
        dict: {"port": int, "host": str}
    """
    config = load_config()
    bridge_config = config.get("bridge", {})
    return {
        "port": bridge_config.get("port", 8081),
        "host": bridge_config.get("host", "0.0.0.0"),
    }


def get_permission_config() -> dict:
    """
    获取权限确认配置

    Returns:
        dict: {"dual_channel": bool, "cli_timeout": int, "feishu_timeout": int}
    """
    config = load_config()
    permission_config = config.get("permission", {})
    return {
        "dual_channel": permission_config.get("dual_channel", True),
        "cli_timeout": permission_config.get("cli_timeout", 60),
        "feishu_timeout": permission_config.get("feishu_timeout", 300),
    }