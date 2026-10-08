#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py — Docker 打包核心逻辑
被 GUI 调用，通过回调函数推送日志行和进度。
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional


# ---------- 项目类型 ----------

class ProjectType:
    NODE = "nodejs"
    PYTHON = "python"
    MAVEN = "maven"
    GRADLE = "gradle"
    GO = "golang"
    DOTNET = "dotnet"
    PHP = "php"
    RUBY = "ruby"
    RUST = "rust"
    CPP = "cpp-cmake"
    FLUTTER = "flutter"
    STATIC = "static"
    CUSTOM = "custom-dockerfile"   # 项目自带 Dockerfile
    UNKNOWN = "unknown"


DOCKERFILES = {
    ProjectType.NODE: """\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com \\
 && (npm ci || npm install)
COPY . .
RUN npm run build --if-present

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package*.json ./
RUN npm config set registry https://registry.npmmirror.com \\
 && npm ci --only=production \\
 && npm cache clean --force
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
EXPOSE {port}
CMD ["node", "dist/index.js"]
""",
    ProjectType.PYTHON: """\
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim AS runner
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \\
 && rm -rf /wheels
COPY . .
EXPOSE {port}
CMD ["python", "app.py"]
""",
    ProjectType.MAVEN: """\
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B -DskipTests
COPY src ./src
RUN mvn package -B -DskipTests

FROM eclipse-temurin:21-jre-alpine AS runner
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
EXPOSE {port}
ENTRYPOINT ["java", "-jar", "app.jar"]
""",
    ProjectType.GRADLE: """\
FROM gradle:8-jdk21 AS builder
WORKDIR /app
COPY build.gradle settings.gradle ./
RUN gradle dependencies --no-daemon || true
COPY . .
RUN gradle bootJar -x test --no-daemon

FROM eclipse-temurin:21-jre-alpine AS runner
WORKDIR /app
COPY --from=builder /app/build/libs/*.jar app.jar
EXPOSE {port}
ENTRYPOINT ["java", "-jar", "app.jar"]
""",
    ProjectType.GO: """\
FROM golang:1.22-alpine AS builder
WORKDIR /app
ENV GOPROXY=https://goproxy.cn,direct
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /app/server .

FROM alpine:3.19 AS runner
WORKDIR /app
RUN apk --no-cache add ca-certificates tzdata \\
 && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
COPY --from=builder /app/server .
EXPOSE {port}
CMD ["./server"]
""",
    ProjectType.DOTNET: """\
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS builder
WORKDIR /app
COPY *.csproj ./
RUN dotnet restore
COPY . .
RUN dotnet publish -c Release -o /out

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runner
WORKDIR /app
COPY --from=builder /out ./
EXPOSE {port}
ENTRYPOINT ["dotnet", "app.dll"]
""",
    ProjectType.PHP: """\
FROM composer:2 AS builder
WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install --no-dev --optimize-autoloader --no-interaction

FROM php:8.3-apache AS runner
WORKDIR /app
COPY --from=builder /app/vendor ./vendor
COPY . .
RUN docker-php-ext-install pdo_mysql 2>/dev/null || true
EXPOSE {port}
""",
    ProjectType.RUBY: """\
FROM ruby:3.2-alpine AS builder
WORKDIR /app
RUN apk add --no-cache build-base
COPY Gemfile Gemfile.lock ./
RUN bundle config set --local frozen false \\
 && bundle install jobs=4 --retry=3

FROM ruby:3.2-alpine AS runner
WORKDIR /app
COPY --from=builder /usr/local/bundle /usr/local/bundle
COPY . .
EXPOSE {port}
CMD ["ruby", "app.rb"]
""",
    ProjectType.RUST: """\
FROM rust:1.77-alpine AS builder
WORKDIR /app
RUN apk add --no-cache musl-dev
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src
COPY src ./src
RUN cargo build --release

FROM alpine:3.19 AS runner
WORKDIR /app
COPY --from=builder /app/target/release/app /app/server
EXPOSE {port}
CMD ["./server"]
""",
    ProjectType.CPP: """\
FROM gcc:13 AS builder
WORKDIR /app
COPY CMakeLists.txt ./
COPY src ./src
RUN apt-get update && apt-get install -y cmake \\
 && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \\
 && cmake --build build -j

FROM debian:bookworm-slim AS runner
WORKDIR /app
COPY --from=builder /app/build/app /app/server
EXPOSE {port}
CMD ["./server"]
""",
    ProjectType.FLUTTER: """\
--========== 说明：Flutter Web/移动产物体积大，需要 Flutter SDK ==========--
FROM ghcr.io/cirruslabs/flutter:stable AS builder
WORKDIR /app
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get
COPY . .
RUN flutter build web

FROM nginx:alpine AS runner
COPY --from=builder /app/build/web /usr/share/nginx/html/
EXPOSE {port}
CMD ["nginx", "-g", "daemon off;"]
""",
    ProjectType.STATIC: """\
FROM nginx:alpine
COPY . /usr/share/nginx/html/
EXPOSE {port}
CMD ["nginx", "-g", "daemon off;"]
""",
}

