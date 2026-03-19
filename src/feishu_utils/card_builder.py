"""
飞书卡片消息构建器

提供类型安全的卡片 JSON 构建工具
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class CardElement:
    """卡片元素基类"""
    tag: str = field(default="", init=False)

    def to_dict(self) -> dict:
        return {"tag": self.tag}


@dataclass
class DivElement(CardElement):
    """文本块元素"""
    text: str
    text_type: str = "lark_md"  # lark_md 或 plain_text

    def __post_init__(self):
        self.tag = "div"

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "text": {
                "tag": self.text_type,
                "content": self.text
            }
        }


@dataclass
class ActionElement(CardElement):
    """操作区域元素（按钮等）"""
    actions: List[Dict[str, Any]]

    def __post_init__(self):
        self.tag = "action"

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "actions": self.actions
        }


@dataclass
class DividerElement(CardElement):
    """分割线元素"""

    def __post_init__(self):
        self.tag = "hr"


@dataclass
class NoteElement(CardElement):
    """备注元素（灰色小字）"""
    text: str

    def __post_init__(self):
        self.tag = "note"

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "elements": [
                {
                    "tag": "plain_text",
                    "content": self.text
                }
            ]
        }


@dataclass
class CardConfig:
    """卡片配置"""
    wide_screen_mode: bool = True
    enable_forward: bool = True

    def to_dict(self) -> dict:
        return {
            "wide_screen_mode": self.wide_screen_mode,
            "enable_forward": self.enable_forward
        }


@dataclass
class CardHeader:
    """卡片标题"""
    title: str
    template: str = ""  # 可选颜色主题

    def to_dict(self) -> dict:
        result = {
            "title": {
                "tag": "plain_text",
                "content": self.title
            }
        }
        if self.template:
            result["template"] = self.template
        return result


class CardBuilder:
    """
    卡片消息构建器

    使用示例：
        card = (CardBuilder()
            .set_header("🤖 Claude", "blue")
            .add_div("回复内容")
            .build())
    """

    def __init__(self):
        self._header: Optional[CardHeader] = None
        self._config: CardConfig = CardConfig()
        self._elements: List[CardElement] = []

    def set_header(self, title: str, template: str = "") -> "CardBuilder":
        """设置卡片标题"""
        self._header = CardHeader(title=title, template=template)
        return self

    def set_config(self, wide_screen_mode: bool = True, enable_forward: bool = True) -> "CardBuilder":
        """设置卡片配置"""
        self._config = CardConfig(wide_screen_mode=wide_screen_mode, enable_forward=enable_forward)
        return self

    def add_div(self, text: str, text_type: str = "lark_md") -> "CardBuilder":
        """添加文本块"""
        self._elements.append(DivElement(text=text, text_type=text_type))
        return self

    def add_divider(self) -> "CardBuilder":
        """添加分割线"""
        self._elements.append(DividerElement(tag="hr"))
        return self

    def add_note(self, text: str) -> "CardBuilder":
        """添加备注（灰色小字）"""
        self._elements.append(NoteElement(text=text))
        return self

    def add_action(self, actions: List[Dict[str, Any]]) -> "CardBuilder":
        """添加操作区域"""
        self._elements.append(ActionElement(actions=actions))
        return self

    def add_button(
        self,
        text: str,
        value: Dict[str, Any],
        button_type: str = "default",
        url: Optional[str] = None
    ) -> "CardBuilder":
        """
        添加按钮

        Args:
            text: 按钮文字
            value: 按钮点击时回传的值
            button_type: 按钮样式 (default, primary, danger)
            url: 可选，点击后跳转的链接

        Returns:
            CardBuilder
        """
        button = {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": text
            },
            "type": button_type,
            "value": value
        }
        if url:
            button["url"] = url

        # 如果已有 action 元素，添加到其中；否则创建新的
        if self._elements and isinstance(self._elements[-1], ActionElement):
            self._elements[-1].actions.append(button)
        else:
            self._elements.append(ActionElement(actions=[button]))
        return self

    def build(self) -> dict:
        """
        构建卡片 JSON

        Returns:
            飞书卡片消息的 content 字段内容
        """
        content: Dict[str, Any] = {
            "config": self._config.to_dict()
        }

        if self._header:
            content["header"] = self._header.to_dict()

        if self._elements:
            content["elements"] = [elem.to_dict() for elem in self._elements]

        return content


def build_status_card(
    status: str,
    details: Optional[str] = None,
    icon: str = "⏳",
    header_template: str = "blue"
) -> dict:
    """构建执行状态卡片"""
    builder = CardBuilder()
    builder.set_header(f"{icon} {status}", header_template)

    if details:
        builder.add_div(details, "lark_md")

    return builder.build()


def build_permission_card(
    tool_name: str,
    tool_input: dict,
    chat_id: str,
) -> dict:
    """构建权限确认卡片（带按钮）"""
    import json

    # 格式化工具输入
    input_display = json.dumps(tool_input, ensure_ascii=False, indent=2)
    if len(input_display) > 500:
        input_display = input_display[:500] + "\n... (内容过长，已截断)"

    content = f"""**操作**: `{tool_name}`

**详情**:
```
{input_display}
```"""

    builder = CardBuilder()
    builder.set_header("🔒 权限确认", "red")
    builder.add_div(content, "lark_md")

    # 添加按钮
    approve_value = {
        "action": "permission_approve",
        "chat_id": chat_id
    }
    deny_value = {
        "action": "permission_deny",
        "chat_id": chat_id
    }

    builder.add_button("✅ 允许", approve_value, "primary")
    builder.add_button("❌ 拒绝", deny_value, "danger")

    builder.add_note("点击按钮快速确认，或回复 y/n")

    return builder.build()