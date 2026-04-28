"""
这个文件专门负责“读取项目配置”。

你可以把它理解成项目的“统一设置中心”：
- Pixiv 账号密码从哪里拿
- 浏览器是否显示窗口
- 下载目录放在哪里
- 登录状态文件保存在哪里

为什么要把配置集中放在这里？
- 修改配置时，不需要去很多文件里逐个改
- 其他模块只需要导入 `settings`，就能拿到统一结果
- 项目会更整洁，也更容易维护
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    `Settings` 是项目的配置对象。

    它继承了 `BaseSettings`，这意味着：
    - 这里定义的字段可以从 `.env` 文件里自动读取
    - 也可以从系统环境变量里自动读取
    - 如果没有外部值，就使用这里写的默认值

    对零基础来说，可以先把它理解成：
    “先定义项目需要哪些设置，再让程序自动去外部配置里找值。”
    """

    # Pixiv 登录账号。
    # 这里给空字符串作为默认值，真正运行时通常会被 `.env` 覆盖。
    pixiv_username: str = ""

    # Pixiv 登录密码。
    pixiv_password: str = ""

    # 是否以“无头模式”启动浏览器。
    # False：会弹出浏览器窗口，适合调试和手动登录。
    # True：浏览器在后台运行，看不到窗口，适合自动化。
    headless: bool = False

    # 可选代理设置。
    # 如果你所在网络环境无法直接访问 Pixiv，
    # 可以在 `.env` 里填写代理地址，例如：
    # `http://host.docker.internal:7890`
    # `socks5://127.0.0.1:7890`
    proxy_server: str = ""

    # 如果代理要求认证，就再补账号密码。
    proxy_username: str = ""
    proxy_password: str = ""

    # 默认超时时间，单位是毫秒。
    # 30000 毫秒 = 30 秒。
    timeout: int = 30000

    # 是否把调试用的 HTML / JSON 快照保存到 `data/temp`。
    # 关闭后，常规批量抓取时不会再持续写入大量调试文件。
    save_debug_artifacts: bool = False

    # 是否打印更详细的解析调试信息。
    # 关闭后，终端输出会更适合长期批量运行。
    verbose_debug_output: bool = False

    # 图片下载目录。
    download_dir: str = "./data/images"

    # 下载图片时单次请求的超时时间，单位是秒。
    download_timeout_seconds: float = 60.0

    # 下载图片时最多尝试多少次。
    # 这里包含第一次请求本身，例如 3 表示“最多 1 次初试 + 2 次重试”。
    download_retry_attempts: int = 3

    # 下载失败后的基础退避时间，单位是秒。
    # 实际等待时间会按 1x、2x、4x 指数递增。
    download_retry_backoff_seconds: float = 1.0

    # Playwright 登录状态文件保存位置。
    state_file: str = "./data/state/storage_state.json"

    # 预留的数据库文件路径。
    db_path: str = "./data/pixiv.db"

    # 预留的日志文件路径。
    log_path: str = "./logs/app.log"

    # 单个日志文件达到多大后开始滚动，单位是字节。
    # 默认 5 MB，足够保留近期运行信息，又不会无限增长。
    log_max_bytes: int = 5 * 1024 * 1024

    # 最多保留多少个历史滚动日志文件。
    log_backup_count: int = 5

    # 是否开启内置定时抓取。
    # 开启后，直接执行 `python main.py` 会进入每日定时模式，
    # 到设定时间自动跑一次“按关注列表更新画师”。
    scheduled_run_enabled: bool = False

    # 每天几点开始执行定时抓取，24 小时制，格式固定为 HH:MM。
    scheduled_run_time: str = "02:00"

    # 是否在定时更新成功后，再自动补跑一次失败重试。
    scheduled_retry_failed_enabled: bool = False

    # 定时补跑失败重试时，最多处理多少条失败记录。
    # 0 表示不处理任何失败记录；通常建议配一个有限值，避免单次补偿拖太久。
    scheduled_retry_failed_limit: int = 20

    # 定时任务每轮执行完成后，JSON 报告默认写到哪里。
    scheduled_report_output_dir: str = "./data/exports/scheduled-reports"

    @field_validator("scheduled_run_time")
    @classmethod
    def validate_scheduled_run_time(cls, value: str) -> str:
        text = str(value).strip()
        hour_text, separator, minute_text = text.partition(":")
        if separator != ":" or not hour_text.isdigit() or not minute_text.isdigit():
            raise ValueError("SCHEDULED_RUN_TIME 必须是 24 小时制 HH:MM 格式。")

        hour = int(hour_text)
        minute = int(minute_text)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("SCHEDULED_RUN_TIME 必须是有效的 24 小时制时间。")

        return f"{hour:02d}:{minute:02d}"

    @field_validator("scheduled_retry_failed_limit")
    @classmethod
    def validate_scheduled_retry_failed_limit(cls, value: int) -> int:
        if int(value) < 0:
            raise ValueError("SCHEDULED_RETRY_FAILED_LIMIT 不能小于 0。")
        return int(value)

    # 告诉 pydantic-settings 去哪里读取配置。
    model_config = SettingsConfigDict(
        # 指定读取哪个文件。
        env_file=".env",
        # 指定文件编码，避免中文乱码。
        env_file_encoding="utf-8",
        # 配置项大小写不敏感。
        case_sensitive=False,
    )


# 在模块加载时直接创建一个全局配置对象。
# 这样其他文件只要导入 `settings`，就能立刻使用。
settings = Settings()
