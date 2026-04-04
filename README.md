# pixiv-crawl

一个基于 Playwright 的 Pixiv 爬虫项目，当前已经支持：

- 自动登录与登录态复用
- 单作品抓取与解析
- 多图作品自动全下
- 批量输入作品 ID / 作品链接
- 按作者批量抓取作品
- 按作者增量更新作品
- SQLite 任务记录
- 失败任务重试
- 失败清单导出
- 旧记录归档与清理
- Docker 运行支持

## 当前能力

- 作品页抓取：打开作品详情页，保存 HTML 和解析结果 JSON
- 作者页抓取：打开作者页并提取作者名下作品 ID
- 作品解析：提取标题、作者、标签、页数、候选图片地址等信息
- 图片下载：复用当前浏览器 cookies 下载原图，并支持多图作品
- 图片命名：按“一个作者一个文件夹，作品标题 + 作品 ID”保存图片
- 批量任务：批量处理多个作品，单个失败不会中断后续任务
- 增量更新：作者模式下只处理新作品和失败作品
- 数据库记录：记录成功 / 失败 / 错误类型 / 下载文件等信息
- 历史管理：查看记录、按失败类型筛选、重试失败任务、导出失败清单、归档旧记录

## 环境准备

1. 创建虚拟环境

```powershell
python -m venv .venv
```

1. 激活虚拟环境

```powershell
.venv\Scripts\Activate.ps1
```

1. 安装依赖

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

1. 创建本地配置文件

把 `.env.example` 复制为 `.env`，然后填写自己的 Pixiv 账号密码。

如果你所在网络环境无法直接访问 Pixiv，也可以在 `.env` 里补代理：

```env
PROXY_SERVER=http://127.0.0.1:7890
```

支持常见的：

- `http://...`
- `https://...`
- `socks5://...`

如果代理需要认证，再补：

```env
PROXY_USERNAME=
PROXY_PASSWORD=
```

## Docker 运行

这个项目已经补好了基础容器化文件：

- [Dockerfile](./Dockerfile)
- [docker-compose.yml](./docker-compose.yml)
- [.dockerignore](./.dockerignore)

最推荐的 Docker 使用方式是：

1. 先在本机完成一次登录，生成登录态文件  
原因：Pixiv 登录可能会触发 `reCAPTCHA`，而容器里默认是无头模式，人工处理验证码不方便。

1. 确认本地这些文件已经存在

- `.env`
- `data/state/storage_state.json`

1. 构建镜像

```powershell
docker compose build
```

1. 启动交互式命令行

```powershell
docker compose run --rm pixiv-crawl
```

容器运行时会直接复用你本地挂载进去的：

- `data/`
- `logs/`

所以这些数据不会因为容器退出而丢失。

### Docker 代理说明

如果在中国内陆运行，需要访问 Pixiv 的代理，直接把 `PROXY_SERVER` 写进 `.env` 即可。  
项目会自动把同一套代理同时用于：

- Playwright 浏览器访问 Pixiv
- `httpx` 下载图片

因为 `docker-compose.yml` 已经通过 `env_file` 读取 `.env`，所以容器里也会自动拿到这套代理配置。

### Docker 注意事项

- `docker-compose.yml` 里已经把 `HEADLESS` 强制覆盖成 `true`
- 如果你需要首次人工登录，更建议先在宿主机上跑通一次，再把 `data/state/storage_state.json` 带进容器
- 当前使用的是 Playwright 官方 Python 镜像 `mcr.microsoft.com/playwright/python:v1.58.0-noble`

## 运行方式

```powershell
python main.py
```

启动后目前支持这些模式：

- `1` 批量抓取作品
- `2` 查看历史记录
- `3` 重试失败任务
- `4` 导出失败清单
- `5` 归档并清理旧记录
- `6` 按作者批量抓取作品

## 项目结构

实际结构请看 [项目结构.md](./项目结构.md)。

当前最重要的目录是：

- `app/browser`：浏览器启动、登录、登录态管理
- `app/crawler`：作品页 / 作者页采集
- `app/parser`：作品信息解析
- `app/downloader`：图片下载
- `app/db`：SQLite 任务记录
- `app/services`：CLI、批量任务、失败分类、导出等服务
- `data/temp`：本地临时调试目录
- `tests`：单元测试

## 测试

```powershell
python -m unittest tests.test_task_service tests.test_author_crawler tests.test_cli_service tests.test_record_exporter tests.test_failure_exporter tests.test_failure_classifier tests.test_db tests.test_main tests.test_parser tests.test_downloader -v
```

## 说明

- `data/temp` 里的 HTML / JSON 主要用于本地调试，当前已加入 `.gitignore`
- `data/images`、`data/state`、`data/exports`、`data/*.db` 属于运行产物，默认已加入 `.gitignore`
- 当前项目仍以网页抓取链路为主，尚未接入 `pixivpy3`

## 参考资料

- Playwright 官方 Docker 说明：<https://playwright.dev/python/docs/docker>
- Playwright 官方认证状态复用说明：<https://playwright.dev/python/docs/auth>
