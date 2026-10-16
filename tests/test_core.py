# -*- coding: utf-8 -*-
"""core.py 的 pytest 回归测试套件（不依赖 docker，只验证纯逻辑）。

合并了原根目录 test_frameworks.py / test_frameworks2.py / test_upgrades.py /
test_p0_fixes.py 的全部检查，并新增 v1.4 功能的校验：
输入校验、错误中文化、自定义模板覆盖、产物自动清理。
"""
import os
import shutil

import pytest

import core


# ---------- 辅助 ----------

def mkproj(root, **files):
    """在 root 下按 {相对路径: 内容} 造一个临时项目。"""
    for name, content in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


# ---------- 一、项目类型识别 ----------

@pytest.mark.parametrize("files,expected", [
    ({"package.json": "{}", "next.config.js": "module.exports={}", "src/index.js": "x"},
     core.ProjectType.NEXTJS),
    ({"manage.py": "x", "requirements.txt": "django", "app/wsgi.py": "x"},
     core.ProjectType.DJANGO),
    ({"requirements.txt": "fastapi\nuvicorn", "main.py": "app = FastAPI()"},
     core.ProjectType.FASTAPI),
    ({"pom.xml": "<project>spring-boot-starter-parent</project>",
      "src/main/java/A.java": "x"},
     core.ProjectType.SPRING_BOOT),
    ({"requirements.txt": "flask", "app.py": "x"}, core.ProjectType.PYTHON),
    ({"pom.xml": "<project>maven</project>"}, core.ProjectType.MAVEN),
    ({"package.json": "{}", "index.js": "x"}, core.ProjectType.NODE),
    ({"Dockerfile": "FROM alpine"}, core.ProjectType.CUSTOM),
    ({"vite.config.ts": "{}"}, core.ProjectType.VITE),
    ({"vue.config.js": "{}"}, core.ProjectType.VITE),
    ({"svelte.config.js": "{}"}, core.ProjectType.VITE),
    ({"deno.json": "{}"}, core.ProjectType.DENO),
    ({"mix.exs": "x"}, core.ProjectType.ELIXIR),
    ({"stack.yaml": "x"}, core.ProjectType.HASKELL),
    ({"package.yaml": "x"}, core.ProjectType.HASKELL),
    ({"Project.toml": "x"}, core.ProjectType.JULIA),
    ({"Package.swift": "x"}, core.ProjectType.SWIFT),
])
def test_detect_project_type(tmp_path, files, expected):
    mkproj(tmp_path, **files)
    assert core.detect_project_type(tmp_path) == expected


def test_detect_priority(tmp_path):
    """专项框架识别优先级回归。"""
    # next.config 必须先于 package.json
    mkproj(tmp_path, **{"package.json": "{}", "next.config.js": "x"})
    assert core.detect_project_type(tmp_path) == core.ProjectType.NEXTJS
    # 普通 node 项目不被 Vite 误判
    for f in list(tmp_path.glob("*")):
        f.unlink()
    (tmp_path / "package.json").write_text("{}")
    assert core.detect_project_type(tmp_path) == core.ProjectType.NODE


# ---------- 二、模板生成与入口替换 ----------

def test_new_types_dockerfile_generated(tmp_path):
    """新增专项类型都能生成含 FROM 的 Dockerfile 和 .dockerignore。"""
    cases = [
        (core.ProjectType.VITE, "vite.config.ts", "package.json"),
        (core.ProjectType.DENO, "deno.json", "main.ts"),
        (core.ProjectType.ELIXIR, "mix.exs", None),
        (core.ProjectType.HASKELL, "stack.yaml", None),
        (core.ProjectType.JULIA, "Project.toml", None),
        (core.ProjectType.SWIFT, "Package.swift", None),
    ]
    for ptype, marker, extra in cases:
        d = tmp_path / ptype
        d.mkdir()
        files = {marker: "x"}
        if extra:
            files[extra] = "x"
        mkproj(d, **files)
        core.prepare_dockerfile(d, ptype, 8080)
        df = (d / "Dockerfile").read_text(encoding="utf-8")
        assert "FROM" in df
        assert (d / ".dockerignore").exists()


