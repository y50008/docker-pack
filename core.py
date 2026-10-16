#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py — Docker 打包核心逻辑
被 GUI 调用，通过回调函数推送日志行和进度。
"""

import gzip
import os
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
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
    # 专项框架
    NEXTJS = "nextjs"
    DJANGO = "django"
    FASTAPI = "fastapi"
    SPRING_BOOT = "spring-boot"
    VITE = "vite-spa"
    DENO = "deno"
    ELIXIR = "elixir"
    HASKELL = "haskell"
    JULIA = "julia"
    SWIFT = "swift"
    UNKNOWN = "unknown"


DOCKERFILES = {
    ProjectType.NODE: """\
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \\
 npm config set registry https://registry.npmmirror.com \\
 && (npm ci || npm install)
COPY . .
RUN npm run build --if-present

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package*.json ./
RUN --mount=type=cache,target=/root/.npm \\
 npm config set registry https://registry.npmmirror.com \\
 && (npm ci --omit=dev || npm install --omit=dev) \\
 && npm cache clean --force
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
EXPOSE {port}
CMD ["node", "dist/index.js"]
""",
    ProjectType.PYTHON: """\
FROM python:3.11-slim AS builder
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/pip \\
 pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \\
 pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

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
RUN --mount=type=cache,target=/root/.m2 mvn dependency:go-offline -B -DskipTests
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn package -B -DskipTests

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
RUN --mount=type=cache,target=/root/.gradle gradle dependencies --no-daemon || true
COPY . .
RUN --mount=type=cache,target=/root/.gradle gradle bootJar -x test --no-daemon

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
COPY go.* ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \\
 CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /app/server .

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
COPY composer.* ./
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
COPY Gemfile* ./
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
COPY Cargo.* ./
RUN mkdir -p src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src
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
# Flutter Web 专项（需要 Flutter SDK，构建较慢）
FROM ghcr.io/cirruslabs/flutter:stable AS builder
WORKDIR /app
COPY pubspec.* ./
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
    # ---------- 专项框架模板 ----------
    ProjectType.NEXTJS: """\
# Next.js（SSR 模式）专项模板
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com \\
 && (npm ci || npm install)
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/package*.json ./
RUN npm config set registry https://registry.npmmirror.com \\
 && (npm ci --omit=dev || npm install --omit=dev) \\
 && npm cache clean --force
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/next.config.* ./
EXPOSE {port}
CMD ["npm", "start"]
""",
    ProjectType.DJANGO: """\
# Django 专项模板（migrate + collectstatic + gunicorn）
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
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput 2>/dev/null; gunicorn {wsgi_module}:application -b 0.0.0.0:{port} -w 4 --timeout 120"]
""",
    ProjectType.FASTAPI: """\
# FastAPI 专项模板（uvicorn 多 worker）
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
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "{port}", "--workers", "4"]
""",
    ProjectType.SPRING_BOOT: """\
# Spring Boot 专项模板（分层构建，利用 spring-boot layertools 加速依赖缓存）
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B -DskipTests
COPY src ./src
RUN mvn package -B -DskipTests

FROM eclipse-temurin:21-jre-alpine AS runner
WORKDIR /app
RUN addgroup -S spring && adduser -S spring -G spring
COPY --from=builder /app/target/*.jar app.jar
USER spring
EXPOSE {port}
ENTRYPOINT ["java", "-jar", "app.jar"]
""",
    ProjectType.VITE: """\
# Vite / Vue3 / React SPA 前端专项（node 构建 → nginx 托管，固定监听 80）
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \\
 npm config set registry https://registry.npmmirror.com \\
 && (npm ci || npm install)
COPY . .
RUN npm run build

FROM nginx:alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html
RUN printf 'server {\\n  listen {port};\\n  root /usr/share/nginx/html;\\n  location / { try_files $uri $uri/ /index.html; }\\n}\\n' > /etc/nginx/conf.d/default.conf
EXPOSE {port}
""",
    ProjectType.DENO: """\
# Deno 专项（入口自动识别 main.ts / mod.ts / server.ts / index.ts）
FROM denoland/deno:alpine-2.0
WORKDIR /app
COPY . .
RUN deno cache main.ts 2>/dev/null || true
EXPOSE {port}
CMD ["run", "--allow-all", "main.ts"]
""",
    ProjectType.ELIXIR: """\
# Elixir / Phoenix 专项（mix run 常驻启动）
FROM elixir:1.16-alpine AS builder
WORKDIR /app
RUN mix local.hex --force && mix local.rebar --force
COPY mix.exs mix.lock ./
RUN mix deps.get --only prod
COPY . .
RUN MIX_ENV=prod mix compile

FROM elixir:1.16-alpine AS runner
WORKDIR /app
COPY --from=builder /app .
EXPOSE {port}
CMD ["mix", "run", "--no-halt"]
""",
    ProjectType.HASKELL: """\
# Haskell 专项（stack 构建，可执行名如不同请修改最后一行）
FROM haskell:9.6 AS builder
WORKDIR /app
COPY stack.yaml package.yaml *.cabal ./
RUN stack build --only-dependencies
COPY . .
RUN stack build --copy-bins --local-bin-path /out

FROM debian:bookworm-slim AS runner
WORKDIR /app
COPY --from=builder /out/* /usr/local/bin/
EXPOSE {port}
CMD ["app"]
""",
    ProjectType.JULIA: """\
# Julia 专项（入口默认 src/main.jl，如不同请修改最后一行）
FROM julia:1.10
WORKDIR /app
COPY Project.toml Manifest.toml ./
RUN julia --project=. -e 'using Pkg; Pkg.instantiate()'
COPY . .
EXPOSE {port}
CMD ["julia", "--project=.", "src/main.jl"]
""",
    ProjectType.SWIFT: """\
# Swift 专项（可执行名默认 App，如不同请修改最后一行）
FROM swift:5.10 AS builder
WORKDIR /app
COPY Package.swift ./
RUN swift package resolve
COPY . .
RUN swift build -c release

FROM swift:5.10-slim AS runner
WORKDIR /app
COPY --from=builder /app/.build/release/App .
EXPOSE {port}
CMD ["./App"]
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
.gradle
*.iml
*.log
logs
tmp
.env
.env.*
docker-compose.yml
docker-compose.yaml
.next
staticfiles
.elasticbeanstalk
.DS_Store
"""


