import os
import shutil
import tempfile
import unittest

from budget_app.exceptions import ConflictError, NotFoundError, ValidationError
from budget_app.models import Transaction
from budget_app.repository import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)
from budget_app.service import BudgetService
from budget_app.storage import JsonlStorage
from budget_app.utils import validate_date, validate_month


class TestBudgetApp(unittest.TestCase):
    def setUp(self):
        # 임시 디렉터리에서 독립 테스트 환경 구성
        self.test_dir = tempfile.mkdtemp()
        self.storage = JsonlStorage(data_dir=self.test_dir)
        self.tx_repo = TransactionRepository(self.storage)
        self.cat_repo = CategoryRepository(self.storage)
        self.budget_repo = BudgetRepository(self.storage)
        self.service = BudgetService(
            self.tx_repo, self.cat_repo, self.budget_repo, data_dir=self.test_dir
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_validation(self):
        # 유효한 날짜 및 잘못된 날짜
        self.assertEqual(validate_date("2024-01-15"), "2024-01-15")
        with self.assertRaises(ValueError):
            validate_date("2024-13-40")

        # 유효한 월 및 잘못된 월
        self.assertEqual(validate_month("2024-01"), "2024-01")
        with self.assertRaises(ValueError):
            validate_month("2024-13")

    def test_add_and_list_transaction(self):
        # 거래 추가
        tx = self.service.add_transaction(
            date_str="2024-01-15",
            tx_type="expense",
            category="food",
            amount_raw="15000",
            memo="점심",
            tags=["meal"],
        )
        self.assertEqual(tx.id, "TX-000001")
        self.assertEqual(tx.amount, 15000)

        # 등록되지 않은 카테고리 추가 시 예외 발생 검증
        with self.assertRaises(ValidationError):
            self.service.add_transaction(
                date_str="2024-01-15",
                tx_type="expense",
                category="non_existent",
                amount_raw=1000,
            )

        # 음수 또는 0 금액 검증
        with self.assertRaises(ValidationError):
            self.service.add_transaction(
                date_str="2024-01-15",
                tx_type="expense",
                category="food",
                amount_raw=-500,
            )

        # 목록 조회 제너레이터 검증
        txs = list(self.service.list_transactions(limit=10))
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0].id, "TX-000001")

    def test_monthly_summary_and_budget(self):
        # 거래 내역 등록
        self.service.add_transaction("2024-01-10", "income", "salary", 3000000)
        self.service.add_transaction("2024-01-12", "expense", "rent", 150000)
        self.service.add_transaction("2024-01-15", "expense", "food", 45000)
        self.service.add_transaction("2024-01-18", "expense", "transport", 20000)

        # 예산 설정
        self.service.set_budget("2024-01", 500000)

        # 통계 요약 검증
        summary = self.service.get_monthly_summary("2024-01", top_n=3)
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["total_income"], 3000000)
        self.assertEqual(summary["total_expense"], 215000)
        self.assertEqual(summary["balance"], 2785000)
        self.assertAlmostEqual(summary["budget"]["usage_rate"], 43.0, places=1)
        self.assertFalse(summary["budget"]["is_exceeded"])

        # 지출 TOP 카테고리 순위 검증
        top_cats = summary["top_categories"]
        self.assertEqual(top_cats[0], ("rent", 150000))
        self.assertEqual(top_cats[1], ("food", 45000))
        self.assertEqual(top_cats[2], ("transport", 20000))

    def test_category_remove_protection(self):
        # 사용 중인 카테고리 삭제 방지
        self.service.add_transaction("2024-01-10", "expense", "food", 10000)

        with self.assertRaises(ConflictError):
            self.service.remove_category("food")

        # 대체 카테고리를 지정하면 정상 삭제 및 데이터 이전
        success, reassigned = self.service.remove_category("food", replacement="utilities")
        self.assertTrue(success)
        self.assertEqual(reassigned, 1)

        # 거래 내역의 카테고리가 utilities로 변경되었는지 확인
        tx = list(self.service.list_transactions())[0]
        self.assertEqual(tx.category, "utilities")

    def test_update_and_delete(self):
        tx = self.service.add_transaction("2024-01-10", "expense", "food", 10000)
        
        # 수정
        updated = self.service.update_transaction(tx.id, amount=12000, memo="수정된 메모")
        self.assertEqual(updated.amount, 12000)
        self.assertEqual(updated.memo, "수정된 메모")

        # 삭제
        deleted = self.service.delete_transaction(tx.id)
        self.assertTrue(deleted)
        self.assertEqual(len(list(self.service.list_transactions())), 0)

        # 없는 ID 삭제 시 예외
        with self.assertRaises(NotFoundError):
            self.service.delete_transaction("TX-999999")


if __name__ == "__main__":
    unittest.main()