def test_deno_entry_replaced(tmp_path):
    mkproj(tmp_path, **{"deno.json": "{}", "server.ts": "x"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.DENO, 8080)
    assert '"server.ts"' in (tmp_path / "Dockerfile").read_text(encoding="utf-8")


def test_django_wsgi_module_resolved(tmp_path):
    mkproj(tmp_path, **{"manage.py": "x", "myproject/wsgi.py": "x",
                        "requirements.txt": "django"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.DJANGO, 8000)
    content = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "myproject.wsgi" in content
    assert "gunicorn" in content


def test_buildkit_cache_mounts_present():
    """各语言模板保留 BuildKit 缓存挂载（国内加速）。"""
    assert "--mount=type=cache,target=/root/.npm" in core.DOCKERFILES[core.ProjectType.NODE]
    assert "--mount=type=cache,target=/root/.cache/pip" in core.DOCKERFILES[core.ProjectType.PYTHON]
    assert "--mount=type=cache,target=/root/.m2" in core.DOCKERFILES[core.ProjectType.MAVEN]
    assert "--mount=type=cache,target=/root/.gradle" in core.DOCKERFILES[core.ProjectType.GRADLE]
    assert "--mount=type=cache,target=/go/pkg/mod" in core.DOCKERFILES[core.ProjectType.GO]


# ---------- 三、P0 修复回归 ----------

def test_flutter_template_valid(tmp_path):
    mkproj(tmp_path, **{"pubspec.yaml": "name: demo"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.FLUTTER, 8080)
    df = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    first = next(l for l in df.splitlines() if l.strip() and not l.strip().startswith("#"))
    assert first.startswith("FROM")
    assert not any(l.startswith("--") for l in df.splitlines())
    assert "COPY pubspec.* ./" in df


def test_rust_template_braces_and_wildcard(tmp_path):
    mkproj(tmp_path, **{"Cargo.toml": "[package]\nname='x'"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.RUST, 8080)
    df = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    # 旧版 str.format 会被 fn main() {} 的花括号炸掉，replace 渲染则安全
    assert "FROM" in df
    assert "COPY Cargo.* ./" in df
    assert "fn main() {}" in df


@pytest.mark.parametrize("extra,ptype", [
    ({"package.json": "{}"}, core.ProjectType.NODE),
    ({"package.json": "{}", "next.config.js": "module.exports={}"}, core.ProjectType.NEXTJS),
])
def test_node_runner_lockfile_tolerant(tmp_path, extra, ptype):
    mkproj(tmp_path, **extra)
    core.prepare_dockerfile(tmp_path, ptype, 8080)
    df = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "npm ci --omit=dev || npm install --omit=dev" in df


@pytest.mark.parametrize("marker,ptype,needle", [
    ("go.mod", core.ProjectType.GO, "COPY go.* ./"),
    ("Gemfile", core.ProjectType.RUBY, "COPY Gemfile* ./"),
    ("composer.json", core.ProjectType.PHP, "COPY composer.* ./"),
])
def test_lockfile_wildcard_copy(tmp_path, marker, ptype, needle):
    mkproj(tmp_path, **{marker: "x"})
    core.prepare_dockerfile(tmp_path, ptype, 8080)
    assert needle in (tmp_path / "Dockerfile").read_text(encoding="utf-8")


def test_python_pyproject_whole_build(tmp_path):
    """无 requirements.txt 的 pyproject 项目切换为整包构建模式。"""
    mkproj(tmp_path, **{"pyproject.toml": "[project]\nname='x'", "main.py": "print(1)"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.PYTHON, 8080)
    df = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY requirements.txt" not in df
    assert "pip wheel --no-cache-dir --wheel-dir /wheels ." in df


def test_python_requirements_keeps_cache(tmp_path):
    """有 requirements.txt 的项目保持依赖缓存优化模板。"""
    mkproj(tmp_path, **{"requirements.txt": "flask", "app.py": "print(1)"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.PYTHON, 8080)
    df = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt" in df


def test_vite_nginx_user_port(tmp_path):
    mkproj(tmp_path, **{"vite.config.ts": "export default {}"})
    core.prepare_dockerfile(tmp_path, core.ProjectType.VITE, 9090)
    df = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
    assert "listen 9090;" in df
    assert "EXPOSE 9090" in df


def test_compose_no_duplicate_keys():
    text = core.generate_compose("my-app", "v1", 8080, include_mysql=True, include_redis=True)
    app_part = text.split("  mysql:")[0] if "  mysql:" in text else text
    assert app_part.count("    environment:") == 1
    assert app_part.count("    depends_on:") == 1
    assert "      - mysql" in app_part
    assert "      - redis" in app_part
    assert "DB_USER=root" in text


def test_build_copy_zero_pollution(tmp_path):
    """构建在临时副本中进行：源码目录零写入，用户 .dockerignore 保留。"""
    src = tmp_path / "src"
    mkproj(src, **{"index.js": "console.log(1)", ".dockerignore": "my-custom-rule",
                   "package.json": "{}"})
    bd = core._make_build_copy(src)
    try:
        core.prepare_dockerfile(bd, core.detect_project_type(bd), 8080)
        assert not (src / "Dockerfile").exists()
        assert (src / ".dockerignore").read_text(encoding="utf-8") == "my-custom-rule"
        assert (bd / ".dockerignore").read_text(encoding="utf-8") == "my-custom-rule"
        assert (bd / "Dockerfile").exists()
    finally:
        # 清理 _make_build_copy 在系统临时目录创建的构建副本，避免测试残留
        shutil.rmtree(bd, ignore_errors=True)


# ---------- 四、compose 生成 ----------

def test_compose_basic():
    c = core.generate_compose("my-app", "v1.0", 8080)
    assert "image: my-app:v1.0" in c
    assert "8080:8080" in c
    assert 'version: "3.8"' in c


def test_compose_mysql_redis():
    c = core.generate_compose("my-app", "v1.0", 8080,
                              include_mysql=True, include_redis=True, db_password="abc123")
    assert "mysql:8.0" in c
    assert "redis:7-alpine" in c
    assert "MYSQL_ROOT_PASSWORD=abc123" in c
    assert "depends_on" in c
    assert "mysql-data:" in c
    assert "redis-data:" in c


# ---------- 五、输入校验 ----------

@pytest.mark.parametrize("name,ok", [
    ("my-app", True),
    ("registry.example.com/ns/my-app", True),
    ("my_app", True),
    ("MyApp", False),            # 大写
    ("my app", False),           # 空格
    ("", False),                 # 空
    ("-leading-dash", False),    # 非法开头
])
def test_validate_image_name(name, ok):
    err = core.validate_image_name(name)
    assert (err == "") is ok


@pytest.mark.parametrize("tag,ok", [
    ("latest", True),
    ("v1.0.0", True),
    ("v1_0", True),
    ("", False),
    ("-bad", False),
    (".bad", False),
])
def test_validate_tag(tag, ok):
    err = core.validate_tag(tag)
    assert (err == "") is ok


@pytest.mark.parametrize("port,ok", [
    ("8080", True),
    ("443", True),
    ("1", True),
    ("65535", True),
    ("abc", False),
    ("0", False),
    ("70000", False),
    ("", False),
])
def test_validate_port(port, ok):
    err = core.validate_port(port)
    assert (err == "") is ok


def test_validate_build_args_ok():
    args, err = core.validate_build_args("A=1\nB=2\n# 注释\n\n")
    assert err == ""
    assert args == {"A": "1", "B": "2"}


def test_validate_build_args_empty():
    args, err = core.validate_build_args("")
    assert err == "" and args == {}


def test_validate_build_args_bad_line():
    args, err = core.validate_build_args("NO_EQUAL_SIGN")
    assert err and args == {}


# ---------- 六、错误中文化 ----------

@pytest.mark.parametrize("raw,needle", [
    ("error during connect: open //./pipe/docker_engine", "Docker Desktop"),
    ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", "Docker"),
    ("no space left on device", "磁盘"),
    ("port is already allocated", "端口被占用"),
    ("Head https://registry-1.docker.io/...: dial tcp: i/o timeout", "网络超时"),
    ("denied: requested access to the resource is denied", "docker login"),
    ("failed to solve: process \"/bin/sh -c xxx\" did not complete", "构建失败"),
])
def test_friendly_error_mapped(raw, needle):
    assert needle in core.friendly_error(raw)


def test_friendly_error_unknown_passthrough():
    raw = "some totally unknown and weird error xyz"
    assert core.friendly_error(raw) == raw


# ---------- 七、自定义模板覆盖 ----------

def test_template_override_via_env(monkeypatch, tmp_path):
    tpl_dir = tmp_path / "mytemplates"
    tpl_dir.mkdir()
    (tpl_dir / "nodejs.dockerfile").write_text(
        "FROM alpine:3.19\n# CUSTOM OVERRIDE\nEXPOSE {port}\n", encoding="utf-8")
    monkeypatch.setenv("DOCKER_PACK_TEMPLATES", str(tpl_dir))

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text("{}", encoding="utf-8")
    core.prepare_dockerfile(proj, core.ProjectType.NODE, 9001)
    df = (proj / "Dockerfile").read_text(encoding="utf-8")
    assert "CUSTOM OVERRIDE" in df
    assert "FROM node:20-alpine" not in df  # 内置模板未被使用
    assert "EXPOSE 9001" in df


# ---------- 八、产物自动清理 ----------

def test_cleanup_old_outputs(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for i in range(5):
        f = out / f"img{i}.tar"
        f.write_text("x")
        os.utime(f, (1000 + i, 1000 + i))
    gz = out / "img_gz.tar.gz"
    gz.write_text("x")
    os.utime(gz, (2000, 2000))

    core.cleanup_old_outputs(out, keep=3)
    assert sorted(p.name for p in out.glob("*.tar*")) == [
        "img3.tar", "img4.tar", "img_gz.tar.gz"]


def test_cleanup_old_outputs_missing_dir(tmp_path):
    # 目录不存在时静默返回，不抛异常
    core.cleanup_old_outputs(tmp_path / "nope", keep=2)
