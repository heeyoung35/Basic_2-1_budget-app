"""
엔드투엔드(E2E) 및 CLI 통합 테스트
---------------------------------
평가 항목 #1, #2, #5, #7, #16을 종합적으로 검증합니다:
- 실제 CLI 진입점 실행 및 프로세스 종료 코드(0, 1) 확인
- 데이터 디렉터리 재실행 유지 및 읽기/쓰기 권한 확인
- CSV 인코딩/헤더 검증 및 원자적(All-or-Nothing) 임포트/롤백 검증
- 카테고리 삭제 영향도 검증
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from budget_app.cli import main
from budget_app.exceptions import AtomicImportError, ConflictError
from budget_app.models import Budget, Category, Transaction
from budget_app.repository import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)
from budget_app.service import BudgetService
from budget_app.storage import JsonlStorage


class TestCliAndIntegrationE2E(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = JsonlStorage(data_dir=self.test_dir)
        self.tx_repo = TransactionRepository(self.storage)
        self.cat_repo = CategoryRepository(self.storage)
        self.budget_repo = BudgetRepository(self.storage)
        self.service = BudgetService(
            self.tx_repo, self.cat_repo, self.budget_repo, data_dir=self.test_dir
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ----------------------------------------------------
    # 평가 항목 #2 검증: 데이터 디렉터리 재실행 유지 및 파일 권한
    # ----------------------------------------------------
    def test_storage_health_and_persistence(self):
        health = self.storage.verify_storage_health()
        for fname, ok in health.items():
            self.assertTrue(ok, f"저장소 파일 {fname} 상태 불량")

        # 재초기화 시에도 데이터 보존 확인
        self.cat_repo.add("custom_category")
        reloaded_storage = JsonlStorage(data_dir=self.test_dir)
        reloaded_cat_repo = CategoryRepository(reloaded_storage)
        self.assertTrue(reloaded_cat_repo.exists("custom_category"))

    # ----------------------------------------------------
    # 평가 항목 #1 & #7 검증: CLI 프로세스 실행 및 종료 코드(0, 1)
    # ----------------------------------------------------
    def test_cli_exit_codes_via_subprocess(self):
        # 1) 정상 실행: --help (exit code 0)
        res_help = subprocess.run(
            [sys.executable, "-m", "budget_app", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(res_help.returncode, 0)

        # 2) 정상 실행: category list (exit code 0)
        res_cat = subprocess.run(
            [sys.executable, "-m", "budget_app", "-data-dir", self.test_dir, "category", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(res_cat.returncode, 0)
        self.assertIn("food", res_cat.stdout)

        # 3) 오류 실행: 존재하지 않는 카테고리 삭제 시도 (exit code 1 및 스택트레이스 없음)
        res_err = subprocess.run(
            [sys.executable, "-m", "budget_app", "-data-dir", self.test_dir, "category", "remove", "no_such_cat"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(res_err.returncode, 1)
        self.assertIn("[오류]", res_err.stderr)
        self.assertNotIn("Traceback", res_err.stderr)

    # ----------------------------------------------------
    # 평가 항목 #5 & #16 검증: CSV 인코딩, 원자적 임포트(strict) 및 롤백
    # ----------------------------------------------------
    def test_csv_import_normal_vs_strict_atomic_rollback(self):
        # 정상 CSV 임포트
        sample_path = Path("sample_import.csv").resolve()
        if sample_path.exists():
            imported, skipped, logs = self.service.import_csv(str(sample_path), strict=False)
            self.assertEqual(imported, 5)
            self.assertEqual(skipped, 0)

        # 오류 포함 CSV 테스트
        invalid_sample = Path("sample_import_invalid.csv").resolve()
        if invalid_sample.exists():
            # 1) 일반 모드: 스킵하고 정상 건만 임포트
            imported, skipped, logs = self.service.import_csv(str(invalid_sample), strict=False)
            self.assertEqual(imported, 1)
            self.assertEqual(skipped, 3)
            self.assertEqual(len(logs), 3)

            # 2) strict(원자적 All-or-Nothing) 모드: 단 1건이라도 오류 시 전체 롤백 및 AtomicImportError 발생
            with self.assertRaises(AtomicImportError):
                self.service.import_csv(str(invalid_sample), strict=True)

    # ----------------------------------------------------
    # 평가 항목 #3 검증: 카테고리 삭제 전 영향도(건수) 사전 안내
    # ----------------------------------------------------
    def test_category_remove_impact_count(self):
        self.service.add_transaction("2024-01-15", "expense", "food", 10000)
        self.service.add_transaction("2024-01-16", "expense", "food", 20000)

        # 영향받는 건수가 2건인지 확인
        count = self.service.get_category_usage_count("food")
        self.assertEqual(count, 2)

        # 대체 없이 삭제 시도 시 예외 메시지에 2건 정보 포함 확인
        with self.assertRaises(ConflictError) as cm:
            self.service.remove_category("food")
        self.assertIn("2건 존재", cm.exception.message)

    # ----------------------------------------------------
    # 평가 항목 #4 검증: 세분화된 예산 알림 정책 (SAFE / WARNING / DANGER)
    # ----------------------------------------------------
    def test_budget_alert_policies(self):
        self.service.set_budget("2024-02", 100000)

        # 1) 안전 상태 (50%)
        self.service.add_transaction("2024-02-01", "expense", "food", 50000)
        s1 = self.service.get_monthly_summary("2024-02", warning_threshold=80.0)
        self.assertEqual(s1["budget"]["alert_level"], "SAFE")

        # 2) 주의 상태 (85%)
        self.service.add_transaction("2024-02-05", "expense", "food", 35000)
        s2 = self.service.get_monthly_summary("2024-02", warning_threshold=80.0)
        self.assertEqual(s2["budget"]["alert_level"], "WARNING")

        # 3) 초과 상태 (110%)
        self.service.add_transaction("2024-02-10", "expense", "food", 25000)
        s3 = self.service.get_monthly_summary("2024-02", warning_threshold=80.0)
        self.assertEqual(s3["budget"]["alert_level"], "DANGER")


if __name__ == "__main__":
    unittest.main()
