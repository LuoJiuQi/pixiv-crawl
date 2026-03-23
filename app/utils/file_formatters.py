"""
这个文件提供“调试友好”的文件格式化工具。

目标不是做一个完美的 HTML 美化器，
而是把原本一整行挤在一起的 HTML / JSON
整理成“人眼能快速扫读”的版本，方便调试。
"""

import json
import re
from typing import Any


VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def pretty_json_text(data: Any) -> str:
    """
    把 Python 数据转成易读的 JSON 文本。
    """
    return json.dumps(data, ensure_ascii=False, indent=2)


def _expand_embedded_json_strings(data: Any) -> Any:
    """
    递归展开“JSON 里面再包一层 JSON 字符串”的字段。

    Pixiv 的 `__NEXT_DATA__` 里经常会出现这种情况：
    - 外层已经是 JSON
    - 但某个字段的值又是一个被转义过的 JSON 字符串

    如果不额外展开，人眼看到的会是一整大串 `\\\"`，
    调试时会非常吃力。
    """
    if isinstance(data, dict):
        expanded: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        expanded[key] = _expand_embedded_json_strings(json.loads(value))
                        continue
                    except json.JSONDecodeError:
                        pass
            expanded[key] = _expand_embedded_json_strings(value)
        return expanded

    if isinstance(data, list):
        return [_expand_embedded_json_strings(item) for item in data]

    return data


def _pretty_script_body(open_tag: str, raw_body: str) -> list[str]:
    """
    尝试把 `<script>` 里的内容整理得更适合阅读。

    优先处理最有价值的情况：
    - `type="application/json"`
    - `id="__NEXT_DATA__"`

    这些脚本通常就是解析器最关心的数据来源。
    """
    tag_text = open_tag.lower()
    stripped = raw_body.strip()

    is_json_script = 'type="application/json"' in tag_text or "id=\"__next_data__\"" in tag_text
    if is_json_script and stripped:
        try:
            parsed = json.loads(stripped)
            expanded = _expand_embedded_json_strings(parsed)
            return pretty_json_text(expanded).splitlines()
        except json.JSONDecodeError:
            pass

    body_lines = [line.rstrip() for line in raw_body.strip().splitlines() if line.strip()]
    return body_lines or [stripped]


def pretty_html_text(html: str) -> str:
    """
    把压缩过的 HTML 尽量整理成更容易阅读的格式。

    这里的目标是“便于调试”，不是“还原成完美源码”。
    所以策略是：
    - 标签单独成行
    - 文本内容适度缩进
    - `script/style` 保留为整块，避免被拆得太碎
    """
    raw_blocks: dict[str, tuple[str, str, str]] = {}

    def stash_raw_block(match: re.Match[str]) -> str:
        key = f"__RAW_HTML_BLOCK_{len(raw_blocks)}__"
        raw_blocks[key] = (
            match.group(1),
            match.group(3),
            match.group(4),
        )
        return f"<!--{key}-->"

    html = re.sub(
        r"(<(script|style)\b[^>]*>)(.*?)(</\2\s*>)",
        stash_raw_block,
        html,
        flags=re.I | re.S,
    )

    tokens = re.findall(r"<!--.*?-->|<![^>]*>|<[^>]+>|[^<]+", html, flags=re.S)
    lines: list[str] = []
    indent = 0

    for token in tokens:
        stripped = token.strip()
        if not stripped:
            continue

        if stripped.startswith("</"):
            indent = max(indent - 1, 0)
            lines.append(f"{'  ' * indent}{stripped}")
            continue

        if stripped.startswith("<!--") and stripped.endswith("-->"):
            placeholder = stripped[4:-3]
            if placeholder in raw_blocks:
                open_tag, raw_body, close_tag = raw_blocks[placeholder]
                lines.append(f"{'  ' * indent}{open_tag}")

                body_lines = _pretty_script_body(open_tag, raw_body)
                for body_line in body_lines:
                    lines.append(f"{'  ' * (indent + 1)}{body_line}")

                lines.append(f"{'  ' * indent}{close_tag}")
                continue

        if stripped.startswith("<!--") or stripped.startswith("<!"):
            lines.append(f"{'  ' * indent}{stripped}")
            continue

        if stripped.startswith("<"):
            tag_match = re.match(r"<\s*([a-zA-Z0-9:-]+)", stripped)
            tag_name = tag_match.group(1).lower() if tag_match else ""
            is_self_closing = stripped.endswith("/>") or tag_name in VOID_HTML_TAGS

            lines.append(f"{'  ' * indent}{stripped}")

            if not is_self_closing:
                indent += 1
            continue

        normalized_text = re.sub(r"\s+", " ", stripped)
        lines.append(f"{'  ' * indent}{normalized_text}")

    return "\n".join(lines) + "\n"
