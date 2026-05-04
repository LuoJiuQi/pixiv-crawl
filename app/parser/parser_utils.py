"""
解析 Pixiv 页面时可复用的底层工具函数。

这些函数不关心“字段业务语义”，只负责：
- HTML / meta 正则提取
- JSON 安全解析
- 嵌套结构递归查找
"""

import json
import re
from html import unescape
from typing import Any


def extract_meta_value(html: str, name: str, attr: str = "property") -> str:
    patterns = [
        rf'<meta[^>]+{attr}="{re.escape(name)}"[^>]+content="(.*?)"',
        rf"<meta[^>]+{attr}='{re.escape(name)}'[^>]+content='(.*?)'",
        rf'<meta[^>]+content="(.*?)"[^>]+{attr}="{re.escape(name)}"',
        rf"<meta[^>]+content='(.*?)'[^>]+{attr}='{re.escape(name)}'",
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)
        if match:
            return unescape(match.group(1)).strip()

    return ""


def extract_first_match(text: str, patterns: list[str], flags: int = re.I | re.S) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            return unescape(value).strip()
    return ""


def extract_title_from_html(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if match:
        return unescape(match.group(1)).strip()
    return ""


def safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def walk_find_keys(
    obj: Any,
    target_keys: set[str],
    results: list[tuple[str, Any]],
    path: str = "",
) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key
            if key in target_keys:
                results.append((current_path, value))
            walk_find_keys(value, target_keys, results, current_path)
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            current_path = f"{path}[{index}]"
            walk_find_keys(item, target_keys, results, current_path)


def find_first_value_by_keys(obj: Any, target_keys: set[str]) -> str:
    results: list[tuple[str, Any]] = []
    walk_find_keys(obj, target_keys, results)

    for _, value in results:
        text = str(value).strip()
        if text:
            return text
    return ""
