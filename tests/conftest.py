"""Cho phép các test ở tests/nd30, tests/hd05, tests/common dùng chung dữ liệu mẫu trong tests/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
