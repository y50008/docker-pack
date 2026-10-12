#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.py — Docker 打包核心逻辑
被 GUI 调用，通过回调函数推送日志行和进度。
"""

import os
import re
import shutil
import socket
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
RUN --mount=type=cache,target=/root/.cache/pip \\
 pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \\
 pip wheel --wheel-dir /wheels -r requirements.txt

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
COPY go.mod go.sum ./
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
 && npm ci --only=production \\
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
EXPOSE 80
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
        # wsgi_module 先保留占位，Django 类型随后单独解析替换
        content = tpl.format(port=port, wsgi_module="{wsgi_module}")
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
    lines = [
        'version: "3.8"',
        "",
        "services:",
        f"  app:",
        f"    image: {full_tag}",
        f"    container_name: {image_name.replace('/', '-')}",
        "    restart: unless-stopped",
        f'    ports:',
        f'      - "{port}:{port}"',
        "    environment:",
        "      - TZ=Asia/Shanghai",
    ]
    if include_mysql:
        lines += [
            "    depends_on:",
            "      - mysql",
            "    environment:",
            "      - DB_HOST=mysql",
            "      - DB_PORT=3306",
            "      - DB_NAME=app",
            f"      - DB_PASSWORD={db_password}",
        ]
    if include_redis:
        lines += [
            "    depends_on:",
            "      - redis",
            "    environment:",
            "      - REDIS_HOST=redis",
            "      - REDIS_PORT=6379",
        ]
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
) -> None:
    """
    构建镜像并导出为 tar 文件。
    - 单架构：docker build → docker save → (可选) docker push
    - 多架构：docker buildx build --output type=oci,dest=...
    """
    if shutil.which("docker") is None:
        raise RuntimeError("未检测到 docker 命令，请先安装并启动 Docker Desktop")

    ptype = detect_project_type(source_dir)
    log(f"[detect] 项目类型: {ptype}")
    prepare_dockerfile(source_dir, ptype, port, log=log)
    log(f"[detect] Dockerfile / .dockerignore 就绪")

    multi_arch = len(platforms) > 1
    if push_registry:
        push_registry = push_registry.rstrip("/")
    full_tag = f"{image_name}:{tag}"
    push_tag = f"{push_registry}/{full_tag}" if push_registry else full_tag

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
        # 单架构镜像已进入本地仓库，可以做运行自检
        _self_check(full_tag, port, log)

    # 可选推送（仅单架构；多架构产物未进本地仓库，无法 push）
    if push:
        if multi_arch:
            log("[push] 多架构 OCI 产物未进入本地仓库，跳过推送（如需多架构推送请用 buildx --push）")
        else:
            if not push_registry:
                raise RuntimeError("请填写镜像仓库地址（如 registry.cn-hangzhou.aliyuncs.com/your-ns）后再推送")
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
