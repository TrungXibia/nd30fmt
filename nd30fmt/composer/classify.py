"""Phân loại dòng nội dung cho trình soạn thảo, có mức tin cậy.

- Dấu hiệu rõ ràng (Điều n., 1., a), I., -, Chương, Mục) -> quy tắc, tin cậy cao.
- Dòng không có dấu hiệu -> giữ là đoạn thường (tin cậy thấp) để người dùng tự chọn.
"""
from __future__ import annotations

from .importer import classify_rule

HIGH = 0.85
MEDIUM = 0.65
MAX_LINES = 60
MAX_LINE = 1000


def level(conf: float | None) -> str:
    if conf is None:
        return "low"
    return "high" if conf >= HIGH else "medium" if conf >= MEDIUM else "low"


def classify_lines(lines: list[str]) -> dict:
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValueError(f"Chọn từ 1 đến {MAX_LINES} dòng")
    if any(not isinstance(x, str) or len(x) > MAX_LINE for x in lines):
        raise ValueError(f"Mỗi dòng tối đa {MAX_LINE} ký tự")
    out = []
    for raw in lines:
        text = raw.strip()
        hit = classify_rule(text) if text else None
        if hit:
            kind, skip, num = hit
            out.append({"kind": kind, "strip": skip, "number": num, "confidence": 1.0, "level": "high", "source": "rule"})
        else:
            out.append({"kind": "p", "strip": 0, "number": "", "confidence": None, "level": "low", "source": "default"})
    return {"lines": out, "thresholds": {"high": HIGH, "medium": MEDIUM}}
