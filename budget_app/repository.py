import re
from typing import Generator, List, Optional
from budget_app.models import Budget, Category, Transaction
from budget_app.storage import (
    BUDGETS_FILE,
    CATEGORIES_FILE,
    TRANSACTIONS_FILE,
    JsonlStorage,
)


class TransactionRepository:
    def __init__(self, storage: JsonlStorage):
        self.storage = storage

    def generate_next_id(self) -> str:
        """
        가장 큰 TX-숫자를 찾아 다음 ID 생성 (예: TX-000001)
        """
        max_id_num = 0
        for item in self.storage.stream_items(TRANSACTIONS_FILE):
            raw_id = str(item.get("id", ""))
            match = re.search(r"TX-(\d+)", raw_id)
            if match:
                val = int(match.group(1))
                if val > max_id_num:
                    max_id_num = val
        return f"TX-{max_id_num + 1:06d}"

    def add(self, tx: Transaction) -> None:
        """새 거래 내역 파일 추가"""
        self.storage.append_item(TRANSACTIONS_FILE, tx.to_dict())

    def add_batch(self, tx_list: List[Transaction]) -> int:
        """거래 내역 다건 일괄 추가 (import 시 활용)"""
        return self.storage.append_items(
            TRANSACTIONS_FILE, (tx.to_dict() for tx in tx_list)
        )

    def stream_all(self, reverse: bool = True) -> Generator[Transaction, None, None]:
        """
        제너레이터 기반 거래 내역 스트리밍
        reverse=True: 최신순(파일 끝에서 역순 스트리밍)
        """
        stream = (
            self.storage.stream_items_reverse(TRANSACTIONS_FILE)
            if reverse
            else self.storage.stream_items(TRANSACTIONS_FILE)
        )
        for item in stream:
            yield Transaction.from_dict(item)

    def find_by_id(self, tx_id: str) -> Optional[Transaction]:
        """ID로 단건 조회"""
        for item in self.storage.stream_items(TRANSACTIONS_FILE):
            if str(item.get("id")) == str(tx_id):
                return Transaction.from_dict(item)
        return None

    def update(self, updated_tx: Transaction) -> bool:
        """원자적 교체를 통한 거래 수정"""
        return self.storage.atomic_update(
            TRANSACTIONS_FILE,
            match_fn=lambda item: str(item.get("id")) == str(updated_tx.id),
            update_fn=lambda _: updated_tx.to_dict(),
        )

    def delete(self, tx_id: str) -> bool:
        """원자적 교체를 통한 거래 삭제 (None 반환 시 제거)"""
        return self.storage.atomic_update(
            TRANSACTIONS_FILE,
            match_fn=lambda item: str(item.get("id")) == str(tx_id),
            update_fn=lambda _: None,
        )

    def is_category_in_use(self, category_name: str) -> bool:
        """해당 카테고리를 사용하는 거래가 있는지 스트리밍으로 신속 검사"""
        for item in self.storage.stream_items(TRANSACTIONS_FILE):
            if str(item.get("category", "")).lower() == category_name.lower():
                return True
        return False

    def replace_category(self, old_category: str, new_category: str) -> int:
        """카테고리 삭제 시 대체 카테고리로 일괄 업데이트"""
        count = 0
        def update_fn(item):
            nonlocal count
            if str(item.get("category", "")).lower() == old_category.lower():
                item["category"] = new_category
                count += 1
            return item

        self.storage.atomic_update(
            TRANSACTIONS_FILE,
            match_fn=lambda item: str(item.get("category", "")).lower() == old_category.lower(),
            update_fn=update_fn,
        )
        return count


class CategoryRepository:
    def __init__(self, storage: JsonlStorage):
        self.storage = storage

    def list_all(self) -> List[str]:
        """카테고리 목록 조회"""
        cats: List[str] = []
        for item in self.storage.stream_items(CATEGORIES_FILE):
            name = item.get("name")
            if name and name not in cats:
                cats.append(name)
        return cats

    def exists(self, category_name: str) -> bool:
        """카테고리 존재 여부 확인"""
        target = category_name.strip().lower()
        for cat in self.list_all():
            if cat.lower() == target:
                return True
        return False

    def add(self, category_name: str) -> None:
        """카테고리 추가"""
        name = category_name.strip()
        self.storage.append_item(CATEGORIES_FILE, {"name": name})

    def remove(self, category_name: str) -> bool:
        """카테고리 삭제"""
        target = category_name.strip().lower()
        return self.storage.atomic_update(
            CATEGORIES_FILE,
            match_fn=lambda item: str(item.get("name", "")).lower() == target,
            update_fn=lambda _: None,
        )


class BudgetRepository:
    def __init__(self, storage: JsonlStorage):
        self.storage = storage

    def set_budget(self, month: str, amount: int) -> None:
        """월별 예산 설정 (기존 것이 있으면 원자적 갱신, 없으면 추가)"""
        updated = self.storage.atomic_update(
            BUDGETS_FILE,
            match_fn=lambda item: str(item.get("month")) == month,
            update_fn=lambda _: {"month": month, "amount": amount},
        )
        if not updated:
            self.storage.append_item(BUDGETS_FILE, {"month": month, "amount": amount})

    def get_budget(self, month: str) -> Optional[Budget]:
        """특정 월 예산 조회"""
        for item in self.storage.stream_items(BUDGETS_FILE):
            if str(item.get("month")) == month:
                return Budget.from_dict(item)
        return None

    def list_all(self) -> List[Budget]:
        """전체 예산 목록 조회"""
        budgets: List[Budget] = []
        for item in self.storage.stream_items(BUDGETS_FILE):
            budgets.append(Budget.from_dict(item))
        return budgets
