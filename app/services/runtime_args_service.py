"""
统一管理非交互 CLI 的参数解析和基础动作判断。

这里不负责真正执行抓取，只负责把：
- 用户传进来的子命令
- 作品 / 作者输入
- 各类 limit / filter 参数

整理成主流程可以直接消费的结果。
"""

import argparse

from app.services.cli_service import AuthorCollectOptions, parse_artwork_ids, parse_user_id


def action_requires_direct_artwork_input(action: str) -> bool:
    """
    判断当前动作是否需要“手动输入作品 ID”。

    现在会自己去收集作品来源的模式有：
    - `crawl_author`：先从作者主页拿作品列表
    - `crawl_following`：先从关注画师列表里拿作者，再继续增量更新
    """
    return action not in {"crawl_author", "crawl_following"}


def build_argument_parser() -> argparse.ArgumentParser:
    """
    构建非交互命令行参数解析器。

    如果没有提供任何子命令，程序仍然会回到原来的交互菜单模式。
    """
    parser = argparse.ArgumentParser(
        description="Pixiv 批量抓取工具。不给子命令时，将进入交互菜单模式。",
    )
    subparsers = parser.add_subparsers(dest="action")

    crawl_parser = subparsers.add_parser("crawl", help="批量抓取作品")
    crawl_parser.add_argument(
        "artwork_inputs",
        nargs="+",
        help="作品 ID 或作品链接，可一次传多个。",
    )

    author_parser = subparsers.add_parser("crawl-author", help="按作者抓取作品")
    author_parser.add_argument("author", help="作者 ID 或作者主页链接。")
    author_parser.add_argument("--limit", type=int, default=0, help="最多抓取多少个作品。")
    author_parser.add_argument(
        "--update-mode",
        choices=["incremental", "full"],
        default="incremental",
        help="作者抓取模式，默认 incremental。",
    )
    author_parser.add_argument(
        "--completed-streak-limit",
        type=int,
        default=10,
        help="增量模式下连续遇到多少个已完成作品后停止扫描。",
    )

    following_parser = subparsers.add_parser("crawl-following", help="按关注列表更新画师")
    following_parser.add_argument("--limit", type=int, default=0, help="最多处理多少位关注画师。")
    following_parser.add_argument(
        "--completed-streak-limit",
        type=int,
        default=10,
        help="每位作者增量模式下连续遇到多少个已完成作品后停止扫描。",
    )

    history_parser = subparsers.add_parser("history", help="查看历史记录")
    history_parser.add_argument(
        "--status",
        choices=["all", "completed", "failed"],
        default="all",
        help="按状态筛选。",
    )
    history_parser.add_argument("--error-type", default="", help="按失败类型筛选。")
    history_parser.add_argument("--limit", type=int, default=10, help="最多展示多少条记录。")

    retry_parser = subparsers.add_parser("retry-failed", help="重试失败任务")
    retry_parser.add_argument("--error-type", default="", help="只重试某一种失败类型。")
    retry_parser.add_argument("--limit", type=int, default=0, help="最多重试多少条失败记录。")

    export_parser = subparsers.add_parser("export-failed", help="导出失败清单")
    export_parser.add_argument("--error-type", default="", help="只导出某一种失败类型。")
    export_parser.add_argument("--limit", type=int, default=0, help="最多导出多少条失败记录。")
    export_parser.add_argument(
        "--format",
        choices=["json", "txt"],
        default="json",
        help="导出格式。",
    )

    archive_parser = subparsers.add_parser("archive-records", help="归档并清理旧记录")
    archive_parser.add_argument(
        "--status",
        choices=["all", "completed", "failed"],
        default="completed",
        help="要归档的记录状态。",
    )
    archive_parser.add_argument("--days", type=int, default=30, help="归档多少天以前的记录。")
    archive_parser.add_argument("--limit", type=int, default=100, help="最多归档多少条记录。")
    archive_parser.add_argument(
        "--format",
        choices=["json", "txt"],
        default="json",
        help="归档文件格式。",
    )
    archive_parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行归档并删除，不再二次提示。",
    )

    doctor_parser = subparsers.add_parser("doctor", help="检查运行环境、浏览器与登录态")
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="将 warning 也视为失败，返回非 0 退出码。",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="以 JSON 输出自检结果，适合脚本或 CI 消费。",
    )
    doctor_parser.add_argument(
        "--output",
        default="",
        help="把自检 JSON 结果写入指定文件路径。",
    )

    return parser


def parse_runtime_arguments(argv: list[str] | None) -> argparse.Namespace | None:
    """
    解析运行时参数。

    约定：
    - `argv is None`：表示使用原来的交互模式
    - `argv == []`：脚本直接启动但没带参数，也回到交互模式
    """
    if argv is None or not argv:
        return None

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    raw_action = args.action

    if raw_action == "crawl":
        artwork_ids = parse_artwork_ids("\n".join(args.artwork_inputs))
        if not artwork_ids:
            parser.error("没有识别到有效的作品 ID，请传入作品 ID 或作品链接。")
        args.artwork_ids = artwork_ids

    if raw_action == "crawl-author":
        user_id = parse_user_id(args.author)
        if not user_id:
            parser.error("没有识别到有效的作者 ID，请传入作者 ID 或作者主页链接。")
        if args.limit < 0:
            parser.error("--limit 不能小于 0。")
        if args.completed_streak_limit <= 0:
            parser.error("--completed-streak-limit 必须大于 0。")
        args.author_request = AuthorCollectOptions(
            user_id=user_id,
            limit=args.limit or None,
            update_mode=args.update_mode,
            completed_streak_limit=args.completed_streak_limit,
        )

    if raw_action == "crawl-following":
        if args.limit < 0:
            parser.error("--limit 不能小于 0。")
        if args.completed_streak_limit <= 0:
            parser.error("--completed-streak-limit 必须大于 0。")
        args.following_limit = args.limit or None

    if raw_action == "history" and args.limit <= 0:
        parser.error("--limit 必须大于 0。")

    if raw_action == "retry-failed" and args.limit < 0:
        parser.error("--limit 不能小于 0。")

    if raw_action == "export-failed" and args.limit < 0:
        parser.error("--limit 不能小于 0。")

    if raw_action == "archive-records":
        if args.days <= 0:
            parser.error("--days 必须大于 0。")
        if args.limit <= 0:
            parser.error("--limit 必须大于 0。")
        if not args.yes:
            parser.error("archive-records 需要显式传入 --yes 才会执行删除。")

    args.action = raw_action.replace("-", "_")
    return args


def normalize_optional_text(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    return text or None
