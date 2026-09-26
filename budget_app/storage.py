import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterable, List, Optional


DEFAULT_DATA_DIR = "./data"
TRANSACTIONS_FILE = "transactions.jsonl"
CATEGORIES_FILE = "categories.jsonl"
BUDGETS_FILE = "budgets.jsonl"

DEFAULT_CATEGORIES = ["food", "transport", "rent", "salary", "utilities", "entertainment"]


class JsonlStorage:
    """
    JSONL 파일 I/O 및 스트리밍 전담 저장소 엔진
    - yield 기반 제너레이터 스트리밍
    - 임시 파일 및 os.replace를 활용한 안전한 원자적 쓰기(Atomic Write)
    """
    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self._ensure_init()

    def _ensure_init(self) -> None:
        """데이터 디렉터리 및 기본 파일 초기화"""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        cat_path = self.get_path(CATEGORIES_FILE)
        if not cat_path.exists():
            # 기본 카테고리 자동 생성
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

    def stream_items(self, filename: str) -> Generator[Dict[str, Any], None, None]:
        """
        제너레이터를 사용하여 JSONL 파일을 앞에서부터 한 줄씩 스트리밍 처리
        """
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
        파일의 끝에서부터 역순으로 한 줄씩 스트리밍(최신순 조회)
        대용량 파일 전체를 메모리에 올리지 않고 버퍼 단위로 역방향 탐색
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

            # 남아있는 첫 줄 처리
            last_line = buffer.decode("utf-8", errors="ignore").strip()
            if last_line:
                try:
                    yield json.loads(last_line)
                except json.JSONDecodeError:
                    pass

    def append_item(self, filename: str, item_dict: Dict[str, Any]) -> None:
        """항목 1건을 파일 끝에 추가"""
        path = self.get_path(filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item_dict, ensure_ascii=False) + "\n")

    def append_items(self, filename: str, items: Iterable[Dict[str, Any]]) -> int:
        """여러 항목을 파일 끝에 추가하고 추가된 건수 반환"""
        path = self.get_path(filename)
        count = 0
        with open(path, "a", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        return count

    def atomic_write(self, filename: str, items: Iterable[Dict[str, Any]]) -> None:
        """
        원자적 교체(Atomic Replace):
        임시 파일(.tmp)에 모두 기록한 뒤 완료되면 os.replace로 원본 교체.
        쓰기 중단이나 시스템 비정상 종료 시에도 기존 데이터 손상을 방지함.
        """
        target_path = self.get_path(filename)
        temp_path = self.data_dir / f"{filename}.tmp"

        with open(temp_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        os.replace(temp_path, target_path)

    def atomic_update(
        self,
        filename: str,
        match_fn: Callable[[Dict[str, Any]], bool],
        update_fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    ) -> bool:
        """
        스트리밍하며 일치하는 항목을 수정하거나 삭제(None 반환 시 삭제).
        성공 여부를 반환.
        """
        target_path = self.get_path(filename)
        temp_path = self.data_dir / f"{filename}.tmp"
        found = False

        with open(temp_path, "w", encoding="utf-8") as out_f:
            for item in self.stream_items(filename):
                if match_fn(item):
                    found = True
                    new_item = update_fn(item)
                    if new_item is not None:
                        out_f.write(json.dumps(new_item, ensure_ascii=False) + "\n")
                else:
                    out_f.write(json.dumps(item, ensure_ascii=False) + "\n")

        os.replace(temp_path, target_path)
        return found
