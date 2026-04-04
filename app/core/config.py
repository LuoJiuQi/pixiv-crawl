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

    # 图片下载目录。
    download_dir: str = "./data/images"

    # Playwright 登录状态文件保存位置。
    state_file: str = "./data/state/storage_state.json"

    # 预留的数据库文件路径。
    db_path: str = "./data/pixiv.db"

    # 预留的日志文件路径。
    log_path: str = "./logs/app.log"

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