DOCKERIGNORE = """\
.git
.github
.vscode
.idea
.DS_Store
Thumbs.db
node_modules
dist
build
target
bin
obj
__pycache__
*.pyc
.venv
venv
vendor
.git
.gradle
*.iml
*.log
logs
tmp
.env
.env.*
docker-compose.yml
docker-compose.yaml
"""


# ---------- 检测 ----------

def detect_project_type(root: Path) -> str:
    # 优先级 1：项目自带 Dockerfile —— 直接尊重，不覆盖
    if (root / "Dockerfile").exists():
        return ProjectType.CUSTOM
    if (root / "docker-compose.yml").exists() or (root / "docker-compose.yaml").exists():
        # 有 compose 但没 Dockerfile，仍按源码类型识别
        pass
    if (root / "package.json").exists():
        return ProjectType.NODE
    if any((root / f).exists() for f in ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"]):
        return ProjectType.PYTHON
    if (root / "pom.xml").exists():
        return ProjectType.MAVEN
    if any((root / f).exists() for f in ["build.gradle", "build.gradle.kts", "settings.gradle"]):
        return ProjectType.GRADLE
    if (root / "go.mod").exists():
        return ProjectType.GO
    if list(root.glob("*.csproj")) or list(root.glob("*.sln")):
        return ProjectType.DOTNET
    if (root / "composer.json").exists():
        return ProjectType.PHP
    if (root / "Gemfile").exists():
        return ProjectType.RUBY
    if (root / "Cargo.toml").exists():
        return ProjectType.RUST
    if (root / "CMakeLists.txt").exists():
        return ProjectType.CPP
    if (root / "pubspec.yaml").exists():
        return ProjectType.FLUTTER
    if (root / "index.html").exists():
        return ProjectType.STATIC
    return ProjectType.UNKNOWN


def detect_start_file(root: Path, ptype: str):
    """返回 (入口相对路径, 是否为 dist 构建产物)"""
    if ptype == ProjectType.NODE:
        for f in ["dist/index.js", "dist/main.js", "dist/server.js"]:
            if (root / f).exists():
                return f, True
        if (root / "tsconfig.json").exists() or list(root.glob("*.config.js")) or list(root.glob("*.config.ts")):
            return "dist/index.js", True
        for f in ["index.js", "app.js", "server.js", "src/index.js", "src/app.js"]:
            if (root / f).exists():
                return f, False
    if ptype == ProjectType.PYTHON:
        for f in ["app.py", "main.py", "server.py", "manage.py", "wsgi.py", "run.py"]:
            if (root / f).exists():
                return f, False
    if ptype == ProjectType.RUBY:
        for f in ["app.rb", "main.rb", "server.rb", "config.ru"]:
            if (root / f).exists():
                return f, False
    return None, False


def prepare_dockerfile(root: Path, ptype: str, port: int, log: Optional[Callable[[str], None]] = None) -> None:
    """在项目根目录生成 Dockerfile 和 .dockerignore。若项目已有 Dockerfile，则保留不覆盖。"""
    # 已有 Dockerfile：尊重用户，只补 .dockerignore
    if ptype == ProjectType.CUSTOM:
        if log:
            log("[detect] 项目自带 Dockerfile，直接复用，不覆盖")
        (root / ".dockerignore").write_text(DOCKERIGNORE, encoding="utf-8", newline="\n")
        return

    tpl = DOCKERFILES.get(ptype)
    if tpl:
        content = tpl.format(port=port)
    else:
        content = f"FROM alpine:3.19\nWORKDIR /app\nCOPY . .\nEXPOSE {port}\nCMD [\"sh\"]\n"

    start_file, is_dist = detect_start_file(root, ptype)
    if start_file:
        if ptype == ProjectType.NODE:
            content = content.replace('["node", "dist/index.js"]', f'["node", "{start_file}"]')
            if not is_dist:
                content = content.replace("RUN npm run build --if-present\n", "")
                content = content.replace("COPY --from=builder /app/dist ./dist\n", "COPY --from=builder /app .\n")
                content = content.replace("COPY --from=builder /app/node_modules ./node_modules\n", "")
        elif ptype == ProjectType.PYTHON:
            content = content.replace('["python", "app.py"]', f'["python", "{start_file}"]')
        elif ptype == ProjectType.RUBY:
            content = content.replace('["ruby", "app.rb"]', f'["ruby", "{start_file}"]')

    (root / "Dockerfile").write_text(content, encoding="utf-8", newline="\n")
    (root / ".dockerignore").write_text(DOCKERIGNORE, encoding="utf-8", newline="\n")


# ---------- Git clone ----------

def is_git_url(s: str) -> bool:
    s = s.strip()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("git@") or s.endswith(".git")


def git_clone(url: str, dest: Path, log: Callable[[str], None]) -> Path:
    """clone 仓库到 dest，返回项目根目录（可能是 dest 本身或其子目录）"""
    log(f"[git] 正在克隆 {url} ...")
    proc = subprocess.Popen(
        ["git", "clone", "--depth", "1", url, str(dest)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log("[git] " + line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"git clone 失败，退出码 {proc.returncode}")

    entries = [e for e in dest.iterdir() if not e.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


# ---------- Docker 构建 ----------

STEP_RE = re.compile(r"Step\s+(\d+)/(\d+)\s*:")


def build_and_export(
    source_dir: Path,
    image_name: str,
    tag: str,
    port: int,
    platforms: list[str],
    output_tar: Path,
    log: Callable[[str], None],
    progress: Callable[[float, str], None],
) -> None:
    """
    构建镜像并导出为 tar 文件。
    - 单架构：docker build → docker save
    - 多架构：docker buildx build --output type=oci,dest=...
    """
    if shutil.which("docker") is None:
        raise RuntimeError("未检测到 docker 命令，请先安装并启动 Docker Desktop")

    ptype = detect_project_type(source_dir)
    log(f"[detect] 项目类型: {ptype}")
    prepare_dockerfile(source_dir, ptype, port, log=log)
    log(f"[detect] Dockerfile / .dockerignore 就绪")

    full_tag = f"{image_name}:{tag}"
    multi_arch = len(platforms) > 1

    if multi_arch:
        platform_str = ",".join(platforms)
        log(f"[buildx] 多架构构建: {platform_str}")
        cmd = [
            "docker", "buildx", "build",
            "--platform", platform_str,
            "-t", full_tag,
            "--output", f"type=oci,dest={output_tar}",
            str(source_dir),
        ]
        _run_streaming(cmd, source_dir, log, progress, multi_arch=True)
    else:
        platform = platforms[0]
        log(f"[build] 单架构构建: {platform}")
        cmd = ["docker", "build", "--platform", platform, "-t", full_tag, str(source_dir)]
        _run_streaming(cmd, source_dir, log, progress, multi_arch=False)
        log(f"[save] 导出镜像到 {output_tar}")
        rc = subprocess.run(
            ["docker", "save", "-o", str(output_tar), full_tag],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        if rc.returncode != 0:
            raise RuntimeError(f"docker save 失败: {rc.stdout}")

    log(f"[done] 镜像已导出: {output_tar} ({output_tar.stat().st_size/1024/1024:.1f} MB)")


def _run_streaming(
    cmd: list,
    cwd: Path,
    log: Callable[[str], None],
    progress: Callable[[float, str], None],
    multi_arch: bool,
) -> None:
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    current, total = 0, 1
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        log(line)
        m = STEP_RE.search(line)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            pct = current / total if total else 0
            progress(pct, f"Step {current}/{total}")
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"命令执行失败，退出码 {proc.returncode}")
    if not multi_arch:
        progress(1.0, "完成")
