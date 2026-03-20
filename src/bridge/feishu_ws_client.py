"""
飞书 WebSocket 长连接客户端

接收飞书事件：消息、卡片交互、群聊解散等

使用 lark-oapi SDK 的 WebSocket 长连接模式，无需公网 IP 即可接收飞书事件。
"""
import logging
import os
import threading
from typing import Callable, Optional, Any

import lark_oapi as lark

logger = logging.getLogger(__name__)


class FeishuWebSocketClient:
    """
    飞书 WebSocket 长连接客户端

    通过 WebSocket 连接到飞书云端，接收实时事件推送。
    适用于内网环境，无需配置公网 webhook。

    Usage:
        client = FeishuWebSocketClient(
            app_id="...",
            app_secret="...",
            on_message=handle_message,
            on_card_action=handle_card,
        )
        client.start()  # 启动后台线程
        # ...
        client.stop()   # 停止连接
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message: Optional[Callable] = None,
        on_card_action: Optional[Callable] = None,
        on_chat_disbanded: Optional[Callable] = None,
        on_member_withdrawn: Optional[Callable] = None,
    ):
        """
        初始化 WebSocket 客户端

        Args:
            app_id: 飞书应用 ID
            app_secret: 飞书应用 Secret
            on_message: 消息事件回调 (async callable)
            on_card_action: 卡片交互回调 (async callable)
            on_chat_disbanded: 群聊解散回调 (async callable)
            on_member_withdrawn: 成员退出回调 (async callable)
        """
        self.app_id = app_id
        self.app_secret = app_secret

        # 事件回调
        self._on_message = on_message
        self._on_card_action = on_card_action
        self._on_chat_disbanded = on_chat_disbanded
        self._on_member_withdrawn = on_member_withdrawn

        # 内部状态
        self._client: Optional[lark.ws.Client] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _create_event_handler(self) -> lark.EventDispatcherHandler:
        """
        创建事件处理器

        Returns:
            lark.EventDispatcherHandler: 事件分发器
        """
        builder = lark.EventDispatcherHandler.builder("", "")

        # 注册消息接收事件
        if self._on_message:
            builder = builder.register_p2_im_message_receive_v1(
                self._wrap_sync(self._on_message)
            )

        # 注册卡片交互事件
        if self._on_card_action:
            builder = builder.register_p2_card_action_trigger(
                self._wrap_sync(self._on_card_action)
            )

        # 注册群聊解散事件
        if self._on_chat_disbanded:
            builder = builder.register_p2_im_chat_disbanded_v1(
                self._wrap_sync(self._on_chat_disbanded)
            )

        # 注册成员退出事件
        if self._on_member_withdrawn:
            builder = builder.register_p2_im_chat_member_user_withdrawn_v1(
                self._wrap_sync(self._on_member_withdrawn)
            )

        return builder.build()

    def _wrap_sync(self, async_handler: Callable) -> Callable:
        """
        将异步处理器包装为同步函数（lark SDK 的要求）

        lark-oapi SDK 的事件处理器需要是同步函数，
        但我们的业务逻辑是异步的，需要包装。
        """
        import asyncio

        def wrapper(event):
            try:
                # 尝试获取现有事件循环
                try:
                    loop = asyncio.get_running_loop()
                    # 如果已在异步上下文中，创建任务
                    asyncio.create_task(async_handler(event))
                except RuntimeError:
                    # 没有运行中的事件循环，创建新的
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(async_handler(event))
                    finally:
                        loop.close()
            except Exception as e:
                logger.error(f"Event handler error: {e}", exc_info=True)

        return wrapper

    def start(self):
        """启动 WebSocket 客户端（在后台线程运行）"""
        if self._running:
            logger.warning("FeishuWebSocketClient already running")
            return

        self._running = True

        # 创建 WebSocket 客户端
        self._client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=self._create_event_handler(),
            log_level=lark.LogLevel.DEBUG
            if logger.isEnabledFor(logging.DEBUG)
            else lark.LogLevel.INFO,
        )

        # 在后台线程启动
        self._thread = threading.Thread(
            target=self._run_client, daemon=True, name="FeishuWS"
        )
        self._thread.start()

        logger.info("Feishu WebSocket client started")

    def _run_client(self):
        """运行 WebSocket 客户端（在后台线程中调用）"""
        try:
            logger.info("Feishu WebSocket connecting...")
            # lark.ws.Client.start() 是阻塞调用
            self._client.start()
        except Exception as e:
            logger.error(f"Feishu WebSocket error: {e}", exc_info=True)
            self._running = False

    def stop(self):
        """停止 WebSocket 客户端"""
        if not self._running:
            return

        self._running = False

        # lark.ws.Client 没有显式的 stop 方法
        # 由于线程是 daemon 线程，进程退出时会自动终止
        logger.info("Feishu WebSocket client stopping")

        # 等待线程结束（最多 5 秒）
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("Feishu WebSocket thread did not stop gracefully")

    @property
    def is_running(self) -> bool:
        """检查客户端是否正在运行"""
        return self._running and self._thread is not None and self._thread.is_alive()


def create_feishu_ws_client_from_env(
    on_message: Optional[Callable] = None,
    on_card_action: Optional[Callable] = None,
    on_chat_disbanded: Optional[Callable] = None,
    on_member_withdrawn: Optional[Callable] = None,
) -> Optional[FeishuWebSocketClient]:
    """
    从环境变量创建 Feishu WebSocket 客户端

    Returns:
        FeishuWebSocketClient or None (如果环境变量未配置)
    """
    app_id = os.getenv("APP_ID")
    app_secret = os.getenv("APP_SECRET")

    if not app_id or not app_secret:
        logger.warning("APP_ID or APP_SECRET not set, Feishu WebSocket client disabled")
        return None

    return FeishuWebSocketClient(
        app_id=app_id,
        app_secret=app_secret,
        on_message=on_message,
        on_card_action=on_card_action,
        on_chat_disbanded=on_chat_disbanded,
        on_member_withdrawn=on_member_withdrawn,
    )