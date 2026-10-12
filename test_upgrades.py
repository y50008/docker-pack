# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, r'C:\Users\y5000\Doubao\chats\2026-10-08\new-chat-3\docker-pack-gui')
import core

# 1. compose 基本版
c1 = core.generate_compose('my-app', 'v1.0', 8080)
assert 'image: my-app:v1.0' in c1 and '8080:8080' in c1 and 'version: "3.8"' in c1
print('[OK] compose 基本版')

# 2. compose 含 MySQL + Redis
c2 = core.generate_compose('my-app', 'v1.0', 8080, include_mysql=True, include_redis=True, db_password='abc123')
assert 'mysql:8.0' in c2 and 'redis:7-alpine' in c2 and 'MYSQL_ROOT_PASSWORD=abc123' in c2
assert 'depends_on' in c2 and 'mysql-data:' in c2 and 'redis-data:' in c2
print('[OK] compose MySQL+Redis 版')

# 3. 模板含 BuildKit 缓存挂载
assert '--mount=type=cache,target=/root/.npm' in core.DOCKERFILES[core.ProjectType.NODE]
assert '--mount=type=cache,target=/root/.cache/pip' in core.DOCKERFILES[core.ProjectType.PYTHON]
assert '--mount=type=cache,target=/root/.m2' in core.DOCKERFILES[core.ProjectType.MAVEN]
assert '--mount=type=cache,target=/root/.gradle' in core.DOCKERFILES[core.ProjectType.GRADLE]
assert '--mount=type=cache,target=/go/pkg/mod' in core.DOCKERFILES[core.ProjectType.GO]
print('[OK] 构建加速缓存挂载')

# 4. Django 模板仍可正常生成
import tempfile
d = Path(tempfile.mkdtemp())
(d / 'manage.py').write_text('x')
(d / 'app').mkdir()
(d / 'app' / 'wsgi.py').write_text('x')
(d / 'requirements.txt').write_text('django')
core.prepare_dockerfile(d, core.ProjectType.DJANGO, 8000)
content = (d / 'Dockerfile').read_text()
assert 'app.wsgi' in content and 'gunicorn' in content
print('[OK] Django 模板生成（含 wsgi 解析）')

print('ALL PASS')
