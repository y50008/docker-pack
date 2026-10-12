#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
web_app.py — Docker Pack Web 版
复用 core.py 的打包逻辑，通过网页界面操作。

部署方式（推荐，挂载 docker.sock）：
    docker build -t docker-pack-web .
    docker run -d -p 8000:8000 \
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
from pathlib import Path

from flask import Flask, jsonify, request, send_file, render_template

import core

# 数据目录（产物 tar 的存放位置，建议挂载出来）
DATA_DIR = Path(os.environ.get("DPW_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# 内存中的任务表：job_id -> job dict
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "pending",        # pending / running / done / error
            "logs": [],
            "progress": 0.0,
            "message": "等待开始...",
            "tar": None,
            "error": None,
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
    try:
        source_type = params["source_type"]
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
            source_dir = core.git_clone(url, tmp, lambda s: log_to(job_id, s))
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

        out_tar = DATA_DIR / f"{name.replace('/', '_')}_{tag}_{job_id}.tar"
        if out_tar.exists():
            out_tar.unlink()

        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"

        core.build_and_export(
            source_dir=source_dir,
            image_name=name,
            tag=tag,
            port=port,
            platforms=platforms,
            output_tar=out_tar,
            log=lambda s: log_to(job_id, s),
            progress=lambda p, m: progress_to(job_id, p, m),
        )

        with JOBS_LOCK:
            j = JOBS[job_id]
            j["status"] = "done"
            j["tar"] = str(out_tar)
            j["message"] = "构建完成"
        log_to(job_id, f"=== 完成：{out_tar} ===")
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

@app.route("/api/build", methods=["POST"])
def api_build():
    data = request.get_json(force=True)
    job_id = new_job()
    t = threading.Thread(target=build_worker, args=(job_id, data), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
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
        })


@app.route("/api/download/<job_id>")
def api_download(job_id: str):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if j is None or not j.get("tar") or not Path(j["tar"]).exists():
            return jsonify({"error": "文件不存在或未完成"}), 404
        tar_path = j["tar"]
    return send_file(tar_path, as_attachment=True,
                     download_name=Path(tar_path).name)


@app.route("/api/health")
def api_health():
    docker_ok = shutil.which("docker") is not None
    return jsonify({"ok": True, "docker_available": docker_ok})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Docker Pack Web 已启动: http://0.0.0.0:{port}")
    print(f"产物目录: {DATA_DIR}")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
