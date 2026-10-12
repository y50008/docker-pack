# -*- coding: utf-8 -*-
import sys, tempfile
from pathlib import Path
sys.path.insert(0, r'C:\Users\y5000\Doubao\chats\2026-10-08\new-chat-3\docker-pack-gui')
import core

cases = [
    ('Next.js', {'package.json': '{}', 'next.config.js': 'module.exports={}', 'src/index.js': 'x'}, core.ProjectType.NEXTJS),
    ('Django', {'manage.py': 'x', 'requirements.txt': 'django', 'app/wsgi.py': 'x'}, core.ProjectType.DJANGO),
    ('FastAPI', {'requirements.txt': 'fastapi', 'main.py': 'app = FastAPI()'}, core.ProjectType.FASTAPI),
    ('SpringBoot', {'pom.xml': '<project>spring-boot-starter-parent</project>', 'src/main/java/A.java': 'x'}, core.ProjectType.SPRING_BOOT),
    ('普通Python', {'requirements.txt': 'flask', 'app.py': 'x'}, core.ProjectType.PYTHON),
    ('普通Maven', {'pom.xml': '<project>maven</project>'}, core.ProjectType.MAVEN),
    ('普通Node', {'package.json': '{}', 'index.js': 'x'}, core.ProjectType.NODE),
    ('自带Dockerfile', {'Dockerfile': 'FROM alpine'}, core.ProjectType.CUSTOM),
]
all_ok = True
for name, files, expect in cases:
    d = Path(tempfile.mkdtemp())
    for fn, content in files.items():
        p = d / fn
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    got = core.detect_project_type(d)
    ok = got == expect
    all_ok = all_ok and ok
    print(f'[{"OK" if ok else "FAIL"}] {name}: expect={expect} got={got}')

# Django wsgi 模块解析测试
d = Path(tempfile.mkdtemp())
(d / 'manage.py').write_text('x')
(d / 'myproject').mkdir()
(d / 'myproject' / 'wsgi.py').write_text('x')
(d / 'requirements.txt').write_text('django')
core.prepare_dockerfile(d, core.ProjectType.DJANGO, 8000)
content = (d / 'Dockerfile').read_text()
assert 'myproject.wsgi' in content, f"wsgi 模块未正确解析: {content}"
print('[OK] Django wsgi 模块解析: myproject.wsgi')

print('ALL PASS' if all_ok else 'HAS FAILURES')
