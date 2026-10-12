<div align="center">

# 🐳 Docker Pack GUI

**一键将项目源码打包成 Docker 镜像的可视化工具**

作者：y50008 ｜ 来源：www.52pojie.com ｜ 开源地址：https://github.com/y50008/docker-pack

![Version](https://img.shields.io/badge/version-1.2.0-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-green)
![Python](https://img.shields.io/badge/python-3.10%2B-yellow)
![Docker](https://img.shields.io/badge/docker-required-2496ED)

</div>

---

## 📖 项目简介

Docker Pack GUI 是一款 **Windows 桌面端**的 Docker 镜像打包工具。你只需要选择项目源码目录（或输入 Git 仓库地址），点击「开始打包」，工具会自动识别项目语言、生成多阶段 Dockerfile、调用 Docker 构建镜像，并最终导出为 `.tar` 文件供你下载保存。

**无需手写 Dockerfile，无需记 docker build 命令，小白也能打出生产级镜像。**

> 🆕 **v1.2 新增**：一键生成 docker-compose.yml、构建后推送镜像到仓库、打包历史记录（一键重新打包）、BuildKit 依赖缓存加速。
>
> 🆕 **v1.1 新增**：专项框架模板（Next.js / Django / FastAPI / Spring Boot）、构建后容器自检、**Web 部署版**（浏览器访问，多人共用）。

![工具界面示意图](docs/screenshot.png)

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 🎯 **自动识别项目类型** | 支持 17 种语言/框架（含 4 个专项框架模板），无需手动配置 |
| 🎨 **可视化界面** | 原生 Windows GUI，双击 exe 即用，无需安装 Python |
| 🌐 **支持 Git 仓库** | 直接输入 GitHub/Gitee 地址，自动 clone 后打包 |
| 🏗️ **多架构构建** | 支持 amd64 / arm64 / armv7 / riscv64 任意组合 |
| ⏱️ **实时进度** | 进度条 + 已用时 + 预计剩余时间 + 实时日志 |
| 📦 **一键导出 tar** | 构建完成后点下载，选择保存位置即可 |
| 🩺 **构建后自检** | 打包完自动运行容器 + 探测端口，验证镜像真能跑 |
| 🧩 **一键 Compose** | 打包完顺手生成 docker-compose.yml（可选附带 MySQL/Redis） |
| 🚀 **镜像推送** | 支持推送到 Docker Hub / 阿里云 ACR / 腾讯云 CCR |
| 🕘 **历史记录** | 自动记录每次打包，一键回填配置重新打包 |
| ⚡ **构建加速** | BuildKit 依赖缓存挂载，二次构建依赖层秒级复用 |
| 🌍 **Web 部署版** | 工具本身可 Docker 化部署，浏览器操作、多人共用 |
| 🇨🇳 **国内镜像源** | npm / pip / Go proxy 默认切国内源，构建更快 |
| 📦 **多阶段构建** | 自动生成精简镜像，体积最小化 |

---

## 🚀 快速开始

### 环境要求

- Windows 10 / 11
- 已安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- 如需打包 Git 仓库，本机需安装 [Git](https://git-scm.com/)

### 使用步骤

1. **下载 `DockerPack.exe`**（在 [Releases](../../releases) 页面）
2. **双击运行**，无需安装
3. **选择源码来源**：
   - 📁 本地目录：点「浏览...」选择项目文件夹
   - 🌐 项目地址：输入 GitHub/Gitee 仓库 URL
4. **配置镜像**：镜像名、标签（tag）、暴露端口
5. **选择目标架构**：默认 amd64，需要 ARM 服务器就勾选 arm64
6. **（可选）部署选项**：勾选「生成 docker-compose.yml」可一并产出部署编排文件；勾选「构建后推送镜像」并填仓库地址，打包完自动推送
7. **点击「开始打包」**，观察实时日志和进度
8. **打包完成后点「下载打包好的镜像文件」**，选择保存位置；「历史记录」页可一键重新打包

---

## 🧩 部署选项（v1.2 新增）

### 一键生成 docker-compose.yml

勾选「生成 docker-compose.yml」后，打包完成会自动生成编排文件，可选附带 **MySQL 8** 和 **Redis 7** 服务：

```yaml
version: "3.8"
services:
  app:
    image: my-app:latest
    container_name: my-app
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=Asia/Shanghai
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: change-me
      MYSQL_DATABASE: app
    volumes:
      - mysql-data:/var/lib/mysql
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
volumes:
  mysql-data:
  redis-data:
```

部署时只需一条命令：`docker compose up -d`。

### 镜像推送

勾选「构建后推送镜像」并填写仓库地址（如 `registry.cn-hangzhou.aliyuncs.com/你的命名空间`），构建完成后自动执行 `docker push`：

| 目标 | 仓库地址示例 |
|---|---|
| Docker Hub | `你的用户名`（推送到 `你的用户名/镜像名:标签`） |
| 阿里云 ACR | `registry.cn-hangzhou.aliyuncs.com/命名空间` |
| 腾讯云 CCR | `ccr.ccs.tencentcloud.com/命名空间` |

> 💡 推送前请先在本机执行 `docker login` 登录对应仓库；推送仅支持单架构构建（多架构 OCI 产物不进入本地仓库，无法 push）。

### 历史记录

每次打包自动记录（时间、镜像、端口、架构、来源、状态），存在 `%APPDATA%\DockerPack\history.json`。在「历史记录」页选中一条，点「用选中记录重新打包」即可回填全部配置并重新构建。

### 构建加速

Node / Python / Maven / Gradle / Go 模板已内置 **BuildKit 依赖缓存挂载**（`--mount=type=cache`），依赖层缓存可跨构建复用，二次打包速度大幅提升。需 Docker 20.10+（Docker Desktop 默认支持）。

---

## 🗂️ 支持的项目类型

### 专项框架模板（v1.1 新增）

| 标志文件 | 识别为 | 专项优化 |
|---|---|---|
| `next.config.*` | **Next.js** | SSR 模式：`.next` 产物 + `npm start`，非静态导出 |
| `manage.py` | **Django** | 自动 migrate + collectstatic + gunicorn 4 worker，自动解析 wsgi 模块 |
| `requirements.txt` 含 fastapi/uvicorn + `main.py` | **FastAPI** | uvicorn 4 worker 启动 |
| `pom.xml` 含 spring-boot | **Spring Boot** | 非 root 用户运行 + JRE 21，更安全 |

### 通用类型

| 标志文件 | 识别为 | 基础镜像策略 |
|---|---|---|
| `Dockerfile`（已有） | 项目自带 Dockerfile | **直接复用，不覆盖** |
| `package.json` | Node.js（含 TS/React/Vue） | node:20-alpine 多阶段 |
| `requirements.txt` / `pyproject.toml` | Python | python:3.11-slim 多阶段 |
| `pom.xml` | Java Maven | maven:3.9 + JRE 21 |
| `build.gradle` | Java Gradle / Spring Boot | gradle:8 + JRE 21 |
| `go.mod` | Go | golang:1.22 + alpine |
| `*.csproj` / `*.sln` | .NET | dotnet/sdk:8 + aspnet:8 |
| `composer.json` | PHP | composer:2 + php:8.3-apache |
| `Gemfile` | Ruby | ruby:3.2-alpine |
| `Cargo.toml` | Rust | rust:1.77-alpine + musl |
| `CMakeLists.txt` | C/C++ | gcc:13 + cmake |
| `pubspec.yaml` | Flutter Web | Flutter SDK + nginx |
| `index.html`（兜底） | 静态网站 | nginx:alpine |

> 💡 **智能兼容**：如果项目根目录已经有 Dockerfile，工具会直接使用它，不会覆盖你写好的配置。

---

## 🩺 构建后自检（v1.1 新增）

单架构构建完成后，工具会自动：

1. `docker run` 启动刚构建的镜像
2. 轮询 30 秒，检查容器是否存活
3. 探测映射端口是否可访问
4. 自动清理测试容器（不留垃圾）

结果在日志中显示为 `✓ 自检通过` / `△ 容器存活但端口暂不可达` / `✗ 容器提前退出（附最近日志）`。**自检失败不影响 tar 导出**，只提醒你镜像可能有问题。

---

## 🌍 Web 部署版（v1.1 新增）

工具本身可以 Docker 化部署，浏览器访问、多人共用：

```bash
cd docker-pack-gui/web
docker build -t docker-pack-web .
docker run -d -p 8000:8000 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /data/docker-pack-web:/data \
    docker-pack-web
```

然后浏览器访问 `http://服务器IP:8000`，功能和 exe 版一致（选目录/输仓库地址、选架构、实时日志、下载 tar）。

**本地开发运行 Web 版**（需 Python 3.10+）：

```bash
pip install flask
python web_app.py          # 默认端口 8000
```

---

## 🏗️ 目标架构说明

| 架构 | 适用场景 |
|---|---|
| `linux/amd64` | 普通 PC、绝大多数云服务器（x86_64）✅ 默认 |
| `linux/arm64` | AWS Graviton、Apple M 系列、阿里云 ARM、树莓派 5 |
| `linux/arm/v7` | 32 位 ARM：树莓派 3/4 老系统、IoT 设备 |
| `linux/riscv64` | RISC-V 开发板、边缘计算 |
| **全部** | 一次打 4 种架构（QEMU 模拟，较慢） |

> ⚠️ 在 Windows 上打 ARM 架构镜像会走 QEMU 模拟，速度比原生 amd64 慢 5-10 倍，属于正常现象。

---

## 📦 产物使用

打包完成后你会得到一个 `.tar` 文件，在目标服务器上导入：

```bash
# 导入镜像
docker load -i my-app_v1.0.tar

# 查看镜像
docker images

# 运行容器（注意端口映射要和你填的端口一致）
docker run -d -p 8080:8080 my-app:v1.0

# 浏览器访问
http://服务器IP:8080
```

---

## 🛠️ 从源码运行

```bash
# 克隆仓库
git clone https://github.com/y50008/docker-pack.git
cd docker-pack-gui

# 直接运行（需要 Python 3.10+）
python pack_gui.py
```

### 打包成 exe

```bash
pip install pyinstaller
# 注意：--collect-all tkinter 必须带上，否则 exe 会因缺少 Tcl/Tk 脚本库报 "No module named 'tkinter'"
pyinstaller --onefile --windowed --name DockerPack --collect-all tkinter pack_gui.py
```

生成的 exe 在 `dist/DockerPack.exe`。

---

## 📁 项目结构

```
docker-pack-gui/
├── pack_gui.py      # tkinter GUI 主程序（exe 版界面）
├── core.py          # 核心逻辑：项目检测、Dockerfile 生成、git clone、docker build/save、构建后自检
├── web_app.py       # Web 版后端（Flask API，复用 core.py）
├── templates/
│   └── index.html   # Web 版前端页面
├── web/
│   ├── Dockerfile   # Web 版自身镜像（部署用）
│   └── requirements.txt
├── docs/
│   └── screenshot.png   # 界面示意图
├── README.md        # 本文件
├── .gitignore
└── dist/
    └── DockerPack.exe   # 打包好的可执行程序
```

---

## 📝 License

本项目仅供学习交流使用，转载请注明出处。

作者：**y50008** ｜ 来源：**www.52pojie.com**
