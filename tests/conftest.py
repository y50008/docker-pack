# -*- coding: utf-8 -*-
"""pytest 公共配置：把项目根目录加入 sys.path，使 tests/ 下的测试可直接 import core。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
