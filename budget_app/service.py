import csv
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Generator, List, Optional, Tuple

from budget_app.exceptions import ConflictError, NotFoundError, ValidationError
from budget_app.models import Budget, Transaction
from budget_app.repository import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)
from budget_app.utils import validate_date, validate_month


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
    def add_transaction(
        self,
        date_str: str,
        tx_type: str,
        category: str,
        amount_raw: Any,
        memo: str = "",
        tags: Optional[List[str]] = None,
    ) -> Transaction:
        # 1) 날짜 유효성 검사
        try:
            valid_date = validate_date(date_str)
        except ValueError as e:
            raise ValidationError(str(e), hint="날짜는 YYYY-MM-DD 형식으로 입력해주세요 (예: 2024-01-15).")

        # 2) 타입 검사
        cleaned_type = str(tx_type).strip().lower()
        if cleaned_type not in ("income", "expense"):
            raise ValidationError(
                f"허용되지 않은 타입입니다: '{tx_type}'",
                hint="타입은 'income' 또는 'expense' 중 하나여야 합니다.",
            )

        # 3) 금액 검사
        try:
            amount = int(amount_raw)
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(
                f"금액이 올바르지 않습니다: '{amount_raw}'",
                hint="금액은 0보다 큰 양의 정수여야 합니다 (예: 15000).",
            )

        # 4) 카테고리 검사
        cleaned_cat = category.strip()
        if not self.cat_repo.exists(cleaned_cat):
            all_cats = ", ".join(self.cat_repo.list_all())
            raise ValidationError(
                f"등록되지 않은 카테고리입니다: '{cleaned_cat}'",
                hint=f"현재 등록된 카테고리 목록: [{all_cats}]. 'category add' 명령으로 먼저 등록해주세요.",
            )

        # 5) ID 생성 및 저장
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
        """최신순 거래 목록 스트리밍"""
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
        """조건에 맞는 거래 최신순 스트리밍 검색"""
        if from_date:
            try:
                validate_date(from_date)
            except ValueError as e:
                raise ValidationError(f"검색 시작일 오류: {e}", hint="--from YYYY-MM-DD")
        if to_date:
            try:
                validate_date(to_date)
            except ValueError as e:
                raise ValidationError(f"검색 종료일 오류: {e}", hint="--to YYYY-MM-DD")

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
    # 4. 월별 요약 (Summary)
    # ----------------------------------------------------
    def get_monthly_summary(self, month: str, top_n: int = 3) -> Dict[str, Any]:
        """
        월별 통계 계산:
        - 총 수입, 총 지출, 잔액
        - 카테고리별 지출 합계 TOP N
        - 예산 설정 확인 및 예산 대비 사용률, 초과 경고
        """
        try:
            valid_month = validate_month(month)
        except ValueError as e:
            raise ValidationError(str(e), hint="월은 YYYY-MM 형식이어야 합니다 (예: 2024-01).")

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

        # 카테고리별 지출 내림차순 정렬
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
            budget_info = {
                "amount": budget.amount,
                "usage_rate": usage_rate,
                "is_exceeded": is_exceeded,
                "excess_amount": excess_amount,
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
            raise ValidationError(str(e), hint="월은 YYYY-MM 형식이어야 합니다 (예: 2024-01).")

        try:
            amount = int(amount_raw)
            if amount < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValidationError(
                f"예산 금액이 올바르지 않습니다: '{amount_raw}'",
                hint="예산 금액은 0 이상의 정수여야 합니다.",
            )

        self.budget_repo.set_budget(valid_month, amount)
        return Budget(month=valid_month, amount=amount)

    def get_budget(self, month: str) -> Optional[Budget]:
        valid_month = validate_month(month)
        return self.budget_repo.get_budget(valid_month)

    # ----------------------------------------------------
    # 6. 카테고리 관리 (Category)
    # ----------------------------------------------------
    def list_categories(self) -> List[str]:
        return self.cat_repo.list_all()

    def add_category(self, name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("카테고리 이름을 입력해야 합니다.")
        if self.cat_repo.exists(cleaned):
            raise ConflictError(
                f"이미 존재하는 카테고리입니다: '{cleaned}'",
                hint="다른 이름을 입력하거나 'category list'로 목록을 확인하세요.",
            )
        self.cat_repo.add(cleaned)
        return cleaned

    def remove_category(self, name: str, replacement: Optional[str] = None) -> Tuple[bool, int]:
        """
        카테고리 삭제:
        - 해당 카테고리가 사용 중일 경우, replacement가 주어지면 대체 후 삭제,
          없으면 ConflictError를 발생시켜 삭제를 막음.
        """
        cleaned = name.strip()
        if not self.cat_repo.exists(cleaned):
            raise NotFoundError(
                f"카테고리를 찾을 수 없습니다: '{cleaned}'",
                hint="'category list'로 등록된 카테고리를 확인하세요.",
            )

        in_use = self.tx_repo.is_category_in_use(cleaned)
        reassigned_count = 0
        if in_use:
            if not replacement:
                raise ConflictError(
                    f"'{cleaned}' 카테고리를 사용하는 거래 내역이 존재하여 삭제할 수 없습니다.",
                    hint="대체할 카테고리를 지정하세요 (예: --replace <대체카테고리>).",
                )
            rep_clean = replacement.strip()
            if not self.cat_repo.exists(rep_clean):
                raise NotFoundError(
                    f"대체할 카테고리가 존재하지 않습니다: '{rep_clean}'",
                    hint="먼저 대체할 카테고리를 등록하거나 존재하는 카테고리를 입력하세요.",
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
                f"존재하지 않는 거래 ID입니다: '{tx_id}'",
                hint="'list' 명령으로 거래 ID를 확인해주세요.",
            )

        new_date = existing.date
        if date is not None:
            new_date = validate_date(date)

        new_type = existing.type
        if tx_type is not None:
            cleaned_type = tx_type.strip().lower()
            if cleaned_type not in ("income", "expense"):
                raise ValidationError("타입은 'income' 또는 'expense'여야 합니다.")
            new_type = cleaned_type

        new_cat = existing.category
        if category is not None:
            cleaned_cat = category.strip()
            if not self.cat_repo.exists(cleaned_cat):
                raise ValidationError(f"등록되지 않은 카테고리입니다: '{cleaned_cat}'")
            new_cat = cleaned_cat

        new_amount = existing.amount
        if amount is not None:
            try:
                parsed_amount = int(amount)
                if parsed_amount <= 0:
                    raise ValueError()
                new_amount = parsed_amount
            except (ValueError, TypeError):
                raise ValidationError("금액은 0보다 큰 양의 정수여야 합니다.")

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
                f"존재하지 않는 거래 ID입니다: '{tx_id}'",
                hint="'list' 명령으로 거래 ID를 확인해주세요.",
            )
        return self.tx_repo.delete(tx_id)

    # ----------------------------------------------------
    # 9. 가져오기 / 내보내기 (Import / Export CSV)
    # ----------------------------------------------------
    def import_csv(self, file_path: str) -> Tuple[int, int]:
        """
        CSV 파일에서 거래를 일괄 등록
        CSV 헤더: date, type, category, amount, memo, tags
        반환: (성공 건수, 스킵 건수)
        """
        path = Path(file_path)
        if not path.exists():
            raise NotFoundError(
                f"CSV 파일을 찾을 수 없습니다: '{file_path}'",
                hint="파일 경로를 다시 확인해주세요.",
            )

        imported = 0
        skipped = 0
        txs_to_add: List[Transaction] = []

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValidationError("CSV 파일이 비어있거나 헤더가 올바르지 않습니다.")

            # 필드 정규화
            fieldnames = [fn.strip().lower() for fn in reader.fieldnames]
            required_cols = {"date", "type", "category", "amount"}
            if not required_cols.issubset(set(fieldnames)):
                raise ValidationError(
                    f"CSV 스키마 오류. 필수 컬럼이 누락되었습니다: {required_cols - set(fieldnames)}",
                    hint="CSV 헤더는 최소 date, type, category, amount를 포함해야 합니다.",
                )

            for row in reader:
                # 공백 제거
                row_clean = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items()}
                try:
                    date_val = validate_date(row_clean.get("date", ""))
                    type_val = row_clean.get("type", "").lower()
                    if type_val not in ("income", "expense"):
                        skipped += 1
                        continue

                    category_val = row_clean.get("category", "")
                    if not category_val:
                        skipped += 1
                        continue
                    if not self.cat_repo.exists(category_val):
                        # 가져올 때 새로운 카테고리면 자동 등록
                        self.cat_repo.add(category_val)

                    amount_val = int(row_clean.get("amount", 0))
                    if amount_val <= 0:
                        skipped += 1
                        continue

                    memo_val = row_clean.get("memo", "")
                    tags_raw = row_clean.get("tags", "")
                    tags_val = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

                    tx_id = self.tx_repo.generate_next_id()
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
                except Exception:
                    skipped += 1

        if txs_to_add:
            self.tx_repo.add_batch(txs_to_add)

        return imported, skipped

    def export_csv(
        self,
        out_path: str,
        month: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> int:
        """
        거래 내역을 CSV로 내보내기
        조건: --month YYYY-MM 또는 --from YYYY-MM-DD --to YYYY-MM-DD 중 하나 이상 필수
        """
        if not month and not (from_date or to_date):
            raise ValidationError(
                "내보내기 조건이 필요합니다.",
                hint="--month YYYY-MM 또는 --from YYYY-MM-DD --to YYYY-MM-DD 조건을 지정해주세요.",
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
    # 10. 백업 기능 (Backup - 보너스 과제 1)
    # ----------------------------------------------------
    def backup_data(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.data_dir.parent / f"backup_{timestamp}"
        shutil.copytree(self.data_dir, backup_dir)
        return str(backup_dir)
