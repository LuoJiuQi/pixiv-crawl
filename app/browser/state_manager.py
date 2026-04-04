"""
这个文件只做一件事：管理登录状态文件。

所谓登录状态文件，就是 Playwright 保存的 `storage_state.json`。
它能帮助程序在下次运行时复用上一次的登录结果。
"""

import json
from pathlib import Path
from typing import Any

from app.core.config import settings


class StateManager:
    """
    统一管理登录状态文件路径和相关操作。

    为什么要单独做一个类？
    - 浏览器模块要知道状态文件在不在
    - 登录模块要保存状态文件
    - 主流程可能要删除失效状态

    把它们集中在这里，后续维护更方便。
    """

    def __init__(self, state_file: str | None = None):
        """
        初始化状态文件路径。

        如果外部传了路径，就优先用外部传入的值。
        否则就使用配置文件里的默认路径。
        """
        self.state_file = Path(state_file or settings.state_file)

    def ensure_state_dir(self) -> None:
        """
        确保状态文件所在目录已经存在。

        参数说明：
        - `parents=True`：如果上级目录不存在，就一起创建
        - `exist_ok=True`：目录已存在时不报错
        """
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def state_exists(self) -> bool:
        """
        判断登录状态文件是否存在，而且它确实是一个文件。

        常见分支逻辑：
        - 有状态文件：尝试复用登录态
        - 没有状态文件：重新登录
        """
        return self.state_file.exists() and self.state_file.is_file()

    def get_state_file(self) -> str:
        """
        返回字符串形式的状态文件路径。

        有些第三方库更喜欢接收字符串路径，而不是 `Path` 对象。
        """
        return str(self.state_file)

    def save_state_data(self, state_data: dict[str, Any]) -> None:
        """
        把登录状态数据保存成“更容易阅读”的 JSON 文件。

        Playwright 默认直接落盘时，文件通常会是一整行，
        调试 cookies 或 localStorage 时会比较费眼。
        所以这里统一改成：
        - 缩进 2 空格
        - 保留中文
        - 末尾自动换行
        """
        self.ensure_state_dir()
        formatted_json = json.dumps(state_data, ensure_ascii=False, indent=2)
        self.state_file.write_text(formatted_json + "\n", encoding="utf-8")

    def delete_state(self) -> None:
        """
        删除本地保存的登录状态文件。

        常见场景：
        - 状态文件还在，但内容已经失效
        - 程序检测到登录态过期
        - 这时就删除旧文件，强制重新登录
        """
        if self.state_exists():
            self.state_file.unlink()
