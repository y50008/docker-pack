# Docker Pack Web 自身镜像
# 构建: docker build -t docker-pack-web .
# 运行: docker run -d -p 8000:8000 \
#          -v /var/run/docker.sock:/var/run/docker.sock \
#          -v /data/docker-pack-web:/data \
#          docker-pack-web
FROM python:3.11-slim

# docker CLI（用于调用宿主机 Docker）+ git（用于克隆仓库）
RUN apt-get update && apt-get install -y --no-install-recommends \
        docker.io git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY web/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY core.py web_app.py ./
COPY templates ./templates

# 数据目录（产物 tar 输出位置）
RUN mkdir -p /data
ENV DPW_DATA_DIR=/data
ENV PORT=8000

EXPOSE 8000
CMD ["python", "web_app.py"]
