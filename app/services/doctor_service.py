"""
这个文件负责“运行环境自检”。

目标不是替你执行抓取任务，
而是在真正开跑前，先把那些最容易踩坑的运行条件检查一遍：
- 账号密码有没有配全
- 代理配置是不是自洽
- 路径和目录是否可写
- 登录态文件是否存在且可读
- Playwright 浏览器能不能真正启动
- 现有登录态是否仍然有效
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

from app.browser.client import BrowserClient
from app.browser.login import PixivLoginService
from app.core.config import settings

DoctorStatus = Literal["ok", "warn", "error", "skip"]


class DoctorCheck(TypedDict):
    name: str
    status: DoctorStatus
    detail: str


class DoctorReport(TypedDict):
    checks: list[DoctorCheck]


def _build_check(name: str, status: DoctorStatus, detail: str) -> DoctorCheck:
    return {
        "name": name,
        "status": status,
        "detail": detail,
    }


def _check_credentials() -> DoctorCheck:
    username_ready = bool(settings.pixiv_username.strip())
    password_ready = bool(settings.pixiv_password.strip())

    if username_ready and password_ready:
        return _build_check("账号密码", "ok", "已配置 Pixiv 账号密码。")

    if username_ready or password_ready:
        return _build_check("账号密码", "warn", "账号密码只配置了一半，自动登录大概率会失败。")

    return _build_check("账号密码", "warn", "未配置账号密码，如需自动登录请补全 PIXIV_USERNAME / PIXIV_PASSWORD。")


def _check_proxy() -> DoctorCheck:
    proxy_server = settings.proxy_server.strip()
    proxy_username = settings.proxy_username.strip()
    proxy_password = settings.proxy_password.strip()

    if not proxy_server and not proxy_username and not proxy_password:
        return _build_check("代理配置", "ok", "未配置代理，将直接访问 Pixiv。")

    if not proxy_server and (proxy_username or proxy_password):
        return _build_check("代理配置", "warn", "填写了代理账号或密码，但 PROXY_SERVER 为空。")

    if proxy_password and not proxy_username:
        return _build_check("代理配置", "warn", "填写了代理密码，但 PROXY_USERNAME 为空。")

    if proxy_server and proxy_username and not proxy_password:
        return _build_check("代理配置", "ok", "已配置带用户名的代理，当前按空密码处理。")

    return _build_check("代理配置", "ok", "代理配置结构完整。")


def _probe_writable_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".doctor_", delete=True):
        pass


def _check_directory_path(name: str, path: Path) -> DoctorCheck:
    try:
        _probe_writable_directory(path)
    except Exception as exc:
        return _build_check(name, "error", f"目录不可写：{path}（{exc}）")

    return _build_check(name, "ok", f"目录可用：{path}")


def _check_file_parent(name: str, file_path: Path) -> DoctorCheck:
    try:
        _probe_writable_directory(file_path.parent)
    except Exception as exc:
        return _build_check(name, "error", f"父目录不可写：{file_path.parent}（{exc}）")

    return _build_check(name, "ok", f"父目录可用：{file_path.parent}")


def _check_state_file() -> DoctorCheck:
    state_path = Path(settings.state_file)
    if not state_path.exists():
        return _build_check("登录态文件", "warn", f"未找到登录态文件：{state_path}")

    if not state_path.is_file():
        return _build_check("登录态文件", "error", f"路径存在但不是文件：{state_path}")

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _build_check("登录态文件", "error", f"登录态文件无法解析为 JSON：{exc}")

    if not isinstance(payload, dict):
        return _build_check("登录态文件", "error", "登录态文件格式异常，根节点不是对象。")

    return _build_check("登录态文件", "ok", f"登录态文件存在且可读：{state_path}")


def _check_browser_runtime() -> list[DoctorCheck]:
    client = BrowserClient()

    try:
        try:
            client.start()
        except Exception as exc:
            return [_build_check("浏览器启动", "error", f"Playwright/Chromium 启动失败：{exc}")]

        runtime_checks = [_build_check("浏览器启动", "ok", "Playwright 与 Chromium 可以正常启动。")]

        if not client.state_manager.state_exists():
            runtime_checks.append(
                _build_check("登录态有效性", "skip", "未找到登录态文件，跳过登录有效性检查。")
            )
            return runtime_checks

        login_service = PixivLoginService(client)
        if login_service.is_logged_in():
            runtime_checks.append(_build_check("登录态有效性", "ok", "当前登录态有效。"))
        else:
            runtime_checks.append(
                _build_check("登录态有效性", "warn", "登录态文件存在，但当前登录态已失效或仍需重新登录。")
            )

        return runtime_checks
    finally:
        client.close()


def run_doctor() -> DoctorReport:
    checks: list[DoctorCheck] = [
        _check_credentials(),
        _check_proxy(),
        _check_directory_path("下载目录", Path(settings.download_dir)),
        _check_file_parent("数据库路径", Path(settings.db_path)),
        _check_file_parent("日志路径", Path(settings.log_path)),
        _check_file_parent("登录态路径", Path(settings.state_file)),
        _check_state_file(),
    ]
    checks.extend(_check_browser_runtime())

    return {"checks": checks}


def summarize_doctor_report(report: DoctorReport) -> dict[str, int]:
    summary = {"ok": 0, "warn": 0, "error": 0, "skip": 0}
    for check in report["checks"]:
        summary[check["status"]] += 1
    return summary