# ---------- 输入校验 ----------

IMAGE_NAME_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*(\/[a-z0-9]+([._-][a-z0-9]+)*)*$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def validate_image_name(name: str) -> str:
    """校验镜像名，返回错误信息（空串表示通过）。"""
    name = name.strip()
    if not name:
        return "镜像名不能为空"
    if name != name.lower():
        return "镜像名必须全部小写（Docker 规范），例如 my-app"
    if not IMAGE_NAME_RE.match(name):
        return "镜像名只能包含小写字母、数字、. _ - 和 / ，例如 my-app 或 registry.example.com/ns/my-app"
    return ""


def validate_tag(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        return "标签不能为空"
    if not TAG_RE.match(tag):
        return "标签只能包含字母、数字、_ . - ，且以字母/数字开头，例如 v1.0 或 latest"
    return ""


def validate_port(port) -> str:
    try:
        p = int(port)
    except (TypeError, ValueError):
        return "端口必须是数字"
    if not (1 <= p <= 65535):
        return "端口必须在 1-65535 之间"
    return ""


def validate_build_args(text: str) -> tuple[dict, str]:
    """解析 KEY=VALUE 每行一个的构建参数，返回 (参数字典, 错误信息)。"""
    args: dict[str, str] = {}
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return {}, f"第 {i} 行构建参数格式错误，应为 KEY=VALUE：{line}"
        k, v = line.split("=", 1)
        k = k.strip()
        if not k:
            return {}, f"第 {i} 行构建参数 KEY 为空"
        args[k] = v.strip()
    return args, ""


# ---------- 环境体检与错误翻译 ----------

def docker_preflight() -> None:
    """构建前体检：docker 命令存在 + 守护进程正在运行。"""
    if shutil.which("docker") is None:
        raise RuntimeError("未检测到 docker 命令，请先安装并启动 Docker Desktop")
    rc = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    if rc.returncode != 0:
        raise RuntimeError("Docker 守护进程未响应：请确认 Docker Desktop 已启动（托盘图标显示 running）后再重试")


def friendly_error(msg: str) -> str:
    """把常见 Docker 英文报错翻译成小白能看懂的中文提示。"""
    hints = [
        ("error during connect", "无法连接 Docker：请确认 Docker Desktop 已启动"),
        ("cannot connect to the docker daemon", "无法连接 Docker：请确认 Docker Desktop 已启动"),
        ("is the docker daemon running", "Docker 守护进程未运行：请启动 Docker Desktop"),
        ("no space left on device", "磁盘空间不足：请清理 Docker 数据或磁盘后重试"),
        ("port is already allocated", "端口被占用：请更换端口或停止占用该端口的程序"),
        ("i/o timeout", "网络超时：拉取基础镜像失败，请检查网络或配置镜像加速器"),
        ("connection refused", "连接被拒绝：请检查网络或镜像仓库地址是否正确"),
        ("not found: manifest unknown", "找不到基础镜像：当前架构可能没有该镜像，试试单架构 amd64 构建"),
        ("denied: requested access to the resource is denied", "推送被拒绝：请先点「登录镜像仓库」完成 docker login"),
        ("unauthorized: authentication required", "推送被拒绝：请先点「登录镜像仓库」完成 docker login"),
        ("name unknown", "推送失败：仓库地址或命名空间不存在，请核对仓库地址"),
        ("failed to solve", "镜像构建失败：请看上方日志中第一个 ERROR 行定位具体原因"),
        ("dockerfile parse error", "Dockerfile 语法错误：请看上方日志中的行号提示"),
    ]
    low = msg.lower()
    for key, hint in hints:
        if key in low:
            return f"{hint}\n\n原始错误：{msg}"
    return msg


# ---------- 检测 ----------

def _read_text(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def detect_project_type(root: Path) -> str:
    # 优先级 1：项目自带 Dockerfile —— 直接尊重，不覆盖
    if (root / "Dockerfile").exists():
        return ProjectType.CUSTOM

    # Next.js（必须在 package.json 之前判断）
    if list(root.glob("next.config.*")):
        return ProjectType.NEXTJS

    # Django（必须在普通 Python 之前判断）
    if (root / "manage.py").exists():
        return ProjectType.DJANGO

    # Vite / Vue / Svelte 前端（必须在 package.json 之前判断）
    if (list(root.glob("vite.config.*")) or (root / "vue.config.js").exists()
            or (root / "svelte.config.js").exists()):
        return ProjectType.VITE

    # Deno（有 deno.json 才算，避免与纯 Node TS 项目混淆）
    if (root / "deno.json").exists() or (root / "deno.jsonc").exists():
        return ProjectType.DENO

    # Elixir / Phoenix
    if (root / "mix.exs").exists():
        return ProjectType.ELIXIR

    # Haskell（stack / cabal）
    if ((root / "stack.yaml").exists() or (root / "package.yaml").exists()
            or list(root.glob("*.cabal"))):
        return ProjectType.HASKELL

    # Julia
    if (root / "Project.toml").exists():
        return ProjectType.JULIA

    # Swift
    if (root / "Package.swift").exists():
        return ProjectType.SWIFT

    # Spring Boot（读取 pom.xml 内容判断，在普通 Maven 之前）
    if (root / "pom.xml").exists():
        pom = _read_text(root / "pom.xml")
        if "spring-boot" in pom:
            return ProjectType.SPRING_BOOT
        return ProjectType.MAVEN

    if any((root / f).exists() for f in ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"]):
        # FastAPI 专项：requirements 含 fastapi/uvicorn 且有 main.py
        req_text = ""
        if (root / "requirements.txt").exists():
            req_text = _read_text(root / "requirements.txt")
        if ("fastapi" in req_text or "uvicorn" in req_text) and (root / "main.py").exists():
            return ProjectType.FASTAPI
        return ProjectType.PYTHON

    if (root / "package.json").exists():
        return ProjectType.NODE
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
    if ptype == ProjectType.DENO:
        for f in ["main.ts", "mod.ts", "server.ts", "index.ts"]:
            if (root / f).exists():
                return f, False
    return None, False


def _write_dockerignore(root: Path, log: Optional[Callable[[str], None]] = None) -> None:
    """只在缺失时写入 .dockerignore，绝不覆盖用户自己的配置。"""
    p = root / ".dockerignore"
    if p.exists():
        if log:
            log("[detect] 项目已有 .dockerignore，保留不覆盖")
        return
    p.write_text(DOCKERIGNORE, encoding="utf-8", newline="\n")


def _load_template_override(ptype: str) -> Optional[str]:
    """加载用户自定义模板：优先环境变量 DOCKER_PACK_TEMPLATES 目录，
    其次 exe/脚本同级 templates/<ptype>.dockerfile。文件存在时覆盖内置模板。"""
    import sys
    candidates = []
    env_dir = os.environ.get("DOCKER_PACK_TEMPLATES")
    if env_dir:
        candidates.append(Path(env_dir) / f"{ptype}.dockerfile")
    exe_dir = Path(sys.argv[0]).resolve().parent
    candidates.append(exe_dir / "templates" / f"{ptype}.dockerfile")
    candidates.append(Path(__file__).resolve().parent / "templates" / f"{ptype}.dockerfile")
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            continue
    return None


def prepare_dockerfile(root: Path, ptype: str, port: int, log: Optional[Callable[[str], None]] = None) -> None:
    """在项目目录生成 Dockerfile 和 .dockerignore（调用方应传入构建用的临时副本目录）。

    - 项目已有 Dockerfile：保留不覆盖，只补 .dockerignore
    - 项目已有 .dockerignore：保留用户自己的，不覆盖
    - 内置模板可被 templates/<ptype>.dockerfile 自定义模板覆盖（支持 {port} 占位符）
    """
    # 已有 Dockerfile：尊重用户
    if ptype == ProjectType.CUSTOM:
        if log:
            log("[detect] 项目自带 Dockerfile，直接复用，不覆盖")
        _write_dockerignore(root, log)
        return

    override = _load_template_override(ptype)
    if override is not None:
        tpl = override
        if log:
            log(f"[detect] 使用自定义模板覆盖内置 {ptype} 模板")
    else:
        tpl = DOCKERFILES.get(ptype)
    if tpl:
        # 用 replace 而非 str.format：模板中可安全出现 {} 花括号（如 Rust 的 fn main() {}）
        content = tpl.replace("{port}", str(port))
    else:
        content = f"FROM alpine:3.19\nWORKDIR /app\nCOPY . .\nEXPOSE {port}\nCMD [\"sh\"]\n"

    # Django 专项：解析 wsgi 模块名（xxx/wsgi.py → xxx.wsgi）
    if ptype == ProjectType.DJANGO:
        wsgi_module = None
        for p in root.rglob("wsgi.py"):
            rel = p.relative_to(root)
            parts = list(rel.parts)[:-1]  # 去掉 wsgi.py
            if parts:
                wsgi_module = ".".join(parts) + ".wsgi"
                break
        if not wsgi_module:
            wsgi_module = "project.wsgi"
            if log:
                log(f"[warn] 未找到 wsgi.py，Django CMD 将使用占位模块名 {wsgi_module}，请手动修改")
        content = content.replace("{wsgi_module}", wsgi_module)

    # Python 家族：没有 requirements.txt（pyproject.toml / setup.py / Pipfile 项目）时，
    # 依赖阶段改为整包构建，避免 COPY requirements.txt 直接失败
    if ptype in (ProjectType.PYTHON, ProjectType.DJANGO, ProjectType.FASTAPI) \
            and not (root / "requirements.txt").exists():
        builder_variants = [
            ("COPY requirements.txt .\nRUN --mount=type=cache,target=/root/.cache/pip \\\n pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt",
             "COPY . .\nRUN --mount=type=cache,target=/root/.cache/pip \\\n pip wheel --no-cache-dir --wheel-dir /wheels ."),
            ("COPY requirements.txt .\nRUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt",
             "COPY . .\nRUN pip wheel --no-cache-dir --wheel-dir /wheels ."),
        ]
        runner_old = ("COPY --from=builder /wheels /wheels\n"
                      "COPY requirements.txt .\n"
                      "RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \\\n"
                      " && rm -rf /wheels\n"
                      "COPY . .")
        runner_new = ("COPY --from=builder /wheels /wheels\n"
                      "COPY . .\n"
                      "RUN pip install --no-cache-dir --no-index --find-links=/wheels . \\\n"
                      " && rm -rf /wheels")
        replaced = False
        for old, new in builder_variants:
            if old in content:
                content = content.replace(old, new)
                replaced = True
                break
        if replaced and runner_old in content:
            content = content.replace(runner_old, runner_new)
            if log:
                log("[detect] 未找到 requirements.txt，已切换为 pyproject/setup.py 整包构建模式")
        elif log:
            log("[warn] 未找到 requirements.txt，请确认项目依赖声明方式（支持 requirements.txt / pyproject.toml / setup.py）")

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
        elif ptype == ProjectType.DENO:
            content = content.replace('"main.ts"', f'"{start_file}"')

    (root / "Dockerfile").write_text(content, encoding="utf-8", newline="\n")
    _write_dockerignore(root, log)


# ---------- Git clone ----------

def is_git_url(s: str) -> bool:
    s = s.strip()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("git@") or s.endswith(".git")


def git_clone(url: str, dest: Path, log: Callable[[str], None], branch: str = "") -> Path:
    """clone 仓库到 dest，返回项目根目录（可能是 dest 本身或其子目录）。branch 可指定分支/标签。"""
    cmd = ["git", "clone", "--depth", "1"]
    if branch.strip():
        cmd += ["--branch", branch.strip()]
    cmd += [url, str(dest)]
    log(f"[git] 正在克隆 {url} ..." + (f"（分支/标签: {branch.strip()}）" if branch.strip() else ""))
    proc = subprocess.Popen(
        cmd,
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
# BuildKit 输出格式：`#5 [2/7] COPY package*.json ./`
BK_STEP_RE = re.compile(r"#\d+\s+\[(\d+)/(\d+)\]")


class BuildCancelled(Exception):
    """用户取消构建时抛出"""


def generate_compose(
    image_name: str,
    tag: str,
    port: int,
    include_mysql: bool = False,
    include_redis: bool = False,
    db_password: str = "change-me",
) -> str:
    """生成 docker-compose.yml 文本（app 服务 + 可选 MySQL/Redis）"""
    full_tag = f"{image_name}:{tag}"

    # 先汇总 app 服务的环境变量与依赖，避免生成重复的 YAML 键（后者会覆盖前者导致配置丢失）
    app_env = ["      - TZ=Asia/Shanghai"]
    app_depends: list[str] = []
    if include_mysql:
        app_depends.append("mysql")
        app_env += [
            "      - DB_HOST=mysql",
            "      - DB_PORT=3306",
            "      - DB_NAME=app",
            "      - DB_USER=root",
            f"      - DB_PASSWORD={db_password}",
        ]
    if include_redis:
        app_depends.append("redis")
        app_env += [
            "      - REDIS_HOST=redis",
            "      - REDIS_PORT=6379",
        ]

    lines = [
        'version: "3.8"',
        "",
        "services:",
        "  app:",
        f"    image: {full_tag}",
        f"    container_name: {image_name.replace('/', '-')}",
        "    restart: unless-stopped",
        "    ports:",
        f'      - "{port}:{port}"',
        "    environment:",
        *app_env,
    ]
    if app_depends:
        lines.append("    depends_on:")
        lines += [f"      - {d}" for d in app_depends]
    lines += ["    # volumes:", "    #   - app-data:/data"]
    if include_mysql:
        lines += [
            "",
            "  mysql:",
            "    image: mysql:8.0",
            "    restart: unless-stopped",
            "    environment:",
            "      - MYSQL_ROOT_PASSWORD=" + db_password,
            "      - MYSQL_DATABASE=app",
            "    volumes:",
            "      - mysql-data:/var/lib/mysql",
            "    ports:",
            '      - "3306:3306"',
        ]
    if include_redis:
        lines += [
            "",
            "  redis:",
            "    image: redis:7-alpine",
            "    restart: unless-stopped",
            "    volumes:",
            "      - redis-data:/data",
            "    ports:",
            '      - "6379:6379"',
        ]
    lines += ["", "volumes:"]
    if include_mysql:
        lines += ["  mysql-data:"]
    if include_redis:
        lines += ["  redis-data:"]
    if not (include_mysql or include_redis):
        lines += ["  # app-data:"]
    return "\n".join(lines) + "\n"


def build_and_export(
    source_dir: Path,
    image_name: str,
    tag: str,
    port: int,
    platforms: list[str],
    output_tar: Path,
    log: Callable[[str], None],
    progress: Callable[[float, str], None],
    push_registry: str = "",      # 例如 registry.cn-hangzhou.aliyuncs.com/your-ns
    push: bool = False,
    build_args: Optional[dict[str, str]] = None,        # 额外构建参数
    subdir: str = "",                                   # monorepo 子目录（相对源码根目录）
    compress: bool = False,                             # 导出后压缩为 .tar.gz
    should_cancel: Optional[Callable[[], bool]] = None,  # 返回 True 表示用户请求取消
) -> Path:
    """
    构建镜像并导出为 tar 文件，返回最终产物路径。
    - 在用户源码的临时副本中构建，不修改项目目录
    - 单架构：docker build → docker save → (可选) 压缩 → (可选) docker push
    - 多架构：docker buildx build --output type=oci,dest=...（OCI 格式，不可 docker load）
    """
    try:
        docker_preflight()

        # monorepo：只构建指定子目录
        if subdir.strip():
            sub = source_dir / subdir.strip().strip("/\\")
            if not sub.is_dir():
                raise RuntimeError(f"子目录不存在: {subdir}（相对源码根目录）")
            source_dir = sub

        # 在源码的临时副本中构建：绝不往用户项目里写 Dockerfile / .dockerignore，构建完自动清理
        build_dir = _make_build_copy(source_dir)
        log(f"[info] 构建上下文已准备在临时目录（源码目录不会被修改）: {build_dir}")
        try:
            ptype = detect_project_type(build_dir)
            log(f"[detect] 项目类型: {ptype}")
            prepare_dockerfile(build_dir, ptype, port, log=log)
            log(f"[detect] Dockerfile / .dockerignore 就绪")

            multi_arch = len(platforms) > 1
            if push_registry:
                push_registry = push_registry.rstrip("/")
            full_tag = f"{image_name}:{tag}"
            push_tag = f"{push_registry}/{full_tag}" if push_registry else full_tag

            build_arg_flags: list[str] = []
            for k, v in (build_args or {}).items():
                build_arg_flags += ["--build-arg", f"{k}={v}"]

            if multi_arch:
                platform_str = ",".join(platforms)
                log(f"[buildx] 多架构构建: {platform_str}")
                cmd = [
                    "docker", "buildx", "build",
                    "--platform", platform_str,
                    "-t", full_tag,
                    "--output", f"type=oci,dest={output_tar}",
                    *build_arg_flags,
                    str(build_dir),
                ]
                _run_streaming(cmd, build_dir, log, progress, multi_arch=True, should_cancel=should_cancel)
                # OCI 产物不是 docker save 格式，docker load 无法导入，必须明确告知用户
                log(f"[save] 多架构 OCI 产物已导出: {output_tar}")
                log("[hint] ⚠ 注意：OCI 格式归档不能直接用 docker load 导入（docker load 只认单架构 docker save 格式）。")
                log("[hint]   推荐用法：推送到镜像仓库，目标机器 docker pull 拉取；")
                log("[hint]   或者在目标架构的机器上分别用本工具做单架构构建（产物可直接 docker load）。")
            else:
                platform = platforms[0]
                log(f"[build] 单架构构建: {platform}")
                cmd = ["docker", "build", "--platform", platform, "-t", full_tag,
                       *build_arg_flags, str(build_dir)]
                _run_streaming(cmd, build_dir, log, progress, multi_arch=False, should_cancel=should_cancel)
                if should_cancel and should_cancel():
                    raise BuildCancelled()
                log(f"[save] 导出镜像到 {output_tar}")
                rc = subprocess.run(
                    ["docker", "save", "-o", str(output_tar), full_tag],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                if rc.returncode != 0:
                    raise RuntimeError(f"docker save 失败: {rc.stdout}")
                # 可选：压缩为 .tar.gz，方便传输与保存
                if compress:
                    if should_cancel and should_cancel():
                        raise BuildCancelled()
                    gz_path = output_tar.with_name(output_tar.name + ".gz")
                    log(f"[save] 压缩为 {gz_path.name} ...")
                    with open(output_tar, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
                        shutil.copyfileobj(f_in, f_out, 1024 * 1024)
                    output_tar.unlink()
                    output_tar = gz_path
                # 单架构镜像已进入本地仓库，可以做运行自检
                _self_check(full_tag, port, log)

            # 可选推送（仅单架构；多架构产物未进本地仓库，无法 push）
            if push:
                if multi_arch:
                    log("[push] 多架构 OCI 产物未进入本地仓库，跳过推送（如需多架构推送请用 buildx --push）")
                else:
                    if not push_registry:
                        raise RuntimeError("请填写镜像仓库地址（如 registry.cn-hangzhou.aliyuncs.com/your-ns）后再推送")
                    if should_cancel and should_cancel():
                        raise BuildCancelled()
                    log(f"[push] 推送镜像: {push_tag}")
                    rc = subprocess.run(
                        ["docker", "push", push_tag],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                    )
                    if rc.returncode != 0:
                        raise RuntimeError(f"docker push 失败（请先 docker login）: {rc.stdout}")
                    log(f"[push] ✓ 推送完成: {push_tag}")

            log(f"[done] 镜像已导出: {output_tar} ({output_tar.stat().st_size/1024/1024:.1f} MB)")
            return output_tar
        finally:
            shutil.rmtree(build_dir, ignore_errors=True)
    except BuildCancelled:
        raise
    except RuntimeError as e:
        # 常见英文报错翻译成中文提示，降低小白排障成本
        raise RuntimeError(friendly_error(str(e))) from e


def _make_build_copy(source_dir: Path) -> Path:
    """把源码复制到临时目录作为构建上下文，绝不修改用户项目目录。

    复制时排除体积大且构建时不需要的目录（.git / node_modules / 各语言构建产物等），
    这些目录本来也会被 .dockerignore 排除在镜像之外，不影响构建结果。
    """
    ignored = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
               "env", "dist", "build", "target", "vendor", ".gradle", ".idea",
               ".vscode", "bin", "obj", ".next", "out", ".dart_tool"}
    dest = Path(tempfile.mkdtemp(prefix="docker_pack_build_"))
    shutil.copytree(source_dir, dest, dirs_exist_ok=True,
                    ignore=lambda d, names: [n for n in names if n in ignored])
    return dest


def cleanup_old_outputs(out_dir: Path, keep: int = 20) -> None:
    """产物目录自动清理：只保留最近 keep 个 tar/tar.gz，删除更早的，避免无限占盘。"""
    try:
        out_dir = Path(out_dir)
        if not out_dir.is_dir():
            return
        files = [p for p in out_dir.glob("*.tar*") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep:]:
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _self_check(image_tag: str, port: int, log: Callable[[str], None]) -> None:
    """
    构建后自检：docker run 启动容器，探测端口是否可达，最后自动清理。
    任何失败都不影响产物导出，只打日志提醒。
    """
    import random
    container = f"packcheck_{os.getpid()}_{int(time.time())}"
    log(f"[check] 自检：启动容器 {container} 验证镜像可运行...")
    rc = subprocess.run(
        ["docker", "run", "-d", "--name", container, "-p", f"127.0.0.1::{port}", image_tag],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    if rc.returncode != 0:
        log(f"[check] ⚠ 容器启动失败（{rc.stdout.strip()}），跳过自检，不影响产物")
        return

    # 查询实际映射的宿主机端口
    host_port = None
    out = subprocess.run(
        ["docker", "port", container],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    m = re.search(r"127\.0\.0\.1:(\d+)", out.stdout)
    if m:
        host_port = int(m.group(1))

    # 轮询最多 30 秒：容器存活 + 端口可达
    alive = False
    reachable = False
    last_logs = ""
    for _ in range(15):
        time.sleep(2)
        insp = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        alive = insp.stdout.strip() == "true"
        if not alive:
            logs = subprocess.run(
                ["docker", "logs", "--tail", "25", container],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            ).stdout
            last_logs = logs[-1200:]
            break
        if host_port:
            try:
                with socket.create_connection(("127.0.0.1", host_port), timeout=2):
                    reachable = True
                    break
            except OSError:
                pass

    if reachable:
        log(f"[check] ✓ 自检通过：容器正常运行，端口 {host_port} 可访问")
    elif alive:
        log(f"[check] △ 容器存活但端口 {host_port or port} 暂不可达（服务可能启动较慢），请以实际运行为准")
    else:
        log(f"[check] ✗ 自检失败：容器提前退出，最近日志：\n{last_logs}")

    subprocess.run(["docker", "rm", "-f", container],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"[check] 自检容器已清理")


def _run_streaming(
    cmd: list,
    cwd: Path,
    log: Callable[[str], None],
    progress: Callable[[float, str], None],
    multi_arch: bool,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> None:
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None

    # 用独立线程读子进程输出，主循环才有机会响应取消请求
    out_queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def _reader():
        for line in proc.stdout:
            out_queue.put(line)
        out_queue.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    current, total = 0, 1
    cancelled = False
    while True:
        try:
            line = out_queue.get(timeout=0.2)
        except queue.Empty:
            if should_cancel and should_cancel():
                cancelled = True
                break
            continue
        if line is None:  # 子进程输出结束
            break
        line = line.rstrip()
        if not line:
            continue
        log(line)
        # 同时兼容旧版 `Step n/m:` 与 BuildKit `#N [n/m]` 两种输出格式
        m = STEP_RE.search(line) or BK_STEP_RE.search(line)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            pct = current / total if total else 0
            progress(pct, f"Step {current}/{total}")
    if cancelled:
        proc.kill()
        proc.wait()
        raise BuildCancelled()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"命令执行失败，退出码 {proc.returncode}（详见上方日志）")
    if not multi_arch:
        progress(1.0, "完成")
