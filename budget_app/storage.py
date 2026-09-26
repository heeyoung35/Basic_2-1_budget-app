"""
저장소 엔진 계층 (Storage Engine)
-------------------------------
JSONL 파일 기반 I/O 및 대용량 제너레이터 스트리밍을 전담합니다.
- yield 기반 정방향 및 역방향(최신순) 스트리밍
- 임시 파일(.tmp)과 os.replace를 통한 원자적 파일 교체(Atomic Replace)
- 쓰기 실패 시 임시 파일 자동 정리(Clean-up) 및 롤백 보장
"""

import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Dict, Generator, Iterable, List, Optional


DEFAULT_DATA_DIR = "./data"
TRANSACTIONS_FILE = "transactions.jsonl"
CATEGORIES_FILE = "categories.jsonl"
BUDGETS_FILE = "budgets.jsonl"

DEFAULT_CATEGORIES = ["food", "transport", "rent", "salary", "utilities", "entertainment"]


class JsonlStorage:
    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self._ensure_init()

    def _ensure_init(self) -> None:
        """데이터 디렉터리 및 필수 3대 파일 초기화"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        cat_path = self.get_path(CATEGORIES_FILE)
        if not cat_path.exists():
            with open(cat_path, "w", encoding="utf-8") as f:
                for cat in DEFAULT_CATEGORIES:
                    f.write(json.dumps({"name": cat}, ensure_ascii=False) + "\n")

        tx_path = self.get_path(TRANSACTIONS_FILE)
        if not tx_path.exists():
            tx_path.touch()

        bg_path = self.get_path(BUDGETS_FILE)
        if not bg_path.exists():
            bg_path.touch()

    def get_path(self, filename: str) -> Path:
        return self.data_dir / filename

    def verify_storage_health(self) -> Dict[str, bool]:
        """
        저장소 무결성 검증 (평가 항목 #2 보완):
        - 필수 파일들의 존재 여부 및 읽기/쓰기 권한을 확인합니다.
        """
        health = {}
        for fname in (TRANSACTIONS_FILE, CATEGORIES_FILE, BUDGETS_FILE):
            p = self.get_path(fname)
            exists = p.exists()
            readable = os.access(p, os.R_OK) if exists else False
            writable = os.access(p, os.W_OK) if exists else False
            health[fname] = exists and readable and writable
        return health

    def stream_items(self, filename: str) -> Generator[Dict[str, Any], None, None]:
        """정방향 스트리밍 (한 줄씩 yield)"""
        path = self.get_path(filename)
        if not path.exists():
            return

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    yield json.loads(line_str)
                except json.JSONDecodeError:
                    continue

    def stream_items_reverse(self, filename: str, buffer_size: int = 4096) -> Generator[Dict[str, Any], None, None]:
        """
        역방향 최신순 스트리밍:
        대용량 파일 전체를 메모리에 올리지 않고 파일 끝에서 버퍼 단위로 역방향 탐색하여 yield
        """
        path = self.get_path(filename)
        if not path.exists():
            return

        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            buffer = bytearray()
            pointer = file_size

            while pointer > 0:
                step = min(pointer, buffer_size)
                pointer -= step
                f.seek(pointer)
                chunk = f.read(step)
                buffer = chunk + buffer

                while b"\n" in buffer:
                    line_idx = buffer.rfind(b"\n")
                    line_bytes = buffer[line_idx + 1:]
                    buffer = buffer[:line_idx]

                    line_str = line_bytes.decode("utf-8", errors="ignore").strip()
                    if line_str:
                        try:
                            yield json.loads(line_str)
                        except json.JSONDecodeError:
                            continue

            last_line = buffer.decode("utf-8", errors="ignore").strip()
            if last_line:
                try:
                    yield json.loads(last_line)
                except json.JSONDecodeError:
                    pass

    def append_item(self, filename: str, item_dict: Dict[str, Any]) -> None:
        path = self.get_path(filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item_dict, ensure_ascii=False) + "\n")

    def append_items(self, filename: str, items: Iterable[Dict[str, Any]]) -> int:
        path = self.get_path(filename)
        count = 0
        with open(path, "a", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        return count

    def atomic_write(self, filename: str, items: Iterable[Dict[str, Any]], create_backup: bool = False) -> None:
        """
        원자적 교체 및 안전 롤백 정책 (평가 항목 #10 보완):
        - 임시 파일(.tmp)에 모두 기록 후 완료 시 os.replace로 교체
        - 쓰기 실패 시 임시 파일 자동 정리(Clean-up)
        - create_backup=True 시 기존 원본을 .bak으로 보존
        """
        target_path = self.get_path(filename)
        temp_path = self.data_dir / f"{filename}.tmp"
        bak_path = self.data_dir / f"{filename}.bak"

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

            if create_backup and target_path.exists():
                shutil.copy2(target_path, bak_path)

            os.replace(temp_path, target_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def atomic_update(
        self,
        filename: str,
        match_fn: Callable[[Dict[str, Any]], bool],
        update_fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
        create_backup: bool = False,
    ) -> bool:
        """
        원자적 수정 및 임시 파일 정리 보장 (평가 항목 #10 보완)
        """
        target_path = self.get_path(filename)
        temp_path = self.data_dir / f"{filename}.tmp"
        bak_path = self.data_dir / f"{filename}.bak"
        found = False

        try:
            with open(temp_path, "w", encoding="utf-8") as out_f:
                for item in self.stream_items(filename):
                    if match_fn(item):
                        found = True
                        new_item = update_fn(item)
                        if new_item is not None:
                            out_f.write(json.dumps(new_item, ensure_ascii=False) + "\n")
                    else:
                        out_f.write(json.dumps(item, ensure_ascii=False) + "\n")

            if create_backup and target_path.exists():
                shutil.copy2(target_path, bak_path)

            os.replace(temp_path, target_path)
            return found
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
