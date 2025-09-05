# utils/admit_window.py
import os
from datetime import datetime
from typing import Optional, Tuple

FMT = "%Y-%m-%d %H:%M:%S"

def _p(key: str) -> Optional[datetime]:
    v = os.getenv(key, "").strip()
    if not v:
        return None
    try:
        return datetime.strptime(v, FMT)
    except ValueError:
        return None

def get_student_window() -> Tuple[Optional[datetime], Optional[datetime]]:
    # admite variables con y sin typo para no romper
    start = (_p("FIRST_TIME_STUDENT_ADMIT")
             or _p("START_TIME_STUDENT_ADMIT")
             or _p("ADMIT_START"))
    end   = (_p("LAST_TIME_STUDENT_ADMIT")
             or _p("LAST_TIME_SUTUDENT_ADMIT"))  # compat
    return start, end

def is_student_window_open(now: Optional[datetime] = None) -> bool:
    _, end = get_student_window()
    if not end:
        return True  # sin fecha → abierto
    now = now or datetime.now()
    return now <= end

def fmt_spanish(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    # 26/08/2025 16:30 (simple y claro)
    return dt.strftime("%d/%m/%Y %H:%M")
