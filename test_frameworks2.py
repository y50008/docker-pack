# -*- coding: utf-8 -*-
import sys, tempfile
from pathlib import Path
sys.path.insert(0, r'C:\Users\y5000\Doubao\chats\2026-10-08\new-chat-3\docker-pack-gui')
import core

CASES = {
    'vite.config.ts': core.ProjectType.VITE,
    'vue.config.js': core.ProjectType.VITE,
    'svelte.config.js': core.ProjectType.VITE,
    'deno.json': core.ProjectType.DENO,
    'mix.exs': core.ProjectType.ELIXIR,
    'stack.yaml': core.ProjectType.HASKELL,
    'package.yaml': core.ProjectType.HASKELL,
    'Project.toml': core.ProjectType.JULIA,
    'Package.swift': core.ProjectType.SWIFT,
    'package.json': core.ProjectType.NODE,  # 回归：普通 node 不被 Vite 误判
}

for marker, expect in CASES.items():
    d = Path(tempfile.mkdtemp())
    if marker in ('vite.config.ts', 'vue.config.js', 'svelte.config.js', 'package.json'):
        (d / marker).write_text('{}')
    else:
        (d / marker).write_text('x')
    got = core.detect_project_type(d)
    assert got == expect, f"{marker}: got {got}, expect {expect}"
    print(f"[OK] {marker} -> {got}")

# 模板生成（新类型 + 端口占位符）
for ptype, marker, extra in [
    (core.ProjectType.VITE, 'vite.config.ts', 'package.json'),
    (core.ProjectType.DENO, 'deno.json', 'main.ts'),
    (core.ProjectType.ELIXIR, 'mix.exs', None),
    (core.ProjectType.HASKELL, 'stack.yaml', None),
    (core.ProjectType.JULIA, 'Project.toml', None),
    (core.ProjectType.SWIFT, 'Package.swift', None),
]:
    d = Path(tempfile.mkdtemp())
    (d / marker).write_text('x')
    if extra:
        (d / extra).write_text('x')
    core.prepare_dockerfile(d, ptype, 8080)
    df = (d / 'Dockerfile').read_text()
    assert 'FROM' in df and '.dockerignore' and (d / '.dockerignore').exists()
    print(f"[OK] {ptype} Dockerfile 生成")

# Deno 入口自动替换
d = Path(tempfile.mkdtemp())
(d / 'deno.json').write_text('{}')
(d / 'server.ts').write_text('x')
core.prepare_dockerfile(d, core.ProjectType.DENO, 8080)
assert '"server.ts"' in (d / 'Dockerfile').read_text()
print("[OK] Deno 入口自动替换 server.ts")

print('ALL PASS')
