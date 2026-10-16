#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack_gui.py — Docker 打包工具可视化界面（v1.4）
新增：取消构建、登录镜像仓库、Git 分支/标签、monorepo 子目录、构建参数、
      tar.gz 压缩、产物目录可配置与自动清理、输入校验、错误中文化
"""

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# 兼容 PyInstaller 打包后的导入
try:
    import core
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import core

# 历史记录文件（%APPDATA%/DockerPack/history.json）
HISTORY_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "DockerPack"
HISTORY_FILE = HISTORY_DIR / "history.json"

# 默认产物目录
DEFAULT_OUT_DIR = Path(tempfile.gettempdir()) / "docker_pack_out"


class PackApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Docker 项目打包工具 v1.4")
        root.geometry("900x860")
        root.minsize(820, 740)

        self.msg_queue: queue.Queue = queue.Queue()
        self.temp_dirs: list[Path] = []
        self.final_tar: Path | None = None
        self.final_compose: Path | None = None
        self.start_time: float = 0.0
        self.building = False
        self.cancel_requested = False
        self.history: list[dict] = []

        self._build_ui()
        self._load_history()
        self._refresh_history()
        self._print_banner()
        self.root.after(100, self._poll_queue)
        self.root.after(500, self._update_eta)

    # ---------- 作者信息 ----------

    def _print_banner(self):
        """启动时输出绿色作者信息"""
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, "作者: y50008\n", ("green",))
        self.log_text.insert(tk.END, "开源地址: https://github.com/y50008/docker-pack\n", ("green",))
        self.log_text.insert(tk.END, "-" * 60 + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # ---------- UI ----------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 3}

        # 1. 源码来源
        frm_src = ttk.LabelFrame(self.root, text="① 选择源码来源")
        frm_src.pack(fill="x", **pad)

        self.src_mode = tk.StringVar(value="local")
        ttk.Radiobutton(frm_src, text="本地目录", variable=self.src_mode,
                        value="local", command=self._on_mode_change).grid(row=0, column=0, sticky="w", padx=8)
        ttk.Radiobutton(frm_src, text="项目地址（github 或其他）", variable=self.src_mode,
                        value="git", command=self._on_mode_change).grid(row=0, column=1, sticky="w", padx=8)

        self.local_entry = ttk.Entry(frm_src)
        self.local_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=3)
        self.browse_btn = ttk.Button(frm_src, text="浏览...", command=self._browse_local)
        self.browse_btn.grid(row=1, column=2, padx=8)

        self.git_entry = ttk.Entry(frm_src)
        self.git_entry.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=3)
        self.git_entry.grid_remove()

        # 分支/标签（仅 Git 模式）
        self.branch_label = ttk.Label(frm_src, text="分支/标签(可选):")
        self.branch_label.grid(row=3, column=0, sticky="e", padx=8, pady=3)
        self.branch_var = tk.StringVar()
        self.branch_entry = ttk.Entry(frm_src, textvariable=self.branch_var)
        self.branch_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=8, pady=3)
        self.branch_label.grid_remove()
        self.branch_entry.grid_remove()

        # monorepo 子目录（两种模式都适用）
        ttk.Label(frm_src, text="子目录(可选):").grid(row=4, column=0, sticky="e", padx=8, pady=3)
        self.subdir_var = tk.StringVar()
        ttk.Entry(frm_src, textvariable=self.subdir_var
                  ).grid(row=4, column=1, columnspan=2, sticky="ew", padx=8, pady=3)

        frm_src.columnconfigure(0, weight=1)
        frm_src.columnconfigure(1, weight=1)
        frm_src.columnconfigure(2, weight=0)

        # 2. 镜像配置
        frm_img = ttk.LabelFrame(self.root, text="② 镜像配置")
        frm_img.pack(fill="x", **pad)

        ttk.Label(frm_img, text="镜像名:").grid(row=0, column=0, padx=6, pady=5, sticky="e")
        self.name_var = tk.StringVar(value="my-app")
        ttk.Entry(frm_img, textvariable=self.name_var, width=24).grid(row=0, column=1, padx=4)

        ttk.Label(frm_img, text="标签:").grid(row=0, column=2, padx=6, pady=5)
        self.tag_var = tk.StringVar(value="latest")
        ttk.Entry(frm_img, textvariable=self.tag_var, width=12).grid(row=0, column=3, padx=4)

        ttk.Label(frm_img, text="暴露端口:").grid(row=0, column=4, padx=6, pady=5)
        self.port_var = tk.StringVar(value="8080")
        ttk.Entry(frm_img, textvariable=self.port_var, width=8).grid(row=0, column=5, padx=4)

        # 3. 架构选择
        frm_arch = ttk.LabelFrame(self.root, text="③ 选择目标架构（可多选）")
        frm_arch.pack(fill="x", **pad)

        self.arch_options = [
            (tk.BooleanVar(value=True),  "linux/amd64",  "x86_64：普通 PC / 云服务器"),
            (tk.BooleanVar(value=False), "linux/arm64",  "ARM 服务器 / Apple M / 树莓派5"),
            (tk.BooleanVar(value=False), "linux/arm/v7", "树莓派3/4 老系统 / IoT"),
            (tk.BooleanVar(value=False), "linux/riscv64","RISC-V 开发板 / 边缘计算"),
        ]
        self.arch_all = tk.BooleanVar(value=False)

        for i, (var, pid, desc) in enumerate(self.arch_options):
            row = i // 2
            col = i % 2
            ttk.Checkbutton(frm_arch, text=f"{pid} — {desc}",
                           variable=var,
                           command=self._on_arch_change).grid(row=row, column=col, sticky="w", padx=10, pady=2)

        ttk.Checkbutton(frm_arch, text="全部常用架构（构建最慢）",
                        variable=self.arch_all,
                        command=self._on_arch_all).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        # 4. 部署选项（Compose + 推送 + 构建参数 + 压缩 + 产物目录）
        frm_opt = ttk.LabelFrame(self.root, text="④ 部署选项（可选）")
        frm_opt.pack(fill="x", **pad)

        self.gen_compose = tk.BooleanVar(value=False)
        self.compose_mysql = tk.BooleanVar(value=False)
        self.compose_redis = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_opt, text="生成 docker-compose.yml", variable=self.gen_compose
                        ).grid(row=0, column=0, sticky="w", padx=10)
        ttk.Checkbutton(frm_opt, text="附带 MySQL", variable=self.compose_mysql
                        ).grid(row=0, column=1, sticky="w", padx=10)
        ttk.Checkbutton(frm_opt, text="附带 Redis", variable=self.compose_redis
                        ).grid(row=0, column=2, sticky="w", padx=10)
        ttk.Label(frm_opt, text="数据库密码:").grid(row=0, column=3, padx=6, sticky="e")
        self.db_pass_var = tk.StringVar(value="change-me")
        ttk.Entry(frm_opt, textvariable=self.db_pass_var, width=14, show="*").grid(row=0, column=4, padx=4)

        self.push_enable = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_opt, text="构建后推送镜像", variable=self.push_enable
                        ).grid(row=1, column=0, sticky="w", padx=10, pady=(6, 2))
        ttk.Label(frm_opt, text="仓库地址:").grid(row=1, column=1, padx=6, pady=(6, 2), sticky="e")
        self.registry_var = tk.StringVar(value="registry.cn-hangzhou.aliyuncs.com/your-namespace")
        ttk.Entry(frm_opt, textvariable=self.registry_var, width=42).grid(row=1, column=2, columnspan=3,
                                                                           sticky="ew", padx=4, pady=(6, 2))

        # 构建参数（每行一个 KEY=VALUE）
        ttk.Label(frm_opt, text="构建参数:").grid(row=2, column=0, sticky="ne", padx=10, pady=(6, 2))
        self.args_text = tk.Text(frm_opt, height=3, width=60, font=("Consolas", 9),
                                 background="#0d1220", foreground="#d4d4d4",
                                 insertbackground="#d4d4d4", relief="solid", borderwidth=1)
        self.args_text.grid(row=2, column=1, columnspan=4, sticky="ew", padx=4, pady=(6, 2))
        ttk.Label(frm_opt, text="每行一个 KEY=VALUE，会传给 docker build --build-arg（可留空）",
                  foreground="gray").grid(row=3, column=1, columnspan=4, sticky="w", padx=4)

        # 压缩 + 产物目录
        self.compress_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_opt, text="压缩为 .tar.gz（体积更小）", variable=self.compress_var
                        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=(6, 2))
        ttk.Label(frm_opt, text="产物目录:").grid(row=5, column=0, sticky="e", padx=10, pady=3)
        self.outdir_var = tk.StringVar(value=str(DEFAULT_OUT_DIR))
        ttk.Entry(frm_opt, textvariable=self.outdir_var, width=48
                  ).grid(row=5, column=1, columnspan=3, sticky="ew", padx=4, pady=3)
        ttk.Button(frm_opt, text="选择目录...", command=self._browse_outdir
                   ).grid(row=5, column=4, padx=4, pady=3)

        frm_opt.columnconfigure(2, weight=1)

        # 5. Notebook：构建 / 历史
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=6)

        # --- Tab1: 构建 ---
        tab_build = ttk.Frame(self.nb)
        self.nb.add(tab_build, text="  构建  ")

        frm_btn = ttk.Frame(tab_build)
        frm_btn.pack(fill="x", padx=8, pady=6)

        self.build_btn = ttk.Button(frm_btn, text="开始打包", command=self._start_build)
        self.build_btn.pack(side="left", padx=6)

        self.cancel_btn = ttk.Button(frm_btn, text="取消构建", command=self._cancel_build, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)

        self.login_btn = ttk.Button(frm_btn, text="登录镜像仓库", command=self._docker_login)
        self.login_btn.pack(side="left", padx=6)

        self.download_btn = ttk.Button(frm_btn, text="下载打包好的镜像文件",
                                       command=self._download_tar, state="disabled")
        self.download_btn.pack(side="left", padx=6)

        self.compose_btn = ttk.Button(frm_btn, text="下载 docker-compose.yml",
                                      command=self._download_compose, state="disabled")
        self.compose_btn.pack(side="left", padx=6)

        self.status_label = ttk.Label(frm_btn, text="就绪", foreground="gray")
        self.status_label.pack(side="right", padx=12)

        frm_prog = ttk.Frame(tab_build)
        frm_prog.pack(fill="x", padx=8, pady=2)

        self.progress = ttk.Progressbar(frm_prog, mode="determinate", maximum=100)
        self.progress.pack(fill="x", side="top")

        self.eta_label = ttk.Label(frm_prog, text="")
        self.eta_label.pack(anchor="w", pady=2)

        frm_log = ttk.LabelFrame(tab_build, text="构建日志")
        frm_log.pack(fill="both", expand=True, padx=8, pady=6)

        self.log_text = tk.Text(frm_log, wrap="word", state="disabled",
                                bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log_text.tag_configure("green", foreground="#4ee44e", font=("Consolas", 20, "bold"))
        scroll = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # --- Tab2: 历史记录 ---
        tab_hist = ttk.Frame(self.nb)
        self.nb.add(tab_hist, text="  历史记录  ")

        frm_hist_btn = ttk.Frame(tab_hist)
        frm_hist_btn.pack(fill="x", padx=8, pady=6)

        ttk.Button(frm_hist_btn, text="用选中记录重新打包",
                   command=self._rebuild_from_history).pack(side="left", padx=8)
        ttk.Button(frm_hist_btn, text="刷新", command=self._refresh_history).pack(side="left", padx=8)
        ttk.Button(frm_hist_btn, text="清空历史", command=self._clear_history).pack(side="left", padx=8)

        cols = ("time", "image", "port", "arch", "source", "status")
        self.hist_tree = ttk.Treeview(tab_hist, columns=cols, show="headings", height=14)
        headers = {"time": ("时间", 130), "image": ("镜像", 170), "port": ("端口", 60),
                   "arch": ("架构", 120), "source": ("来源", 130), "status": ("状态", 80)}
        for c, (text, w) in headers.items():
            self.hist_tree.heading(c, text=text)
            self.hist_tree.column(c, width=w, anchor="w")
        self.hist_tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.hist_tree.bind("<Double-1>", lambda e: self._rebuild_from_history())

    # ---------- 交互 ----------

    def _on_mode_change(self):
        if self.src_mode.get() == "local":
            self.git_entry.grid_remove()
            self.branch_label.grid_remove()
            self.branch_entry.grid_remove()
            self.local_entry.grid()
            self.browse_btn.grid()
        else:
            self.local_entry.grid_remove()
            self.browse_btn.grid_remove()
            self.git_entry.grid()
            self.branch_label.grid()
            self.branch_entry.grid()

    def _browse_local(self):
        d = filedialog.askdirectory(title="选择项目源码目录")
        if d:
            self.local_entry.delete(0, tk.END)
            self.local_entry.insert(0, d)
            self.name_var.set(Path(d).name.lower().replace("_", "-"))

    def _browse_outdir(self):
        d = filedialog.askdirectory(title="选择镜像产物保存目录")
        if d:
            self.outdir_var.set(d)

    def _on_arch_change(self):
        if not any(v.get() for v, _, _ in self.arch_options):
            self.arch_options[0][0].set(True)
        self.arch_all.set(False)

    def _on_arch_all(self):
        if self.arch_all.get():
            for var, _, _ in self.arch_options:
                var.set(True)

    def _collect_platforms(self) -> list[str]:
        selected = [pid for var, pid, _ in self.arch_options if var.get()]
        return selected or ["linux/amd64"]

    # ---------- 登录镜像仓库 ----------

    def _docker_login(self):
        """弹窗收集仓库地址/用户名/密码，调用 docker login --password-stdin，无需切命令行。"""
        registry = simpledialog.askstring(
            "登录镜像仓库", "仓库地址（留空 = Docker Hub）：",
            initialvalue="", parent=self.root)
        if registry is None:
            return
        username = simpledialog.askstring("登录镜像仓库", "用户名：", parent=self.root)
        if not username:
            return
        password = simpledialog.askstring("登录镜像仓库", "密码 / 访问令牌：", show="*", parent=self.root)
        if not password:
            return
        host = registry.strip() or "https://index.docker.io/v1/"
        # docker login 只接受 host[:port]，把命名空间路径去掉
        if "://" not in host and "/" in host:
            host = host.split("/")[0]
        cmd = ["docker", "login", host, "-u", username.strip(), "--password-stdin"]
        self._append_log(f"[login] 正在登录 {host} ...")
        try:
            rc = subprocess.run(cmd, input=password, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            messagebox.showerror("登录失败", "未检测到 docker 命令，请先安装并启动 Docker Desktop")
            return
        if rc.returncode == 0:
            self._append_log(f"[login] ✓ 已登录 {host}")
            messagebox.showinfo("登录成功", f"已登录 {host}\n现在可以勾选「构建后推送镜像」了。")
        else:
            self._append_log(f"[login] 登录失败：{rc.stderr or rc.stdout}")
            messagebox.showerror("登录失败", (rc.stderr or rc.stdout or "未知错误"))

    # ---------- 历史记录 ----------

    def _load_history(self):
        try:
            if HISTORY_FILE.exists():
                self.history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                if not isinstance(self.history, list):
                    self.history = []
        except Exception:
            self.history = []

    def _save_history(self):
        try:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(
                json.dumps(self.history[:100], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _add_history(self, rec: dict):
        rec["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.history.insert(0, rec)
        self._save_history()
        self._refresh_history()

    def _refresh_history(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        for rec in self.history[:50]:
            self.hist_tree.insert("", "end", values=(
                rec.get("time", ""),
                f"{rec.get('name', '')}:{rec.get('tag', '')}",
                rec.get("port", ""),
                ", ".join(p.split("/")[-1] for p in rec.get("platforms", [])),
                rec.get("source", ""),
                rec.get("status", ""),
            ))

    def _clear_history(self):
        if messagebox.askyesno("确认", "确定清空全部历史记录？"):
            self.history = []
            self._save_history()
            self._refresh_history()

    def _rebuild_from_history(self):
        sel = self.hist_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在历史列表中选择一条记录")
            return
        idx = self.hist_tree.index(sel[0])
        if idx >= len(self.history):
            return
        rec = self.history[idx]
        # 回填表单
        self.name_var.set(rec.get("name", "my-app"))
        self.tag_var.set(rec.get("tag", "latest"))
        self.port_var.set(str(rec.get("port", 8080)))
        if rec.get("source_type") == "git":
            self.src_mode.set("git")
            self.git_entry.delete(0, tk.END)
            self.git_entry.insert(0, rec.get("source", ""))
        else:
            self.src_mode.set("local")
            self.local_entry.delete(0, tk.END)
            self.local_entry.insert(0, rec.get("source", ""))
        self.branch_var.set(rec.get("branch", ""))
        self.subdir_var.set(rec.get("subdir", ""))
        self.compress_var.set(bool(rec.get("compress", False)))
        self.args_text.delete("1.0", tk.END)
        self.args_text.insert("1.0", rec.get("build_args", ""))
        self._on_mode_change()
        # 架构
        want = rec.get("platforms", ["linux/amd64"])
        for var, pid, _ in self.arch_options:
            var.set(pid in want)
        self.nb.select(0)  # 切回构建页
        self._start_build()

    # ---------- 构建 ----------

    def _start_build(self):
        if self.building:
            return

        src = ""
        if self.src_mode.get() == "local":
            src = self.local_entry.get().strip()
            if not src or not Path(src).is_dir():
                messagebox.showerror("错误", "请选择有效的本地项目目录")
                return
            source_dir = Path(src).resolve()
        else:
            url = self.git_entry.get().strip()
            if not core.is_git_url(url):
                messagebox.showerror("错误", "请输入有效的项目地址（https://... 或 git@...）")
                return
            source_dir = None

        name = self.name_var.get().strip() or "my-app"
        tag = self.tag_var.get().strip() or "latest"
        port_raw = self.port_var.get().strip()
        # 输入校验（镜像名 / 标签 / 端口）
        err = core.validate_image_name(name) or core.validate_tag(tag) or core.validate_port(port_raw)
        if err:
            messagebox.showerror("输入有误", err)
            return
        port = int(port_raw)

        # 构建参数校验
        build_args_text = self.args_text.get("1.0", tk.END)
        build_args, ba_err = core.validate_build_args(build_args_text)
        if ba_err:
            messagebox.showerror("输入有误", ba_err)
            return

        platforms = self._collect_platforms()
        registry = self.registry_var.get().strip().rstrip("/")
        push = self.push_enable.get()
        if push and not registry:
            messagebox.showerror("错误", "勾选推送后请填写镜像仓库地址")
            return
        gen_compose = self.gen_compose.get()
        db_pass = self.db_pass_var.get().strip() or "change-me"
        branch = self.branch_var.get().strip()
        subdir = self.subdir_var.get().strip()
        compress = self.compress_var.get()

        # 产物目录
        out_dir = Path(self.outdir_var.get().strip() or str(DEFAULT_OUT_DIR)).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("错误", f"产物目录无法创建：{e}")
            return
        # core 压缩时会在 .tar 后追加 .gz，这里先按 .tar 命名
        out_tar = out_dir / f"{name.replace('/', '_')}_{tag}_{'multi' if len(platforms)>1 else platforms[0].replace('/','_')}.tar"
        if out_tar.exists():
            out_tar.unlink()
        gz_tar = out_tar.with_name(out_tar.name + ".gz")
        if gz_tar.exists():
            gz_tar.unlink()

        # 记录历史
        self._add_history({
            "source_type": self.src_mode.get(),
            "source": src if self.src_mode.get() == "local" else self.git_entry.get().strip(),
            "name": name, "tag": tag, "port": port,
            "platforms": platforms, "status": "进行中",
            "branch": branch, "subdir": subdir,
            "compress": compress, "build_args": build_args_text.strip(),
        })

        # 重置 UI
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self._print_banner()
        self.progress["value"] = 0
        self.download_btn.configure(state="disabled")
        self.compose_btn.configure(state="disabled")
        self.build_btn.configure(state="disabled", text="打包中...")
        self.cancel_btn.configure(state="normal")
        self.login_btn.configure(state="disabled")
        self.status_label.configure(text="构建中...", foreground="orange")
        self.final_tar = None
        self.final_compose = None
        self.start_time = time.time()
        self.building = True
        self.cancel_requested = False

        opts = {
            "name": name, "tag": tag, "port": port, "platforms": platforms,
            "registry": registry, "push": push,
            "gen_compose": gen_compose,
            "compose_mysql": self.compose_mysql.get(),
            "compose_redis": self.compose_redis.get(),
            "db_pass": db_pass,
            "branch": branch, "subdir": subdir,
            "compress": compress, "build_args": build_args,
            "out_dir": str(out_dir),
        }
        t = threading.Thread(
            target=self._build_worker,
            args=(source_dir, self.git_entry.get().strip() if source_dir is None else None,
                  out_tar, opts),
            daemon=True,
        )
        t.start()

    def _cancel_build(self):
        if not self.building:
            return
        self.cancel_requested = True
        self.cancel_btn.configure(state="disabled")
        self.status_label.configure(text="正在取消...", foreground="orange")
        self._append_log("[cancel] 已请求取消，正在终止构建进程...")

    def _build_worker(self, source_dir, git_url, out_tar, opts):
        try:
            self._log(f"=== 开始任务 ===")
            self._log(f"镜像: {opts['name']}:{opts['tag']}  端口: {opts['port']}  架构: {opts['platforms']}")
            if opts["push"]:
                self._log(f"[push] 将推送到: {opts['registry']}")

            if git_url:
                tmp = Path(tempfile.mkdtemp(prefix="docker_pack_src_"))
                self.temp_dirs.append(tmp)
                try:
                    source_dir = core.git_clone(git_url, tmp, self._log, branch=opts.get("branch", ""))
                except Exception as e:
                    # git clone 的错误未经 core 翻译，这里补一层中文提示
                    raise RuntimeError(core.friendly_error(str(e)))
                self._log(f"[git] 源码目录: {source_dir}")

            assert source_dir is not None

            final_tar = core.build_and_export(
                source_dir=source_dir,
                image_name=opts["name"],
                tag=opts["tag"],
                port=opts["port"],
                platforms=opts["platforms"],
                output_tar=out_tar,
                log=self._log,
                progress=self._progress,
                push_registry=opts["registry"],
                push=opts["push"],
                build_args=opts["build_args"],
                subdir=opts["subdir"],
                compress=opts["compress"],
                should_cancel=lambda: self.cancel_requested,
            )

            self.final_tar = final_tar

            # 生成 compose
            compose_path = None
            if opts["gen_compose"]:
                compose_text = core.generate_compose(
                    opts["name"], opts["tag"], opts["port"],
                    include_mysql=opts["compose_mysql"],
                    include_redis=opts["compose_redis"],
                    db_password=opts["db_pass"],
                )
                base = final_tar.name
                if base.endswith(".tar.gz"):
                    base = base[:-len(".tar.gz")]
                else:
                    base = final_tar.stem
                compose_path = final_tar.with_name(base + ".compose.yml")
                compose_path.write_text(compose_text, encoding="utf-8", newline="\n")
                self.final_compose = compose_path
                self._log(f"[compose] 已生成 {compose_path}")
                self._log("[compose] 内容预览：\n" + compose_text)

            # 产物目录自动清理：只保留最近 20 个镜像归档
            core.cleanup_old_outputs(Path(opts["out_dir"]), keep=20)

            self._log(f"=== 全部完成，产物: {final_tar} ===")
            self.msg_queue.put(("done", {"tar": str(final_tar),
                                         "compose": str(compose_path) if compose_path else None}))
        except core.BuildCancelled:
            self._log("[cancel] 构建已取消")
            self.msg_queue.put(("cancelled", None))
        except Exception as e:
            self._log(f"[ERROR] {e}")
            self.msg_queue.put(("error", str(e)))
        finally:
            # 清理本次任务克隆的临时源码目录
            for d in self.temp_dirs:
                shutil.rmtree(d, ignore_errors=True)
            self.temp_dirs.clear()

    # ---------- 线程安全回调 ----------

    def _log(self, line: str):
        self.msg_queue.put(("log", line))

    def _progress(self, pct: float, status: str):
        self.msg_queue.put(("progress", (pct, status)))

    # ---------- 主线程轮询 ----------

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    pct, status = payload
                    self.progress["value"] = pct * 100
                    self.status_label.configure(text=status, foreground="orange")
                elif kind == "done":
                    self.building = False
                    self.cancel_requested = False
                    self.build_btn.configure(state="normal", text="开始打包")
                    self.cancel_btn.configure(state="disabled")
                    self.login_btn.configure(state="normal")
                    self.download_btn.configure(state="normal")
                    if payload and payload.get("compose"):
                        self.compose_btn.configure(state="normal")
                    self.status_label.configure(text="✓ 构建完成，可下载", foreground="green")
                    # 更新历史状态
                    if self.history:
                        self.history[0]["status"] = "完成"
                        self.history[0]["tar"] = payload.get("tar", "") if payload else ""
                        self._save_history()
                        self._refresh_history()
                    messagebox.showinfo("完成", "镜像打包完成！点击「下载打包好的镜像文件」保存。")
                elif kind == "cancelled":
                    self.building = False
                    self.cancel_requested = False
                    self.build_btn.configure(state="normal", text="开始打包")
                    self.cancel_btn.configure(state="disabled")
                    self.login_btn.configure(state="normal")
                    self.status_label.configure(text="已取消", foreground="gray")
                    if self.history:
                        self.history[0]["status"] = "已取消"
                        self._save_history()
                        self._refresh_history()
                elif kind == "error":
                    self.building = False
                    self.cancel_requested = False
                    self.build_btn.configure(state="normal", text="开始打包")
                    self.cancel_btn.configure(state="disabled")
                    self.login_btn.configure(state="normal")
                    self.status_label.configure(text="✗ 构建失败", foreground="red")
                    if self.history:
                        self.history[0]["status"] = "失败"
                        self._save_history()
                        self._refresh_history()
                    messagebox.showerror("构建失败", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _append_log(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _update_eta(self):
        if self.building and self.start_time > 0:
            elapsed = time.time() - self.start_time
            pct = self.progress["value"] / 100.0
            if pct > 0.02:
                eta = elapsed / pct - elapsed
                if eta > 0:
                    mm, ss = divmod(int(eta), 60)
                    hh, mm = divmod(mm, 60)
                    eta_str = f"预计剩余: {hh:02d}:{mm:02d}:{ss:02d}" if hh else f"预计剩余: {mm:02d}:{ss:02d}"
                else:
                    eta_str = "即将完成..."
                self.eta_label.configure(text=f"已用时 {int(elapsed)}s  |  {eta_str}  |  进度 {pct*100:.1f}%")
            else:
                self.eta_label.configure(text=f"已用时 {int(elapsed)}s  |  正在初始化...")
        self.root.after(500, self._update_eta)

    # ---------- 下载 ----------

    def _download_tar(self):
        if not self.final_tar or not self.final_tar.exists():
            messagebox.showwarning("提示", "还没有可下载的文件")
            return
        dest = filedialog.asksaveasfilename(
            initialfile=self.final_tar.name,
            filetypes=[("Docker 镜像归档", "*.tar *.tar.gz"), ("所有文件", "*.*")],
            title="保存镜像文件到...",
        )
        if not dest:
            return
        shutil.copy2(self.final_tar, dest)
        self._append_log(f"[save] 已保存到: {dest}")
        messagebox.showinfo("完成", f"镜像文件已保存到:\n{dest}\n\n在目标机器上用 docker load -i {Path(dest).name} 即可导入。")

    def _download_compose(self):
        if not self.final_compose or not self.final_compose.exists():
            messagebox.showwarning("提示", "还没有可下载的 compose 文件")
            return
        dest = filedialog.asksaveasfilename(
            defaultextension=".yml",
            initialfile=self.final_compose.name,
            filetypes=[("YAML 文件", "*.yml"), ("所有文件", "*.*")],
            title="保存 docker-compose.yml 到...",
        )
        if not dest:
            return
        shutil.copy2(self.final_compose, dest)
        self._append_log(f"[save] compose 已保存到: {dest}")


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    PackApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
