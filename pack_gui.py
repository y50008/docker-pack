#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pack_gui.py — Docker 打包工具可视化界面
"""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# 兼容 PyInstaller 打包后的导入
sys.path.insert(0, str(Path(__file__).parent))
import core


class PackApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Docker 项目打包工具")
        root.geometry("860x720")
        root.minsize(780, 640)

        self.msg_queue: queue.Queue = queue.Queue()
        self.temp_dirs: list[Path] = []
        self.final_tar: Path | None = None
        self.start_time: float = 0.0
        self.building = False

        self._build_ui()
        self._print_banner()
        self.root.after(100, self._poll_queue)
        self.root.after(500, self._update_eta)

    def _print_banner(self):
        """启动时输出绿色作者信息"""
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, "作者: y50008    ", ("green",))
        self.log_text.insert(tk.END, "来源: www.52pojie.com\n", ("green",))
        self.log_text.insert(tk.END, "开源地址: https://github.com/y50008/docker-pack\n", ("green",))
        self.log_text.insert(tk.END, "-" * 60 + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # ---------- UI ----------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # 1. 源码来源
        frm_src = ttk.LabelFrame(self.root, text="① 选择源码来源")
        frm_src.pack(fill="x", **pad)

        self.src_mode = tk.StringVar(value="local")
        ttk.Radiobutton(frm_src, text="本地目录", variable=self.src_mode,
                        value="local", command=self._on_mode_change).grid(row=0, column=0, sticky="w", padx=8)
        ttk.Radiobutton(frm_src, text="项目地址（github 或其他）", variable=self.src_mode,
                        value="git", command=self._on_mode_change).grid(row=0, column=1, sticky="w", padx=8)

        self.local_entry = ttk.Entry(frm_src)
        self.local_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        self.browse_btn = ttk.Button(frm_src, text="浏览...", command=self._browse_local)
        self.browse_btn.grid(row=1, column=2, padx=8)

        self.git_entry = ttk.Entry(frm_src)
        self.git_entry.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        self.git_entry.grid_remove()

        frm_src.columnconfigure(0, weight=1)
        frm_src.columnconfigure(1, weight=1)
        frm_src.columnconfigure(2, weight=0)

        # 2. 镜像配置
        frm_img = ttk.LabelFrame(self.root, text="② 镜像配置")
        frm_img.pack(fill="x", **pad)

        ttk.Label(frm_img, text="镜像名:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.name_var = tk.StringVar(value="my-app")
        ttk.Entry(frm_img, textvariable=self.name_var, width=24).grid(row=0, column=1, padx=4)

        ttk.Label(frm_img, text="标签:").grid(row=0, column=2, padx=6, pady=6)
        self.tag_var = tk.StringVar(value="latest")
        ttk.Entry(frm_img, textvariable=self.tag_var, width=12).grid(row=0, column=3, padx=4)

        ttk.Label(frm_img, text="暴露端口:").grid(row=0, column=4, padx=6, pady=6)
        self.port_var = tk.StringVar(value="8080")
        ttk.Entry(frm_img, textvariable=self.port_var, width=8).grid(row=0, column=5, padx=4)

        # 3. 架构选择
        frm_arch = ttk.LabelFrame(self.root, text="③ 选择目标架构（可多选）")
        frm_arch.pack(fill="x", **pad)

        # (变量, 显示文本, 平台ID)
        self.arch_options = [
            (tk.BooleanVar(value=True),  "linux/amd64",  "x86_64：普通 PC / 绝大多数云服务器"),
            (tk.BooleanVar(value=False), "linux/arm64",  "aarch64：AWS Graviton / Apple M / 阿里云 ARM / 树莓派5"),
            (tk.BooleanVar(value=False), "linux/arm/v7", "32位 ARM：树莓派3/4 老系统 / IoT 设备"),
            (tk.BooleanVar(value=False), "linux/riscv64","RISC-V：新兴开发板 / 边缘计算"),
        ]
        self.arch_all = tk.BooleanVar(value=False)

        for i, (var, pid, desc) in enumerate(self.arch_options):
            row = i // 2
            col = i % 2
            ttk.Checkbutton(frm_arch, text=f"{pid}  —  {desc}",
                           variable=var,
                           command=self._on_arch_change).grid(row=row, column=col, sticky="w", padx=10, pady=3)

        ttk.Checkbutton(frm_arch, text="全部常用架构（amd64 + arm64 + arm/v7 + riscv64，构建最慢）",
                        variable=self.arch_all,
                        command=self._on_arch_all).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=4)

        # 4. 操作按钮
        frm_btn = ttk.Frame(self.root)
        frm_btn.pack(fill="x", **pad)

        self.build_btn = ttk.Button(frm_btn, text="开始打包", command=self._start_build)
        self.build_btn.pack(side="left", padx=8)

        self.download_btn = ttk.Button(frm_btn, text="下载打包好的镜像文件",
                                       command=self._download_tar, state="disabled")
        self.download_btn.pack(side="left", padx=8)

        self.status_label = ttk.Label(frm_btn, text="就绪", foreground="gray")
        self.status_label.pack(side="right", padx=12)

        # 5. 进度条 + 预计时间
        frm_prog = ttk.Frame(self.root)
        frm_prog.pack(fill="x", padx=8, pady=4)

        self.progress = ttk.Progressbar(frm_prog, mode="determinate", maximum=100)
        self.progress.pack(fill="x", side="top")

        self.eta_label = ttk.Label(frm_prog, text="")
        self.eta_label.pack(anchor="w", pady=2)

        # 6. 日志窗口
        frm_log = ttk.LabelFrame(self.root, text="构建日志")
        frm_log.pack(fill="both", expand=True, padx=8, pady=6)

        self.log_text = tk.Text(frm_log, wrap="word", state="disabled",
                                bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        # 配置绿色 tag，用于作者信息等醒目提示
        self.log_text.tag_configure("green", foreground="#4ee44e", font=("Consolas", 20, "bold"))
        scroll = ttk.Scrollbar(frm_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ---------- 交互 ----------

    def _on_mode_change(self):
        if self.src_mode.get() == "local":
            self.git_entry.grid_remove()
            self.local_entry.grid()
            self.browse_btn.grid()
        else:
            self.local_entry.grid_remove()
            self.browse_btn.grid_remove()
            self.git_entry.grid()

    def _browse_local(self):
        d = filedialog.askdirectory(title="选择项目源码目录")
        if d:
            self.local_entry.delete(0, tk.END)
            self.local_entry.insert(0, d)
            # 自动把目录名填成镜像名
            self.name_var.set(Path(d).name.lower().replace("_", "-"))

    def _on_arch_change(self):
        # 至少保留一个
        if not any(v.get() for v, _, _ in self.arch_options):
            self.arch_options[0][0].set(True)
        self.arch_all.set(False)

    def _on_arch_all(self):
        if self.arch_all.get():
            for var, _, _ in self.arch_options:
                var.set(True)

    def _collect_platforms(self) -> list[str]:
        selected = [pid for var, pid, _ in self.arch_options if var.get()]
        if not selected:
            selected = ["linux/amd64"]
        return selected

    # ---------- 构建 ----------

    def _start_build(self):
        if self.building:
            return

        # 校验输入
        if self.src_mode.get() == "local":
            src = self.local_entry.get().strip()
            if not src or not Path(src).is_dir():
                messagebox.showerror("错误", "请选择有效的本地项目目录")
                return
            source_dir = Path(src).resolve()
        else:
            url = self.git_entry.get().strip()
            if not core.is_git_url(url):
                messagebox.showerror("错误", "请输入有效的项目地址（https://github.com/xxx/xxx.git 或其他 Git 仓库地址）")
                return
            source_dir = None  # clone 后确定

        name = self.name_var.get().strip() or "my-app"
        tag = self.tag_var.get().strip() or "latest"
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("错误", "端口必须是数字")
            return

        platforms = self._collect_platforms()

        # 准备输出 tar 路径（临时目录）
        out_dir = Path(tempfile.gettempdir()) / "docker_pack_out"
        out_dir.mkdir(exist_ok=True)
        out_tar = out_dir / f"{name.replace('/', '_')}_{tag}_{'multi' if len(platforms)>1 else platforms[0].replace('/','_')}.tar"
        if out_tar.exists():
            out_tar.unlink()

        # 重置 UI
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self._print_banner()
        self.progress["value"] = 0
        self.download_btn.configure(state="disabled")
        self.build_btn.configure(state="disabled", text="打包中...")
        self.status_label.configure(text="构建中...", foreground="orange")
        self.final_tar = None
        self.start_time = time.time()
        self.building = True

        # 启动子线程
        t = threading.Thread(
            target=self._build_worker,
            args=(source_dir, url if source_dir is None else None, name, tag, port, platforms, out_tar),
            daemon=True,
        )
        t.start()

    def _build_worker(self, source_dir: Path | None, git_url: str | None,
                      name: str, tag: str, port: int,
                      platforms: list[str], out_tar: Path):
        try:
            self._log(f"=== 开始任务 ===")
            self._log(f"镜像: {name}:{tag}  端口: {port}  架构: {platforms}")

            # 如果是 git，先 clone
            if git_url:
                tmp = Path(tempfile.mkdtemp(prefix="docker_pack_src_"))
                self.temp_dirs.append(tmp)
                source_dir = core.git_clone(git_url, tmp, self._log)
                self._log(f"[git] 源码目录: {source_dir}")

            assert source_dir is not None

            core.build_and_export(
                source_dir=source_dir,
                image_name=name,
                tag=tag,
                port=port,
                platforms=platforms,
                output_tar=out_tar,
                log=self._log,
                progress=self._progress,
            )

            self.final_tar = out_tar
            self._log(f"=== 全部完成，产物: {out_tar} ===")
            self.msg_queue.put(("done", None))
        except Exception as e:
            self._log(f"[ERROR] {e}")
            self.msg_queue.put(("error", str(e)))

    # ---------- 线程安全的回调 ----------

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
                    self.build_btn.configure(state="normal", text="开始打包")
                    self.download_btn.configure(state="normal")
                    self.status_label.configure(text="✓ 构建完成，可下载", foreground="green")
                    messagebox.showinfo("完成", "镜像打包完成！点击「下载」按钮保存文件。")
                elif kind == "error":
                    self.building = False
                    self.build_btn.configure(state="normal", text="开始打包")
                    self.status_label.configure(text="✗ 构建失败", foreground="red")
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
            defaultextension=".tar",
            initialfile=self.final_tar.name,
            filetypes=[("Docker 镜像归档", "*.tar"), ("所有文件", "*.*")],
            title="保存镜像文件到...",
        )
        if not dest:
            return
        import shutil
        shutil.copy2(self.final_tar, dest)
        self._append_log(f"[save] 已保存到: {dest}")
        messagebox.showinfo("完成", f"镜像文件已保存到:\n{dest}\n\n在目标机器上用 docker load -i {Path(dest).name} 即可导入。")


def main():
    root = tk.Tk()
    # 适配高 DPI
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    PackApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
