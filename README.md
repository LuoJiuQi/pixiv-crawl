# pixiv-crawl

一个基于 Playwright 的 Pixiv 爬虫项目，当前已经支持：

- 自动登录与登录态复用
- 单作品抓取与解析
- 多图作品自动全下
- 批量输入作品 ID / 作品链接
- SQLite 任务记录
- 失败任务重试
- 失败清单导出
- 旧记录归档与清理

## 当前能力

- 作品页抓取：打开作品详情页，保存 HTML 和解析结果 JSON
- 作品解析：提取标题、作者、标签、页数、候选图片地址等信息
- 图片下载：复用当前浏览器 cookies 下载原图，并支持多图作品
- 批量任务：批量处理多个作品，单个失败不会中断后续任务
- 数据库记录：记录成功 / 失败 / 错误类型 / 下载文件等信息
- 历史管理：查看记录、按失败类型筛选、重试失败任务、导出失败清单、归档旧记录

## 环境准备

1. 创建虚拟环境

```powershell
python -m venv .venv
```

2. 激活虚拟环境

```powershell
.venv\Scripts\Activate.ps1
```

3. 安装依赖

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

4. 创建本地配置文件

把 `.env.example` 复制为 `.env`，然后填写自己的 Pixiv 账号密码。

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

## 项目结构

实际结构请看 [项目结构.md](./项目结构.md)。

当前最重要的目录是：

- `app/browser`：浏览器启动、登录、登录态管理
- `app/crawler`：页面采集
- `app/parser`：作品信息解析
- `app/downloader`：图片下载
- `app/db`：SQLite 任务记录
- `app/services`：失败分类、导出等服务
- `data/temp`：调试样本
- `tests`：单元测试

## 测试

```powershell
python -m unittest tests.test_record_exporter tests.test_failure_exporter tests.test_failure_classifier tests.test_db tests.test_main tests.test_parser tests.test_downloader -v
```

## 说明

- `data/temp` 里的 HTML / JSON 样本用于调试和测试，建议保留
- `data/images`、`data/state`、`data/exports`、`data/*.db` 属于运行产物，默认已加入 `.gitignore`
- 当前项目仍以网页抓取链路为主，尚未接入 `pixivpy3`
