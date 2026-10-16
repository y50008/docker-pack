#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
web_app.py — Docker Pack Web 版 v2
复用 core.py 的打包逻辑，通过网页界面操作，功能与桌面版对齐。

安全相关环境变量：
    DPW_TOKEN             访问令牌；设置后所有 /api 接口都要求 Bearer 令牌（强烈建议设置）
    DPW_ALLOW_LOCAL_PATH  =1 时允许构建服务器上的任意目录；默认只允许 DPW_DATA_DIR 内的路径
    DPW_DATA_DIR          产物 / 上传 zip 的解压根目录（默认 /data）
    PORT                  监听端口（默认 8000）

部署方式（推荐，挂载 docker.sock；在项目根目录构建）：
    docker build -f web/Dockerfile -t docker-pack-web .
    docker run -d -p 8000:8000 \
        -e DPW_TOKEN=你的访问令牌 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v /data/docker-pack-web:/data \
        docker-pack-web

然后浏览器访问 http://服务器IP:8000
"""

import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request, send_file, render_template

import core

# 数据目录（产物 tar 的存放位置，建议挂载出来）
DATA_DIR = Path(os.environ.get("DPW_DATA_DIR", "/data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 鉴权与路径白名单开关
AUTH_TOKEN = os.environ.get("DPW_TOKEN", "").strip()
ALLOW_LOCAL_PATH = os.environ.get("DPW_ALLOW_LOCAL_PATH", "") == "1"
MAX_JOBS = 50

app = Flask(__name__)

# 内存中的任务表：job_id -> job dict
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def require_token(fn):
    """访问令牌鉴权：支持 Authorization: Bearer <token> 或 ?token=<token>（下载链接用）。"""
    @wraps(fn)
    def wrapper(*a, **kw):
        if AUTH_TOKEN:
            auth = request.headers.get("Authorization", "")
            token = request.args.get("token", "")
            if auth != f"Bearer {AUTH_TOKEN}" and token != AUTH_TOKEN:
                return jsonify({"error": "unauthorized：访问令牌无效或缺失"}), 401
        return fn(*a, **kw)
    return wrapper


def new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        # 任务表只保留最近 MAX_JOBS 个已结束任务，超出的连同产物文件一起清理
        done = [jid for jid, j in JOBS.items()
                if j["status"] in ("done", "error", "cancelled")]
        while len(JOBS) >= MAX_JOBS and done:
            old_id = done.pop(0)
            old = JOBS.pop(old_id, None)
            if old:
                for key in ("tar", "compose"):
                    p = old.get(key)
                    if p:
                        try:
                            Path(p).unlink(missing_ok=True)
                        except OSError:
                            pass
        JOBS[job_id] = {
            "status": "pending",        # pending / running / done / error / cancelled
            "logs": [],
            "progress": 0.0,
            "message": "等待开始...",
            "tar": None,
            "compose": None,
            "error": None,
            "cancel": False,
        }
    return job_id


def log_to(job_id: str, line: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is not None:
            j["logs"].append(line)
            if len(j["logs"]) > 2000:
                j["logs"] = j["logs"][-2000:]


def progress_to(job_id: str, pct: float, msg: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is not None:
            j["progress"] = round(pct, 3)
            j["message"] = msg


def build_worker(job_id: str, params: dict):
    log_to(job_id, "=== 任务已接收 ===")

    def should_cancel() -> bool:
        with JOBS_LOCK:
            return JOBS[job_id].get("cancel", False)

    try:
        source_type = params.get("source_type", "local")
        if source_type == "local":
            src = params.get("path", "")
            if not Path(src).is_dir():
                raise RuntimeError(f"本地目录不存在: {src}")
            source_dir = Path(src).resolve()
            log_to(job_id, f"[src] 本地目录: {source_dir}")
        else:
            url = params.get("url", "")
            if not core.is_git_url(url):
                raise RuntimeError("项目地址无效（需 https://... 或 git@...）")
            tmp = Path(tempfile.mkdtemp(prefix="dpw_src_"))
            try:
                source_dir = core.git_clone(
                    url, tmp, lambda s: log_to(job_id, s),
                    branch=params.get("branch", ""))
            except Exception as e:
                # git clone 的错误未经 core 翻译，这里补一层中文提示
                raise RuntimeError(core.friendly_error(str(e)))
            log_to(job_id, f"[src] 已克隆到: {source_dir}")

        name = params.get("name", "my-app").strip() or "my-app"
        tag = params.get("tag", "latest").strip() or "latest"
        try:
            port = int(params.get("port", 8080))
        except (TypeError, ValueError):
            raise RuntimeError("端口必须是数字")
        platforms = params.get("platforms") or ["linux/amd64"]
        if not platforms:
            platforms = ["linux/amd64"]

        build_args = params.get("build_args") or {}
        subdir = params.get("subdir", "")
        compress = bool(params.get("compress", False))

        out_tar = DATA_DIR / f"{name.replace('/', '_')}_{tag}_{job_id}.tar"
        if out_tar.exists():
            out_tar.unlink()

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"

        final_tar = core.build_and_export(
            source_dir=source_dir,
            image_name=name,
            tag=tag,
            port=port,
            platforms=platforms,
            output_tar=out_tar,
            log=lambda s: log_to(job_id, s),
            progress=lambda p, m: progress_to(job_id, p, m),
            push_registry=params.get("registry", ""),
            push=bool(params.get("push", False)),
            build_args=build_args,
            subdir=subdir,
            compress=compress,
            should_cancel=should_cancel,
        )

        # 可选：生成 docker-compose.yml
        compose_path = None
        if params.get("gen_compose"):
            compose_text = core.generate_compose(
                name, tag, port,
                include_mysql=bool(params.get("compose_mysql")),
                include_redis=bool(params.get("compose_redis")),
                db_password=params.get("db_password") or "change-me",
            )
            base = final_tar.name
            if base.endswith(".tar.gz"):
                base = base[:-len(".tar.gz")]
            else:
                base = final_tar.stem
            compose_path = final_tar.with_name(base + ".compose.yml")
            compose_path.write_text(compose_text, encoding="utf-8", newline="\n")
            log_to(job_id, f"[compose] 已生成 {compose_path}")

        with JOBS_LOCK:
            j = JOBS[job_id]
            j["status"] = "done"
            j["tar"] = str(final_tar)
            j["compose"] = str(compose_path) if compose_path else None
            j["message"] = "构建完成"
        log_to(job_id, f"=== 完成：{final_tar} ===")
    except core.BuildCancelled:
        log_to(job_id, "[cancel] 构建已取消")
        with JOBS_LOCK:
            j = JOBS.get(job_id)
            if j:
                j["status"] = "cancelled"
                j["message"] = "已取消"
    except Exception as e:
        log_to(job_id, f"[ERROR] {e}")
        with JOBS_LOCK:
            j = JOBS.get(job_id)
            if j:
                j["status"] = "error"
                j["error"] = str(e)
                j["message"] = "构建失败"


# ---------- 页面 ----------

@app.route("/")
def index():
    return render_template("index.html")


# ---------- API ----------

@app.route("/api/upload", methods=["POST"])
@require_token
def api_upload():
    """接收 zip 源码包，解压到上传目录，返回服务器路径供构建使用。"""
    f = request.files.get("file")
    if not f or not f.filename or not f.filename.lower().endswith(".zip"):
        return jsonify({"error": "请上传 .zip 文件"}), 400
    dest = Path(tempfile.mkdtemp(prefix="dpw_upload_", dir=UPLOAD_DIR))
    zip_path = dest / "src.zip"
    f.save(zip_path)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            # zip-slip 防护：解压目标必须留在 dest 内
            for member in zf.namelist():
                target = (dest / member).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    shutil.rmtree(dest, ignore_errors=True)
                    return jsonify({"error": "zip 内包含非法路径，已拒绝解压"}), 400
            zf.extractall(dest)
    except zipfile.BadZipFile:
        shutil.rmtree(dest, ignore_errors=True)
        return jsonify({"error": "zip 文件损坏"}), 400
    zip_path.unlink(missing_ok=True)
    return jsonify({"path": str(dest)})


@app.route("/api/build", methods=["POST"])
@require_token
def api_build():
    data = request.get_json(force=True)

    # 源码来源校验 + 路径白名单
    source_type = data.get("source_type", "local")
    if source_type == "local":
        src = Path(data.get("path", "")).expanduser()
        if not src.is_dir():
            return jsonify({"error": f"本地目录不存在: {src}"}), 400
        if not ALLOW_LOCAL_PATH:
            root = DATA_DIR.resolve()
            if not str(src.resolve()).startswith(str(root)):
                return jsonify({"error": "为安全起见，服务器路径模式仅允许产物目录内的路径；"
                                          "请使用 zip 上传，或设置环境变量 DPW_ALLOW_LOCAL_PATH=1"}), 400
    else:
        if not core.is_git_url(data.get("url", "")):
            return jsonify({"error": "项目地址无效（需 https://... 或 git@...）"}), 400

    # 输入校验
    name = (data.get("name") or "my-app").strip()
    tag = (data.get("tag") or "latest").strip()
    err = (core.validate_image_name(name)
           or core.validate_tag(tag)
           or core.validate_port(data.get("port", 8080)))
    if err:
        return jsonify({"error": err}), 400

    # 构建参数：前端可传对象，也可传 KEY=VALUE 文本
    ba = data.get("build_args")
    if isinstance(ba, str):
        ba, ba_err = core.validate_build_args(ba)
        if ba_err:
            return jsonify({"error": ba_err}), 400
        data["build_args"] = ba
    elif ba is None:
        data["build_args"] = {}

    job_id = new_job()
    t = threading.Thread(target=build_worker, args=(job_id, data), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/cancel/<job_id>", methods=["POST"])
@require_token
def api_cancel(job_id: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is None:
            return jsonify({"error": "job not found"}), 404
        j["cancel"] = True
    return jsonify({"ok": True})


@app.route("/api/status/<job_id>")
@require_token
def api_status(job_id: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is None:
            return jsonify({"error": "job not found"}), 404
        return jsonify({
            "status": j["status"],
            "logs": j["logs"][-200:],          # 最近 200 行
            "progress": j["progress"],
            "message": j["message"],
            "error": j["error"],
            "has_tar": j["tar"] is not None,
            "has_compose": j.get("compose") is not None,
        })


@app.route("/api/download/<job_id>")
@require_token
def api_download(job_id: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is None or not j.get("tar") or not Path(j["tar"]).exists():
            return jsonify({"error": "文件不存在或未完成"}), 404
        tar_path = j["tar"]
    return send_file(tar_path, as_attachment=True,
                     download_name=Path(tar_path).name)


@app.route("/api/download-compose/<job_id>")
@require_token
def api_download_compose(job_id: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is None or not j.get("compose") or not Path(j["compose"]).exists():
            return jsonify({"error": "文件不存在或未完成"}), 404
        compose_path = j["compose"]
    return send_file(compose_path, as_attachment=True,
                     download_name="docker-compose.yml")


@app.route("/api/health")
def api_health():
    docker_ok = shutil.which("docker") is not None
    return jsonify({"ok": True, "docker_available": docker_ok,
                    "auth_enabled": bool(AUTH_TOKEN)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Docker Pack Web 已启动: http://0.0.0.0:{port}")
    print(f"产物目录: {DATA_DIR}")
    if AUTH_TOKEN:
        print("已启用访问令牌鉴权（DPW_TOKEN）")
    else:
        print("警告：未设置 DPW_TOKEN，任何能访问本端口的人都能构建镜像！")
    try:
        # 生产环境优先使用 waitress（多线程 WSGI 服务器），未安装则回退 Flask 内置服务器
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
