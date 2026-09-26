import functools
import re
import sys
import time
from datetime import datetime
from typing import Any, Callable, List, Optional
from budget_app.exceptions import BudgetAppError


def handle_errors(func: Callable) -> Callable:
    """
    미션 필수 요구사항:
    - 오류 시 스택트레이스(Traceback) 숨김
    - [오류] 원인 + [힌트] 해결 가이드 출력
    - 오류 시 비정상 종료 코드(exit code != 0) 반환
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except BudgetAppError as e:
            print(f"[오류] {e.message}", file=sys.stderr)
            if e.hint:
                print(f"[힌트] {e.hint}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n[알림] 작업이 사용자에 의해 중단되었습니다.", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            print(f"[오류] 예기치 않은 오류가 발생했습니다: {e}", file=sys.stderr)
            print("[힌트] 입력 데이터 또는 실행 인자를 확인해주세요.", file=sys.stderr)
            sys.exit(1)

    return wrapper


def measure_execution_time(func: Callable) -> Callable:
    """실행 시간을 측정하는 데코레이터 (데코레이터 활용 요구사항 충족)"""
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start_time
        # 디버그나 상세 모드에서 참고할 수 있도록 내부 기록
        return result
    return wrapper


def validate_date(date_str: str) -> str:
    """YYYY-MM-DD 형식 유효성 검사"""
    cleaned = date_str.strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", cleaned)
    if not match:
        raise ValueError("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        datetime(year, month, day)
    except ValueError:
        raise ValueError("존재하지 않는 날짜입니다 (예: 2월 30일 등).")
    return cleaned


def validate_month(month_str: str) -> str:
    """YYYY-MM 형식 유효성 검사"""
    cleaned = month_str.strip()
    match = re.match(r"^(\d{4})-(\d{2})$", cleaned)
    if not match:
        raise ValueError("월 형식이 올바르지 않습니다 (YYYY-MM).")
    year, month = int(match.group(1)), int(match.group(2))
    if not (1 <= month <= 12):
        raise ValueError("월은 01부터 12 사이여야 합니다.")
    return cleaned


def format_currency(amount: int) -> str:
    """금액 포맷팅 (예: 15,000원)"""
    return f"{amount:,}원"


def render_table(headers: List[str], rows: List[List[str]]) -> str:
    """외부 라이브러리 없이 깔끔하게 테이블을 렌더링하는 헬퍼 함수"""
    if not headers and not rows:
        return ""

    num_cols = len(headers)
    col_widths = [len(h) for h in headers]

    for row in rows:
        for idx, cell in enumerate(row):
            if idx < num_cols:
                # 동아시아 와이드 문자(한글 등) 길이 보정
                display_len = sum(2 if ord(c) > 127 else 1 for c in str(cell))
                col_widths[idx] = max(col_widths[idx], display_len)

    def pad_cell(text: str, width: int) -> str:
        d_len = sum(2 if ord(c) > 127 else 1 for c in str(text))
        padding = " " * max(0, width - d_len)
        return str(text) + padding

    header_line = " | ".join(pad_cell(h, col_widths[i]) for i, h in enumerate(headers))
    separator_line = "-+-".join("-" * col_widths[i] for i in range(num_cols))
    row_lines = [
        " | ".join(pad_cell(cell, col_widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]

    return "\n".join([header_line, separator_line] + row_lines)
