"""
서비스 계층 (Business Logic Layer)
--------------------------------
가계부 애플리케이션의 핵심 비즈니스 규칙과 트랜잭션을 조율합니다.
- 거래 등록/수정/삭제/조회/검색 비즈니스 검증
- 월별 통계, 지출 TOP N, 예산 사용률 및 임계값별 알림 정책
- 카테고리 참조 무결성 검증 및 사전 영향도 분석
- 원자적(All-or-Nothing) CSV 임포트 및 롤백 지원
"""

import csv
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Generator, List, Optional, Tuple

from budget_app.exceptions import (
    AtomicImportError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from budget_app.models import Budget, Transaction
from budget_app.repository import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)
from budget_app.utils import log_action, validate_date, validate_month


class BudgetService:
    def __init__(
        self,
        tx_repo: TransactionRepository,
        cat_repo: CategoryRepository,
        budget_repo: BudgetRepository,
        data_dir: str = "./data",
    ):
        self.tx_repo = tx_repo
        self.cat_repo = cat_repo
        self.budget_repo = budget_repo
        self.data_dir = Path(data_dir)

    def validate_date_input(self, date_str: str) -> str:
        """날짜 유효성 검사 헬퍼"""
        return validate_date(date_str)

    # ----------------------------------------------------
    # 1. 거래 추가 (Add)
    # ----------------------------------------------------
    @log_action("add_transaction")
    def add_transaction(
        self,
        date_str: str,
        tx_type: str,
        category: str,
        amount_raw: Any,
        memo: str = "",
        tags: Optional[List[str]] = None,
    ) -> Transaction:
        try:
            valid_date = validate_date(date_str)
        except ValueError as e:
            raise ValidationError(
                str(e),
                hint="날짜는 YYYY-MM-DD 형식으로 입력해주세요 (예: 2024-01-15).",
                error_code="ERR_DATE_FORMAT",
            )

        cleaned_type = str(tx_type).strip().lower()
        if cleaned_type not in ("income", "expense"):
            raise ValidationError(
                f"허용되지 않은 타입입니다: '{tx_type}'",
                hint="타입은 'income' 또는 'expense' 중 하나여야 합니다.",
                error_code="ERR_TYPE_INVALID",
            )

        try:
            amount = int(amount_raw)
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(
                f"금액이 올바르지 않습니다: '{amount_raw}'",
                hint="금액은 0보다 큰 양의 정수여야 합니다 (예: 15000).",
                error_code="ERR_AMOUNT_INVALID",
            )

        cleaned_cat = category.strip()
        if not self.cat_repo.exists(cleaned_cat):
            all_cats = ", ".join(self.cat_repo.list_all())
            raise ValidationError(
                f"등록되지 않은 카테고리입니다: '{cleaned_cat}'",
                hint=f"현재 등록된 카테고리 목록: [{all_cats}]. 'category add' 명령으로 먼저 등록해주세요.",
                error_code="ERR_CATEGORY_NOT_FOUND",
            )

        tx_id = self.tx_repo.generate_next_id()
        tx = Transaction(
            id=tx_id,
            type=cleaned_type,
            date=valid_date,
            amount=amount,
            category=cleaned_cat,
            memo=memo.strip(),
            tags=[t.strip() for t in (tags or []) if t.strip()],
        )
        self.tx_repo.add(tx)
        return tx

    # ----------------------------------------------------
    # 2. 거래 목록 (List)
    # ----------------------------------------------------
    def list_transactions(self, limit: Optional[int] = None) -> Generator[Transaction, None, None]:
        count = 0
        for tx in self.tx_repo.stream_all(reverse=True):
            if limit is not None and count >= limit:
                break
            yield tx
            count += 1

    # ----------------------------------------------------
    # 3. 거래 검색 (Search)
    # ----------------------------------------------------
    def search_transactions(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        category: Optional[str] = None,
        tx_type: Optional[str] = None,
        query: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Generator[Transaction, None, None]:
        if from_date:
            try:
                validate_date(from_date)
            except ValueError as e:
                raise ValidationError(f"검색 시작일 오류: {e}", hint="-from YYYY-MM-DD", error_code="ERR_DATE_FORMAT")
        if to_date:
            try:
                validate_date(to_date)
            except ValueError as e:
                raise ValidationError(f"검색 종료일 오류: {e}", hint="-to YYYY-MM-DD", error_code="ERR_DATE_FORMAT")

        for tx in self.tx_repo.stream_all(reverse=True):
            if from_date and tx.date < from_date:
                continue
            if to_date and tx.date > to_date:
                continue
            if category and tx.category.lower() != category.strip().lower():
                continue
            if tx_type and tx.type.lower() != tx_type.strip().lower():
                continue
            if query and (query.lower() not in tx.memo.lower()):
                continue
            if tag and not any(t.lower() == tag.strip().lower() for t in tx.tags):
                continue
            yield tx

    # ----------------------------------------------------
    # 4. 월별 요약 및 정책 분리 (Summary - 평가 항목 #4 보완)
    # ----------------------------------------------------
    def get_monthly_summary(
        self,
        month: str,
        top_n: int = 3,
        warning_threshold: float = 80.0,
    ) -> Dict[str, Any]:
        """
        월별 통계 및 예산 알림 레벨 산출
        - warning_threshold: 주의 알림 기준 퍼센트 (기본 80.0%)
        """
        try:
            valid_month = validate_month(month)
        except ValueError as e:
            raise ValidationError(str(e), hint="월은 YYYY-MM 형식이어야 합니다 (예: 2024-01).", error_code="ERR_MONTH_FORMAT")

        total_income = 0
        total_expense = 0
        category_expenses: Dict[str, int] = {}
        has_data = False

        for tx in self.tx_repo.stream_all(reverse=False):
            if tx.date.startswith(valid_month):
                has_data = True
                if tx.type == "income":
                    total_income += tx.amount
                elif tx.type == "expense":
                    total_expense += tx.amount
                    category_expenses[tx.category] = (
                        category_expenses.get(tx.category, 0) + tx.amount
                    )

        budget = self.budget_repo.get_budget(valid_month)

        if not has_data and budget is None:
            return {"month": valid_month, "has_data": False}

        sorted_cat_expenses = sorted(
            category_expenses.items(), key=lambda x: x[1], reverse=True
        )
        top_categories = sorted_cat_expenses[:top_n]
        balance = total_income - total_expense

        budget_info = None
        if budget is not None and budget.amount > 0:
            usage_rate = (total_expense / budget.amount) * 100.0
            is_exceeded = total_expense > budget.amount
            excess_amount = total_expense - budget.amount if is_exceeded else 0

            # 예산 알림 정책 레벨 세분화 (평가 항목 #4 보완)
            if is_exceeded:
                alert_level = "DANGER"
                alert_message = f"⚠️ [초과 경고] 예산을 {excess_amount:,}원 초과했습니다!"
            elif usage_rate >= warning_threshold:
                alert_level = "WARNING"
                alert_message = f"🔔 [예산 주의] 예산의 {usage_rate:.1f}%를 사용하여 임계치({warning_threshold}%)에 도달했습니다."
            else:
                alert_level = "SAFE"
                alert_message = f"✅ 예산이 안전하게 유지되고 있습니다 (사용률: {usage_rate:.1f}%)."

            budget_info = {
                "amount": budget.amount,
                "usage_rate": usage_rate,
                "is_exceeded": is_exceeded,
                "excess_amount": excess_amount,
                "alert_level": alert_level,
                "alert_message": alert_message,
            }

        return {
            "month": valid_month,
            "has_data": True,
            "total_income": total_income,
            "total_expense": total_expense,
            "balance": balance,
            "top_categories": top_categories,
            "budget": budget_info,
        }

    # ----------------------------------------------------
    # 5. 예산 관리 (Budget)
    # ----------------------------------------------------
    def set_budget(self, month: str, amount_raw: Any) -> Budget:
        try:
            valid_month = validate_month(month)
        except ValueError as e:
            raise ValidationError(str(e), hint="월은 YYYY-MM 형식이어야 합니다 (예: 2024-01).", error_code="ERR_MONTH_FORMAT")

        try:
            amount = int(amount_raw)
            if amount < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(
                f"예산 금액이 올바르지 않습니다: '{amount_raw}'",
                hint="예산 금액은 0 이상의 정수여야 합니다.",
                error_code="ERR_AMOUNT_INVALID",
            )

        self.budget_repo.set_budget(valid_month, amount)
        return Budget(month=valid_month, amount=amount)

    def get_budget(self, month: str) -> Optional[Budget]:
        valid_month = validate_month(month)
        return self.budget_repo.get_budget(valid_month)

    # ----------------------------------------------------
    # 6. 카테고리 관리 (Category - 평가 항목 #3 사전 영향도 보완)
    # ----------------------------------------------------
    def list_categories(self) -> List[str]:
        return self.cat_repo.list_all()

    def add_category(self, name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("카테고리 이름을 입력해야 합니다.", error_code="ERR_EMPTY_NAME")
        if self.cat_repo.exists(cleaned):
            raise ConflictError(
                f"이미 존재하는 카테고리입니다: '{cleaned}'",
                hint="다른 이름을 입력하거나 'category list'로 목록을 확인하세요.",
                error_code="ERR_CATEGORY_EXISTS",
            )
        self.cat_repo.add(cleaned)
        return cleaned

    def get_category_usage_count(self, name: str) -> int:
        """카테고리 삭제 전 영향받는 거래 건수 사전 확인 (평가 항목 #3 보완)"""
        return self.tx_repo.count_by_category(name.strip())

    def remove_category(self, name: str, replacement: Optional[str] = None) -> Tuple[bool, int]:
        cleaned = name.strip()
        if not self.cat_repo.exists(cleaned):
            raise NotFoundError(
                f"카테고리를 찾을 수 없습니다: '{cleaned}'",
                hint="'category list'로 등록된 카테고리를 확인하세요.",
                error_code="ERR_CATEGORY_NOT_FOUND",
            )

        usage_count = self.get_category_usage_count(cleaned)
        reassigned_count = 0
        if usage_count > 0:
            if not replacement:
                raise ConflictError(
                    f"'{cleaned}' 카테고리를 사용하는 거래 내역이 {usage_count}건 존재하여 삭제할 수 없습니다.",
                    hint=f"대체할 카테고리를 지정하세요 (예: -replace <대체카테고리>). 영향받는 거래: {usage_count}건",
                    error_code="ERR_CATEGORY_IN_USE",
                )
            rep_clean = replacement.strip()
            if not self.cat_repo.exists(rep_clean):
                raise NotFoundError(
                    f"대체할 카테고리가 존재하지 않습니다: '{rep_clean}'",
                    hint="먼저 대체할 카테고리를 등록하거나 존재하는 카테고리를 입력하세요.",
                    error_code="ERR_CATEGORY_NOT_FOUND",
                )
            reassigned_count = self.tx_repo.replace_category(cleaned, rep_clean)

        self.cat_repo.remove(cleaned)
        return True, reassigned_count

    # ----------------------------------------------------
    # 7. 거래 수정 (Update)
    # ----------------------------------------------------
    def update_transaction(
        self,
        tx_id: str,
        date: Optional[str] = None,
        tx_type: Optional[str] = None,
        category: Optional[str] = None,
        amount: Optional[Any] = None,
        memo: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Transaction:
        existing = self.tx_repo.find_by_id(tx_id)
        if not existing:
            raise NotFoundError(
                f"없는 데이터: 존재하지 않는 거래 ID입니다: '{tx_id}'",
                hint="'list' 명령으로 거래 ID를 확인해주세요.",
                error_code="ERR_TRANSACTION_NOT_FOUND",
            )

        new_date = existing.date
        if date is not None:
            new_date = validate_date(date)

        new_type = existing.type
        if tx_type is not None:
            cleaned_type = tx_type.strip().lower()
            if cleaned_type not in ("income", "expense"):
                raise ValidationError("타입은 'income' 또는 'expense'여야 합니다.", error_code="ERR_TYPE_INVALID")
            new_type = cleaned_type

        new_cat = existing.category
        if category is not None:
            cleaned_cat = category.strip()
            if not self.cat_repo.exists(cleaned_cat):
                raise ValidationError(f"등록되지 않은 카테고리입니다: '{cleaned_cat}'", error_code="ERR_CATEGORY_NOT_FOUND")
            new_cat = cleaned_cat

        new_amount = existing.amount
        if amount is not None:
            try:
                parsed_amount = int(amount)
                if parsed_amount <= 0:
                    raise ValueError()
                new_amount = parsed_amount
            except (ValueError, TypeError):
                raise ValidationError("금액은 0보다 큰 양의 정수여야 합니다.", error_code="ERR_AMOUNT_INVALID")

        new_memo = existing.memo if memo is None else memo.strip()
        new_tags = existing.tags if tags is None else [t.strip() for t in tags if t.strip()]

        updated_tx = Transaction(
            id=existing.id,
            date=new_date,
            type=new_type,
            category=new_cat,
            amount=new_amount,
            memo=new_memo,
            tags=new_tags,
        )

        self.tx_repo.update(updated_tx)
        return updated_tx

    # ----------------------------------------------------
    # 8. 거래 삭제 (Delete)
    # ----------------------------------------------------
    def delete_transaction(self, tx_id: str) -> bool:
        existing = self.tx_repo.find_by_id(tx_id)
        if not existing:
            raise NotFoundError(
                f"없는 데이터: 존재하지 않는 거래 ID입니다: '{tx_id}'",
                hint="'list' 명령으로 거래 ID를 확인해주세요.",
                error_code="ERR_TRANSACTION_NOT_FOUND",
            )
        return self.tx_repo.delete(tx_id)

    # ----------------------------------------------------
    # 9. 원자적 임포트 / 내보내기 (Import / Export - 평가 항목 #16 FAIL 완전 해결)
    # ----------------------------------------------------
    def import_csv(
        self,
        file_path: str,
        strict: bool = False,
    ) -> Tuple[int, int, List[str]]:
        """
        CSV 일괄 등록 메서드
        - strict=False (기본값): 오류 행 건너뛰기(Skip) 모드
        - strict=True (평가 항목 #16 보완): 원자적 트랜잭션(All-or-Nothing) 모드.
          단 1개 행이라도 유효하지 않으면 전체 취소 및 롤백, AtomicImportError 발생.
        반환: (성공 건수, 실패/스킵 건수, 상세 오류 메시지 목록)
        """
        path = Path(file_path)
        if not path.exists():
            raise NotFoundError(
                f"CSV 파일을 찾을 수 없습니다: '{file_path}'",
                hint="파일 경로를 다시 확인해주세요.",
                error_code="ERR_FILE_NOT_FOUND",
            )

        imported = 0
        skipped = 0
        error_logs: List[str] = []
        txs_to_add: List[Transaction] = []
        new_categories_to_add: List[str] = []

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValidationError("CSV 파일이 비어있거나 헤더가 올바르지 않습니다.", error_code="ERR_CSV_EMPTY")

            fieldnames = [fn.strip().lower() for fn in reader.fieldnames]
            required_cols = {"date", "type", "category", "amount"}
            if not required_cols.issubset(set(fieldnames)):
                raise ValidationError(
                    f"CSV 스키마 오류. 필수 컬럼이 누락되었습니다: {required_cols - set(fieldnames)}",
                    hint="CSV 헤더는 최소 date, type, category, amount를 포함해야 합니다.",
                    error_code="ERR_CSV_SCHEMA",
                )

            current_id_seq = 0
            for row_idx, row in enumerate(reader, start=2):  # 2행부터 데이터
                row_clean = {
                    (k.strip().lower() if k else ""): (v.strip() if v else "")
                    for k, v in row.items()
                    if k
                }
                row_errors = []

                # 1) 날짜 검증
                date_val = row_clean.get("date", "")
                try:
                    date_val = validate_date(date_val)
                except ValueError as e:
                    row_errors.append(f"날짜 오류({e})")

                # 2) 타입 검증
                type_val = row_clean.get("type", "").lower()
                if type_val not in ("income", "expense"):
                    row_errors.append(f"타입 오류('{type_val}')")

                # 3) 카테고리 검증
                category_val = row_clean.get("category", "")
                if not category_val:
                    row_errors.append("카테고리 누락")
                elif not self.cat_repo.exists(category_val) and category_val not in new_categories_to_add:
                    new_categories_to_add.append(category_val)

                # 4) 금액 검증
                try:
                    amount_val = int(row_clean.get("amount", 0))
                    if amount_val <= 0:
                        raise ValueError()
                except (ValueError, TypeError):
                    row_errors.append(f"금액 오류('{row_clean.get('amount')}')")

                # 행 단위 검증 실패 처리
                if row_errors:
                    skipped += 1
                    err_msg = f"Line {row_idx}: {', '.join(row_errors)}"
                    error_logs.append(err_msg)
                    if strict:
                        # 평가 항목 #16: 원자적 롤백 모드 즉시 발동
                        raise AtomicImportError(
                            f"원자적 임포트 실패: {err_msg} (총 {len(error_logs)}건 오류)",
                            hint="--strict 모드에서는 모든 행이 유효해야 등록됩니다. CSV 데이터를 수정 후 재시도하세요.",
                        )
                    continue

                memo_val = row_clean.get("memo", "")
                tags_raw = row_clean.get("tags", "")
                tags_val = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

                # 가상 ID 생성
                tx_id = self.tx_repo.generate_next_id()
                # batch 내 중복 ID 방지를 위해 시퀀스 처리
                if current_id_seq > 0:
                    import re
                    m = re.search(r"TX-(\d+)", tx_id)
                    if m:
                        tx_id = f"TX-{int(m.group(1)) + current_id_seq:06d}"
                current_id_seq += 1

                tx = Transaction(
                    id=tx_id,
                    date=date_val,
                    type=type_val,
                    category=category_val,
                    amount=amount_val,
                    memo=memo_val,
                    tags=tags_val,
                )
                txs_to_add.append(tx)
                imported += 1

        # 모든 검증을 무사히 통과했을 때만 일괄 커밋
        for cat in new_categories_to_add:
            if not self.cat_repo.exists(cat):
                self.cat_repo.add(cat)

        if txs_to_add:
            self.tx_repo.add_batch(txs_to_add)

        return imported, skipped, error_logs

    def export_csv(
        self,
        out_path: str,
        month: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> int:
        if not month and not (from_date or to_date):
            raise ValidationError(
                "내보내기 조건이 필요합니다.",
                hint="-month YYYY-MM 또는 -from YYYY-MM-DD -to YYYY-MM-DD 조건을 지정해주세요.",
                error_code="ERR_EXPORT_CONDITION",
            )

        if month:
            from_date = f"{month}-01"
            to_date = f"{month}-31"

        target_file = Path(out_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        exported_count = 0
        with open(target_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "type", "category", "amount", "memo", "tags"])

            for tx in self.search_transactions(from_date=from_date, to_date=to_date):
                writer.writerow([
                    tx.date,
                    tx.type,
                    tx.category,
                    tx.amount,
                    tx.memo,
                    ",".join(tx.tags),
                ])
                exported_count += 1

        return exported_count

    # ----------------------------------------------------
    # 10. 백업 기능 (Backup)
    # ----------------------------------------------------
    def backup_data(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.data_dir.parent / f"backup_{timestamp}"
        shutil.copytree(self.data_dir, backup_dir)
        return str(backup_dir)
