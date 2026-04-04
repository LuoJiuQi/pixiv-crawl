FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

# 把工作目录固定到 /app，后面所有命令都在这里执行。
WORKDIR /app

# 先复制依赖清单，利用 Docker 的层缓存。
COPY requirements.txt ./

RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 再复制项目源码。
COPY . .

# 让 Python 日志直接输出到终端，方便看容器日志。
ENV PYTHONUNBUFFERED=1

# Docker 里默认走无头模式更稳。
ENV HEADLESS=true

CMD ["python", "main.py"]
