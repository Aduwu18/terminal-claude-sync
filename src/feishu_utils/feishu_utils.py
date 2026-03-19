"""
飞书 API 工具函数

提供飞书开放平台 API 封装
"""
import datetime
import re
import requests
import json
import os
import logging

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

logger = logging.getLogger(__name__)

app_id = os.getenv('APP_ID')
app_secret = os.getenv('APP_SECRET')

assert app_id and app_secret, 'app_id and app_secret is required'


def get_tenant_access_token():
    """
    获取飞书的tenant_access_token
    """
    res = requests.post(
        url='https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal',
        json={"app_id": app_id, "app_secret": app_secret}
    ).json()
    return res['app_access_token']


def get_headers(access_token):
    return {'Authorization': 'Bearer ' + access_token}


def reply_message(message_id, text, access_token=None):
    if access_token is None:
        access_token = get_tenant_access_token()

    url = 'https://open.feishu.cn/open-apis/im/v1/messages/{}/reply'.format(message_id)

    ret_data = {'text': text}

    body = {
        "msg_type": "text",
        "content": json.dumps(ret_data, ensure_ascii=False, indent=4),
        'uuid': str(datetime.datetime.now().timestamp())
    }
    res = requests.post(url, headers=get_headers(access_token), json=body).json()
    return res


def send_message(receive_id, text, access_token=None):
    if access_token is None:
        access_token = get_tenant_access_token()

    url = 'https://open.feishu.cn/open-apis/im/v1/messages'
    param = {'receive_id_type': 'chat_id'}

    ret_data = {'text': text}

    body = {
        'receive_id': receive_id,
        "msg_type": "text",
        "content": json.dumps(ret_data, ensure_ascii=False, indent=4),
        'uuid': str(datetime.datetime.now().timestamp())
    }
    res = requests.post(url, headers=get_headers(access_token), json=body, params=param).json()
    return res


def send_markdown_message(receive_id: str, text: str, title: str = "", access_token=None) -> dict:
    """
    发送 Markdown 格式消息（使用卡片渲染）
    """
    from src.feishu_utils.card_builder import CardBuilder

    if access_token is None:
        access_token = get_tenant_access_token()

    builder = CardBuilder()
    if title:
        builder.set_header(title, "blue")
    builder.add_div(text, "lark_md")

    return send_card_message(receive_id, builder.build(), access_token)


def create_group_chat(user_open_id: str, name: str, access_token=None) -> str:
    """
    创建群聊会话

    需要飞书应用开通 im:chat:write 权限

    Args:
        user_open_id: 用户 open_id
        name: 群聊名称

    Returns:
        chat_id: 新创建的群聊 chat_id

    Raises:
        Exception: 创建失败时抛出异常
    """
    if access_token is None:
        access_token = get_tenant_access_token()

    url = 'https://open.feishu.cn/open-apis/im/v1/chats'
    body = {
        "chat_mode": "group",
        "name": name,
        "user_id_list": [user_open_id]
    }
    res = requests.post(url, headers=get_headers(access_token), json=body).json()
    if res['code'] != 0:
        raise Exception(f'创建群聊失败: {json.dumps(res, ensure_ascii=False)}')
    return res['data']['chat_id']


def disband_group_chat(chat_id: str, access_token=None) -> bool:
    """
    解散群聊

    需要飞书应用开通 im:chat:write 权限

    Args:
        chat_id: 群聊 ID
        access_token: 访问令牌（可选）

    Returns:
        bool: True 表示解散成功，False 表示失败
    """
    if access_token is None:
        access_token = get_tenant_access_token()

    url = f'https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}/disband'
    res = requests.post(url, headers=get_headers(access_token)).json()
    if res['code'] != 0:
        # 群聊不存在或已解散，视为成功
        if res['code'] == 230001:
            logger.warning(f'群聊 {chat_id} 不存在或已解散')
            return True
        raise Exception(f'解散群聊失败: {json.dumps(res, ensure_ascii=False)}')
    return True


def get_chat_info(chat_id: str, access_token=None) -> dict:
    """
    获取群聊信息

    Args:
        chat_id: 群聊 ID
        access_token: 访问令牌（可选）

    Returns:
        dict: 群聊信息，如果群聊不存在返回 None
    """
    if access_token is None:
        access_token = get_tenant_access_token()

    url = f'https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}'
    res = requests.get(url, headers=get_headers(access_token)).json()
    if res['code'] != 0:
        if res['code'] == 230001:
            return None
        raise Exception(f'获取群聊信息失败: {json.dumps(res, ensure_ascii=False)}')
    return res['data']


