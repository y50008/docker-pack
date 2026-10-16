<div align="center">

# 🐳 Docker Pack GUI

**一键将项目源码打包成 Docker 镜像的可视化工具 — 双击即用，无需安装任何依赖环境**

作者：y50008 ｜ 开源地址：https://github.com/y50008/docker-pack

![Version](https://img.shields.io/badge/version-1.4.0-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-green)
![Docker](https://img.shields.io/badge/docker-required-2496ED)
![Framework](https://img.shields.io/badge/支持框架-23种-orange)
![CI](https://img.shields.io/badge/CI-pytest%20%2F%20GitHub%20Actions-brightgreen)

</div>

---

## 📖 项目简介

Docker Pack GUI 是一款 **Windows 桌面端**的 Docker 镜像打包工具。**下载 exe 后双击即可打开，不需要安装 Python、不需要配置任何环境**（工具已把所有运行文件打包进 exe）。

你只需要选择项目源码目录（或输入 Git 仓库地址），点击「开始打包」，工具会自动：

1. **识别项目语言/框架**（支持 23 种，见下文）
2. **自动生成多阶段 Dockerfile**（国内镜像源加速，依赖缓存复用）
3. **调用 Docker 构建镜像**（单架构 / 多架构可选，实时解析 BuildKit 进度）
4. **导出为 `.tar`（或 `.tar.gz`）文件**供你下载保存
5. **可选**：构建后自检、一键生成 docker-compose.yml、推送到镜像仓库

> 无需手写 Dockerfile，无需记 docker build 命令，小白也能打出生产级镜像。

### ✨ v1.4 新功能

- **随时取消构建**：构建过程中可点「取消构建」，立即终止构建进程，不再只能关程序
- **登录镜像仓库**：界面上直接完成 `docker login`，无需切到命令行
- **Git 分支/标签**：克隆仓库时可指定分支或 tag
- **monorepo 子目录**：只构建仓库中的指定子目录
- **构建参数注入**：支持每行一个 `KEY=VALUE`，自动传给 `docker build --build-arg`
- **导出压缩**：一键压缩为 `.tar.gz`，体积更小、传输更方便
- **产物目录可配置 + 自动清理**：产物保存位置自选，默认只保留最近 20 个归档
- **自定义 Dockerfile 模板**：可用 `templates/<类型>.dockerfile` 或 `DOCKER_PACK_TEMPLATES` 环境变量覆盖内置模板
- **输入校验 + 错误中文化**：镜像名/标签/端口即时校验；守护进程未启动、磁盘不足、端口占用、网络超时等常见英文报错自动翻译成中文提示，并在构建前做 Docker 环境体检
- **Web 版安全加固**：访问令牌鉴权、服务器路径白名单、zip 上传解压、功能与桌面版对齐，内置生产级 WSGI 服务器（waitress）

![工具界面示意图](docs/screenshot.png)

---

## 🚀 快速开始（3 步上手）

### 第 1 步：下载并双击运行

- 下载 [Releases](../../releases) 页面中的 `DockerPack.exe`
- **双击运行，无需安装**——exe 已内置完整运行环境（Python + tkinter 界面库全部打包在文件里）
- 杀毒软件若提示，选择信任即可（PyInstaller 打包的程序首次运行常见此提示）

### 第 2 步：选择源码

| 方式 | 操作 |
|---|---|
| 📁 本地目录 | 点「浏览...」选择项目文件夹，工具会自动把目录名填成镜像名 |
| 🌐 项目地址 | 粘贴 GitHub / Gitee / 自建 Git 仓库的 HTTPS 或 SSH 地址 |

### 第 3 步：开始打包

1. 填镜像名、标签（tag）、暴露端口（输入不合法会立即提示）
2. 勾选目标架构（默认 amd64；需要 ARM 服务器就勾 arm64）
3. （可选）在「部署选项」里勾选：生成 docker-compose.yml / 构建后推送 / 压缩为 .tar.gz，
   并按需填写分支、子目录、构建参数、产物目录
4. 点「开始打包」→ 看实时日志与进度条（BuildKit 进度也能正确显示）
5. 构建过程中可随时点「取消构建」；完成后点「下载打包好的镜像文件」，选择保存位置即可

---

## ⚙️ 环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10 / 11 | 工具本身无需安装任何 Python 环境 |
| Docker | 已安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 打包动作由 Docker 执行，这是唯一依赖 |
| Git（可选） | 已安装 [Git](https://git-scm.com/) | 仅在输入 Git 仓库地址时需要 |
| 网络 | 能访问 Docker Hub / 国内镜像源 | 首次构建需拉取基础镜像 |

> ✅ **exe 双击即用**：Python、tkinter、Tcl/Tk 已全部打包进单个 exe（11MB），目标机器上无需安装任何开发环境。

---

## 🗂️ 支持的项目类型（23 种）

### 专项框架模板（自动识别 + 专属优化）

| 标志文件 | 识别为 | 专项优化 |
|---|---|---|
| `next.config.*` | **Next.js** | SSR 模式：`.next` 产物 + `npm start` |
| `manage.py` | **Django** | 自动 migrate + collectstatic + gunicorn，自动解析 wsgi 模块 |
| `requirements.txt` 含 fastapi + `main.py` | **FastAPI** | uvicorn 多 worker 启动 |
| `pom.xml` 含 spring-boot | **Spring Boot** | 非 root 用户运行 + JRE 21 |
| `vite.config.*` / `vue.config.js` / `svelte.config.js` | **Vite 前端 SPA** | node 构建 → nginx 托管（自动按所填端口监听） |
| `deno.json` / `deno.jsonc` | **Deno** | 自动识别入口 main.ts / mod.ts / server.ts |
| `mix.exs` | **Elixir / Phoenix** | mix 编译 + 常驻运行 |
| `stack.yaml` / `package.yaml` / `*.cabal` | **Haskell** | stack 构建 + 精简 debian 运行 |
| `Project.toml` | **Julia** | Pkg 实例化 + 运行 |
| `Package.swift` | **Swift** | swift build release |

### 通用类型（按标志文件识别）

| 标志文件 | 识别为 | 基础镜像策略 |
|---|---|---|
| `Dockerfile`（已有） | 项目自带 | **直接复用，不覆盖** |
| `package.json` | Node.js（含 TS/React/Vue） | node:20-alpine 多阶段 |
| `requirements.txt` / `pyproject.toml` | Python | python:3.11-slim 多阶段 |
| `pom.xml` | Java Maven | maven:3.9 + JRE 21 |
| `build.gradle(.kts)` | Java Gradle / Spring Boot | gradle:8 + JRE 21 |
| `go.mod` | Go | golang:1.22 + alpine |
| `*.csproj` / `*.sln` | .NET | dotnet/sdk:8 + aspnet:8 |
| `composer.json` | PHP | composer:2 + php:8.3-apache |
| `Gemfile` | Ruby | ruby:3.2-alpine |
| `Cargo.toml` | Rust | rust:1.77-alpine + musl |
| `CMakeLists.txt` | C/C++ | gcc:13 + cmake |
| `pubspec.yaml` | Flutter Web | Flutter SDK + nginx |
| `index.html`（兜底） | 静态网站 | nginx:alpine |

> 💡 **智能兼容**：如果项目根目录已有 Dockerfile，工具直接使用它，不覆盖你写好的配置。
>
> 🧹 **零污染**：构建在源码的临时副本中进行，不会往你的项目目录写入 Dockerfile / .dockerignore；项目已有 `.dockerignore` 时也会原样保留。
>
> 🔧 少数小众模板（Haskell/Swift 等）的入口文件名若与项目不同，生成的 Dockerfile 末尾有注释提示，按注释修改即可。

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

## 🧩 部署选项

### 一键生成 docker-compose.yml

勾选「生成 docker-compose.yml」，打包完成自动产出编排文件，可选附带 **MySQL 8** / **Redis 7**：

```yaml
version: "3.8"
services:
  app:
    image: my-app:latest
    container_name: my-app
    restart: unless-stopped
    ports:
      - "8080:8080"
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: change-me
  redis:
    image: redis:7-alpine
volumes:
  mysql-data:
  redis-data:
```

部署时只需一条命令：`docker compose up -d`。

### 镜像推送

勾选「构建后推送镜像」+ 填写仓库地址，打包完自动 `docker push`：

| 目标 | 仓库地址示例 |
|---|---|
| Docker Hub | `你的用户名` |
| 阿里云 ACR | `registry.cn-hangzhou.aliyuncs.com/命名空间` |
| 腾讯云 CCR | `ccr.ccs.tencentcloud.com/命名空间` |

> 推送前点界面上的「登录镜像仓库」按钮，按提示填仓库地址、用户名、密码/令牌即可完成 `docker login`，无需切命令行；推送仅支持单架构构建。

### 取消构建 / 分支 / 子目录 / 构建参数 / 压缩

- **取消构建**：多架构 QEMU 构建可能持续几十分钟，点「取消构建」会立即终止 docker 构建进程，构建用的临时目录也会自动清理
- **分支/标签**：Git 模式下可填分支或 tag（等价于 `git clone --branch <名称>`）
- **子目录**：monorepo 项目可填相对源码根目录的子目录，只构建该子目录
- **构建参数**：部署选项里每行写一个 `KEY=VALUE`，会作为 `--build-arg` 传入
- **压缩**：勾选「压缩为 .tar.gz」，导出后自动 gzip 压缩；`.tar.gz` 同样可用 `docker load -i` 导入
- **产物目录**：可自选 tar 保存目录，默认在系统临时目录 `docker_pack_out`；每次构建后自动清理，只保留最近 20 个归档

### 错误中文化与环境体检

点「开始打包」后会先做 Docker 环境体检（`docker` 命令存在 + 守护进程正在运行）。构建中遇到守护进程未启动、磁盘不足、端口占用、网络拉取超时、推送未授权等常见错误，会自动翻译成中文提示并附原始错误，不用再对着英文日志排查。

### 自定义 Dockerfile 模板

内置模板不满足时，无需改代码：在程序（exe / 脚本）同级的 `templates/` 目录放一个 `<类型标识>.dockerfile`（例如 `nodejs.dockerfile`），或设置环境变量 `DOCKER_PACK_TEMPLATES` 指向模板目录，即会用你的模板覆盖内置模板。模板中用 `{port}` 占位暴露端口。

### 历史记录

每次打包自动记录（时间、镜像、端口、架构、来源、分支、子目录、构建参数、是否压缩、状态），存于 `%APPDATA%\DockerPack\history.json`。在「历史记录」页选中一条，点「用选中记录重新打包」即可回填全部配置重新构建。

### 构建加速

Node / Python / Maven / Gradle / Go 模板内置 **BuildKit 依赖缓存挂载**，依赖层跨构建复用，二次打包大幅提速。需 Docker 20.10+（Docker Desktop 默认支持）。

---

## 🩺 构建后自检

单架构构建完成后自动：启动容器 → 轮询 30 秒 → 探测端口 → 自动清理。日志显示 `✓ 自检通过` / `△ 端口暂不可达` / `✗ 容器提前退出（附日志）`。**自检失败不影响 tar 导出**。

---

## 📦 产物使用

打包完成得到 `.tar` 文件，在目标服务器上导入：

```bash
# 导入镜像
docker load -i my-app_v1.0.tar

# 查看镜像
docker images

# 运行容器（端口映射要与填的端口一致）
docker run -d -p 8080:8080 my-app:v1.0

# 浏览器访问
http://服务器IP:8080
```

---

## ❓ 常见问题

| 问题 | 解决方法 |
|---|---|
| 双击 exe 无反应 | 右键 → 以管理员身份运行；或检查杀毒软件隔离区 |
| 提示未检测到 docker | 安装并启动 Docker Desktop |
| 打 ARM 架构很慢 | QEMU 模拟正常现象，建议在 ARM 机器上直接构建 |
| 多架构无法推送 | OCI 产物不进入本地仓库，请用单架构构建后推送 |
| 多架构 tar 无法 `docker load` | 多架构产物是 OCI 格式，不属于 `docker save` 格式；请推送到镜像仓库后用 `docker pull`，或在目标架构机器上分别单架构构建 |
| git clone 失败 | 检查网络；私有仓库需提前配置好 Git 凭据 |

---

## 🌍 Web 部署版

工具本身可 Docker 化部署，浏览器访问、多人共用：

```bash
# 在项目根目录构建（Dockerfile 位于 web/ 下，COPY 路径以项目根为上下文）
docker build -f web/Dockerfile -t docker-pack-web .
docker run -d -p 8000:8000 \
    -e DPW_TOKEN=设置一个访问令牌 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /data/docker-pack-web:/data \
    docker-pack-web
```

浏览器访问 `http://服务器IP:8000`，首次进入在页面顶部填写并保存令牌（存在浏览器 localStorage 中），功能与桌面版一致（compose / 推送 / 分支 / 子目录 / 构建参数 / 压缩 / 取消）。

安全与使用说明：

| 环境变量 | 作用 |
|---|---|
| `DPW_TOKEN` | 访问令牌；设置后所有 `/api` 接口都要求 `Authorization: Bearer <令牌>`，**多人部署强烈建议设置** |
| `DPW_ALLOW_LOCAL_PATH` | 设为 `1` 才允许以服务器上的任意目录作为构建上下文；默认只允许 `DPW_DATA_DIR` 内的路径 |
| `DPW_DATA_DIR` | 产物与上传 zip 的解压根目录，默认 `/data` |
| `PORT` | 监听端口，默认 8000 |

- **zip 上传**：不想开放服务器路径时，直接在页面选择本地 `.zip` 上传，服务端自动解压（带 zip-slip 路径防护）后构建
- **生产服务器**：安装了 waitress 时自动使用多线程 WSGI 服务（`threads=8`），未安装则回退 Flask 内置服务器
- 未设置 `DPW_TOKEN` 时启动日志会打印明确警告

---

## 🛠️ 从源码构建

```bash
git clone https://github.com/y50008/docker-pack.git
cd docker-pack-gui

# 直接运行（开发用）
python pack_gui.py

# 运行测试（不依赖 docker，纯逻辑回归；GitHub Actions 会在
# ubuntu / windows 双平台自动执行）
pip install pytest
python -m pytest tests/ -v

# 打包成 exe（需 Python 3.10+）
pip install pyinstaller
# 单文件版（启动稍慢、易被杀毒软件误报）
pyinstaller --onefile --windowed --name DockerPack --collect-all tkinter pack_gui.py
# 目录版（推荐：启动更快、误报更少，把整个 dist/DockerPack 目录分发即可）
pyinstaller --onedir --windowed --name DockerPack --collect-all tkinter pack_gui.py
```

> ⚠️ `--collect-all tkinter` 必须带上，否则 exe 会因缺少 Tcl/Tk 脚本库报 `No module named 'tkinter'`。
> 推荐用完整版 Python 打包（非精简发行版），确保 tkinter 脚本文件齐全。
> 单文件 `--onefile` 启动慢且更容易触发杀软误报，正式分发建议用 `--onedir` 目录版（或对 exe 做代码签名）。

---

## 📁 项目结构

```
docker-pack-gui/
├── pack_gui.py      # tkinter GUI 主程序（exe 版界面）
├── core.py          # 核心逻辑：类型检测、Dockerfile 生成、构建/自检/compose/推送/校验/取消
├── web_app.py       # Web 版后端（Flask API + 令牌鉴权 + zip 上传，复用 core.py）
├── templates/
│   └── index.html   # Web 版前端页面（也可放 <类型>.dockerfile 自定义模板）
├── web/
│   ├── Dockerfile   # Web 版自身镜像
│   └── requirements.txt
├── tests/
│   ├── conftest.py  # pytest 路径配置
│   └── test_core.py # 纯逻辑回归测试（71 项，不依赖 docker）
├── .github/
│   └── workflows/
│       └── ci.yml   # GitHub Actions：Windows / Ubuntu 双平台跑 pytest
├── docs/
│   └── screenshot.png
├── README.md
└── dist/
    └── DockerPack.exe   # 双击即用的可执行程序
```

---

## 📝 License

本项目仅供学习交流使用，转载请注明出处。

作者：**y50008**
