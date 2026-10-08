# Docker Pack GUI — 可视化 Docker 打包工具

一键把项目源码打包成 Docker 镜像并导出为 tar 文件的桌面工具。

- **作者**: y50008
- **来源**: www.52pojie.com
- **开源地址**: https://github.com/y50008/docker-pack

## 直接使用

双击 `dist\DockerPack.exe` 即可运行（无需安装 Python）。

## 界面功能

1. **选择源码来源**
   - 本地目录：点「浏览...」选择项目源码文件夹
   - Git 仓库地址：输入 https://github.com/xxx/xxx.git，工具自动 clone
2. **镜像配置**：镜像名、标签（tag）、容器暴露端口
3. **目标架构**
   - `linux/amd64`：普通 PC / 云服务器（x86_64）
   - `linux/arm64`：ARM 服务器 / Apple M 系列
   - 全部：同时构建两种架构（用 buildx 输出 OCI 格式 tar）
4. **开始打包**：自动检测项目类型 → 生成 Dockerfile → 调用 docker build
5. **实时进度**：进度条 + 已用时 + 预计剩余时间 + 实时日志
6. **下载按钮**：构建完成后亮起，点击后弹出「另存为」对话框，把镜像 tar 保存到指定位置

## 支持的项目类型（自动识别）

| 标志文件 | 识别为 | 基础镜像策略 |
|---|---|---|
| `Dockerfile`（已有） | 项目自带 Dockerfile | **直接复用，不覆盖** |
| `package.json` | Node.js（含 TS/React/Vue/Next） | node:20-alpine 多阶段 |
| `requirements.txt` / `pyproject.toml` / `Pipfile` | Python | python:3.11-slim 多阶段 |
| `pom.xml` | Java Maven | maven:3.9 + JRE 21 |
| `build.gradle` / `settings.gradle` | Java Gradle / Spring Boot | gradle:8 + JRE 21 |
| `go.mod` | Go | golang:1.22 + alpine |
| `*.csproj` / `*.sln` | .NET | dotnet/sdk:8 + aspnet:8 |
| `composer.json` | PHP | composer:2 + php:8.3-apache |
| `Gemfile` | Ruby | ruby:3.2-alpine |
| `Cargo.toml` | Rust | rust:1.77-alpine + musl |
| `CMakeLists.txt` | C/C++ | gcc:13 + cmake |
| `pubspec.yaml` | Flutter Web | Flutter SDK + nginx |
| `index.html`（兜底） | 静态网站 | nginx:alpine |

> 关键兼容策略：如果项目根目录**已经有 Dockerfile**，工具会直接复用它，不会覆盖——这意味着任何已有 Docker 化的项目都能直接打包。

## 使用前提

- Windows 10/11
- 本机已安装并启动 **Docker Desktop**（需要 docker 命令在 PATH 中）
- 如果要 clone Git 仓库，需要本机装了 `git` 命令
- 多架构构建（arm64）需要 Docker Desktop 已启用 buildx 和 QEMU 模拟（Docker Desktop 默认自带）

## 产物说明

构建完成后得到一个 `.tar` 文件，在目标机器上导入：

```bash
docker load -i your-image.tar
docker run -d -p 8080:8080 your-image:tag
```

## 重新打包 exe（开发者用）

```bat
build_exe.bat
```

脚本内容等价于：

```bat
pyinstaller --onefile --windowed --name DockerPack pack_gui.py
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `pack_gui.py` | tkinter GUI 主程序 |
| `core.py` | 核心逻辑：项目检测、Dockerfile 生成、git clone、docker build/save |
| `dist/DockerPack.exe` | 打包好的单文件可执行程序 |
| `build_exe.bat` | 重新打包 exe 的脚本 |