def send_card_message(receive_id: str, card_content: dict, access_token=None) -> dict:
    """
    发送卡片消息
    """
    if access_token is None:
        access_token = get_tenant_access_token()

    url = 'https://open.feishu.cn/open-apis/im/v1/messages'
    param = {'receive_id_type': 'chat_id'}

    body = {
        'receive_id': receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content, ensure_ascii=False),
        'uuid': str(datetime.datetime.now().timestamp())
    }

    res = requests.post(url, headers=get_headers(access_token), json=body, params=param)
    return res.json()


def update_card_message(message_id: str, card_content: dict, access_token=None) -> dict:
    """
    更新已发送的卡片消息
    """
    if access_token is None:
        access_token = get_tenant_access_token()

    url = f'https://open.feishu.cn/open-apis/im/v1/messages/{message_id}'
    body = {
        "msg_type": "interactive",
        "content": json.dumps(card_content, ensure_ascii=False)
    }
    res = requests.patch(url, headers=get_headers(access_token), json=body)
    return res.json()


# 消息分块常量
FEISHU_TEXT_MAX_LENGTH = 30000
FEISHU_CARD_MD_MAX_LENGTH = 10000


def split_long_message(text: str, max_length: int = FEISHU_CARD_MD_MAX_LENGTH) -> list:
    """
    将长消息分割为多个片段
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        search_start = max(0, max_length - 500)
        search_end = min(max_length, len(remaining))
        search_text = remaining[search_start:search_end]

        best_split = -1

        # 优先在双换行分割
        double_newline = search_text.rfind('\n\n')
        if double_newline != -1:
            best_split = search_start + double_newline + 2
        else:
            single_newline = search_text.rfind('\n')
            if single_newline != -1:
                best_split = search_start + single_newline + 1
            else:
                space = search_text.rfind(' ')
                if space != -1:
                    best_split = search_start + space + 1
                else:
                    best_split = max_length

        if best_split > max_length:
            best_split = max_length

        chunk = remaining[:best_split].strip()
        if chunk:
            chunks.append(chunk)

        if best_split >= len(remaining):
            break
        remaining = remaining[best_split:].strip()

    return chunks


def send_long_message(
    receive_id: str,
    text: str,
    title: str = "",
    use_card: bool = True,
    access_token=None
) -> list:
    """
    发送长消息，自动分块
    """
    from src.feishu_utils.card_builder import CardBuilder

    max_length = FEISHU_CARD_MD_MAX_LENGTH if use_card else FEISHU_TEXT_MAX_LENGTH
    chunks = split_long_message(text, max_length)

    responses = []
    total = len(chunks)

    for i, chunk in enumerate(chunks):
        if use_card:
            builder = CardBuilder()

            if i == 0 and title:
                builder.set_header(title, "blue")

            if total > 1:
                chunk_text = f"{chunk}\n\n---\n📄 {i + 1}/{total}"
            else:
                chunk_text = chunk

            builder.add_div(chunk_text, "lark_md")
            card = builder.build()

            res = send_card_message(receive_id, card, access_token)
        else:
            if total > 1:
                chunk_text = f"{chunk}\n\n---\n📄 {i + 1}/{total}"
            else:
                chunk_text = chunk
            res = send_message(receive_id, chunk_text, access_token)

        responses.append(res)

    return responses


def send_terminal_status_card(
    chat_id: str,
    status: str,
    details: dict,
    access_token=None
) -> dict:
    """
    发送终端状态卡片
    """
    from src.feishu_utils.card_builder import CardBuilder

    if access_token is None:
        access_token = get_tenant_access_token()

    # 状态配置
    status_config = {
        "started": {"icon": "🚀", "template": "green", "text": "终端已启动"},
        "running": {"icon": "⏳", "template": "blue", "text": "正在执行"},
        "idle": {"icon": "💤", "template": "grey", "text": "等待输入"},
        "stopped": {"icon": "🛑", "template": "red", "text": "终端已停止"},
        "error": {"icon": "❌", "template": "red", "text": "发生错误"},
    }

    config = status_config.get(status, {"icon": "📌", "template": "blue", "text": status})

    builder = CardBuilder()
    builder.set_header(f"{config['icon']} {config['text']}", config['template'])

    # 构建内容
    content_lines = [
        f"**终端**: `{details.get('terminal_id', 'unknown')}`",
        f"**主机**: `{details.get('hostname', 'unknown')}`",
    ]

    if details.get('message'):
        content_lines.append(f"**状态**: {details['message']}")

    if details.get('session_id'):
        content_lines.append(f"**会话**: `{details['session_id'][:8]}...`")

    builder.add_div("\n".join(content_lines), "lark_md")

    # 添加时间戳
    builder.add_note(f"更新时间: {datetime.datetime.now().strftime('%H:%M:%S')}")

    return send_card_message(chat_id, builder.build(), access_token)