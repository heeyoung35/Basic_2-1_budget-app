import argparse
import sys
from typing import List, Optional

# Windows 콘솔 인코딩 대응
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from budget_app.exceptions import BudgetAppError, ValidationError
from budget_app.repository import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)
from budget_app.service import BudgetService
from budget_app.storage import DEFAULT_DATA_DIR, JsonlStorage
from budget_app.utils import handle_errors, measure_execution_time


def create_service(data_dir: str) -> BudgetService:
    storage = JsonlStorage(data_dir=data_dir)
    tx_repo = TransactionRepository(storage)
    cat_repo = CategoryRepository(storage)
    budget_repo = BudgetRepository(storage)
    return BudgetService(tx_repo, cat_repo, budget_repo, data_dir=data_dir)


# ----------------------------------------------------
# 1. 거래 추가 (add)
# ----------------------------------------------------
def handle_add(service: BudgetService, args: argparse.Namespace) -> None:
    # PDF 예시(페이지 8 및 10):
    # 날짜 입력 즉시 검증하여 잘못된 경우 즉시 오류/힌트 출력
    date_val = input("날짜(YYYY-MM-DD): ").strip()
    try:
        service.validate_date_input(date_val)
    except ValueError:
        raise ValidationError(
            "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).",
            hint="예: 2024-01-15",
        )

    type_val = input("타입(income/expense): ").strip()
    if type_val.lower() not in ("income", "expense"):
        raise ValidationError(
            f"허용되지 않은 타입입니다: '{type_val}'",
            hint="타입은 'income' 또는 'expense' 중 하나여야 합니다.",
        )

    cat_val = input("카테고리: ").strip()
    if not service.cat_repo.exists(cat_val):
        all_cats = ", ".join(service.cat_repo.list_all())
        raise ValidationError(
            f"등록되지 않은 카테고리입니다: '{cat_val}'",
            hint=f"현재 등록된 카테고리 목록: [{all_cats}]. 'category add' 명령으로 먼저 등록해주세요.",
        )

    amount_val = input("금액(양수): ").strip()
    try:
        amt_int = int(amount_val)
        if amt_int <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError(
            f"금액이 올바르지 않습니다: '{amount_val}'",
            hint="금액은 0보다 큰 양의 정수여야 합니다 (예: 15000).",
        )

    memo_val = input("메모(선택): ").strip()
    tags_raw = input("태그(쉼표로 구분, 없으면 엔터): ").strip()
    tags_val = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    tx = service.add_transaction(
        date_str=date_val,
        tx_type=type_val,
        category=cat_val,
        amount_raw=amount_val,
        memo=memo_val,
        tags=tags_val,
    )
    print(f"[저장 완료] id={tx.id}")


# ----------------------------------------------------
# 2. 거래 목록 (list)
# ----------------------------------------------------
def handle_list(service: BudgetService, args: argparse.Namespace) -> None:
    found = False
    for tx in service.list_transactions(limit=args.limit):
        found = True
        # PDF 예시(페이지 9): TX-000012 | 2024-01-15 | expense | food | 15000 | 점심
        memo_display = tx.memo if tx.memo else ""
        print(f"{tx.id} | {tx.date} | {tx.type} | {tx.category} | {tx.amount} | {memo_display}")

    if not found:
        print("[알림] 등록된 거래 내역이 없습니다.")


# ----------------------------------------------------
# 3. 거래 검색 (search)
# ----------------------------------------------------
def handle_search(service: BudgetService, args: argparse.Namespace) -> None:
    found = False
    for tx in service.search_transactions(
        from_date=args.from_date,
        to_date=args.to_date,
        category=args.category,
        tx_type=args.type,
        query=args.query,
        tag=args.tag,
    ):
        found = True
        memo_display = tx.memo if tx.memo else ""
        print(f"{tx.id} | {tx.date} | {tx.type} | {tx.category} | {tx.amount} | {memo_display}")

    if not found:
        print("[검색 결과] 조건에 맞는 거래 내역이 없습니다.")


# ----------------------------------------------------
# 4. 월별 요약 (summary)
# ----------------------------------------------------
def handle_summary(service: BudgetService, args: argparse.Namespace) -> None:
    result = service.get_monthly_summary(month=args.month, top_n=args.top)

    if not result.get("has_data"):
        print(f"[{args.month}] 데이터 없음")
        return

    print(f"총 수입: {result['total_income']}원")
    print(f"총 지출: {result['total_expense']}원")
    print(f"잔액: {result['balance']}원")

    budget_info = result.get("budget")
    if budget_info:
        usage = budget_info["usage_rate"]
        print(f"예산: {budget_info['amount']}원 (사용률 {usage:.1f}%)")
        if budget_info["is_exceeded"]:
            print(f"⚠️  [경고] 예산을 {budget_info['excess_amount']}원 초과했습니다!")
    else:
        print("예산: 미설정 ('budget set' 명령으로 설정 가능)")

    top_cats = result.get("top_categories", [])
    if top_cats:
        print(f"\n지출 TOP {len(top_cats)}")
        for idx, (cat, amt) in enumerate(top_cats, 1):
            print(f"{idx}) {cat} {amt}원")


# ----------------------------------------------------
# 5. 예산 설정/조회 (budget)
# ----------------------------------------------------
def handle_budget(service: BudgetService, args: argparse.Namespace) -> None:
    if args.budget_action == "set":
        if not args.month or args.amount is None:
            raise ValidationError(
                "예산 설정 시 -month 및 -amount가 필요합니다.",
                hint="예: budget set -month 2024-01 -amount 500000",
            )
        b = service.set_budget(month=args.month, amount_raw=args.amount)
        print(f"[저장 완료] {b.month} 예산 {b.amount}원")
    elif args.budget_action == "get":
        if not args.month:
            raise ValidationError("조회할 월을 입력해주세요.", hint="예: budget get -month 2024-01")
        b = service.get_budget(month=args.month)
        if b:
            print(f"[{b.month}] 설정 예산: {b.amount}원")
        else:
            print(f"[{args.month}] 설정된 예산이 없습니다.")
    else:
        raise ValidationError("budget 서브명령은 'set' 또는 'get'이어야 합니다.")


# ----------------------------------------------------
# 6. 카테고리 관리 (category)
# ----------------------------------------------------
def handle_category(service: BudgetService, args: argparse.Namespace) -> None:
    if args.category_action == "list":
        cats = service.list_categories()
        if not cats:
            print("[알림] 등록된 카테고리가 없습니다.")
        else:
            for cat in cats:
                print(f"- {cat}")
    elif args.category_action == "add":
        if not args.name:
            name = input("카테고리명: ").strip()
        else:
            name = args.name
        added = service.add_category(name)
        print(f"[저장 완료] category={added}")
    elif args.category_action == "remove":
        if not args.name:
            raise ValidationError("삭제할 카테고리명을 지정해주세요.", hint="category remove <name>")
        success, reassigned = service.remove_category(args.name, replacement=args.replace)
        if reassigned > 0:
            print(f"[삭제 완료] category={args.name} (기존 {reassigned}건의 거래가 '{args.replace}'(으)로 대체됨)")
        else:
            print(f"[삭제 완료] category={args.name}")
    else:
        raise ValidationError("category 서브명령은 'list', 'add', 'remove' 중 하나여야 합니다.")


# ----------------------------------------------------
# 7. 거래 수정 (update)
# ----------------------------------------------------
def handle_update(service: BudgetService, args: argparse.Namespace) -> None:
    tx_id = args.id
    existing = service.tx_repo.find_by_id(tx_id)
    if not existing:
        raise ValidationError(
            f"없는 데이터: 존재하지 않는 거래 ID입니다: '{tx_id}'",
            hint="'list' 명령으로 거래 ID를 확인하세요.",
        )

    has_flags = any([args.date, args.type, args.category, args.amount, args.memo, args.tags])
    if not has_flags:
        print(f"거래 [{tx_id}] 수정 (변경하지 않으려면 그냥 엔터를 누르세요)")
        d_in = input(f"날짜 [{existing.date}]: ").strip()
        t_in = input(f"타입 [{existing.type}]: ").strip()
        c_in = input(f"카테고리 [{existing.category}]: ").strip()
        a_in = input(f"금액 [{existing.amount}]: ").strip()
        m_in = input(f"메모 [{existing.memo}]: ").strip()
        tags_in = input(f"태그 [{','.join(existing.tags)}]: ").strip()

        date_val = d_in if d_in else None
        type_val = t_in if t_in else None
        cat_val = c_in if c_in else None
        amt_val = a_in if a_in else None
        memo_val = m_in if m_in else None
        tags_val = [x.strip() for x in tags_in.split(",") if x.strip()] if tags_in else None
    else:
        date_val = args.date
        type_val = args.type
        cat_val = args.category
        amt_val = args.amount
        memo_val = args.memo
        tags_val = [x.strip() for x in args.tags.split(",") if x.strip()] if args.tags else None

    updated = service.update_transaction(
        tx_id=tx_id,
        date=date_val,
        tx_type=type_val,
        category=cat_val,
        amount=amt_val,
        memo=memo_val,
        tags=tags_val,
    )
    print(f"[수정 완료] id={updated.id} | {updated.date} | {updated.type} | {updated.category} | {updated.amount}")


# ----------------------------------------------------
# 8. 거래 삭제 (delete)
# ----------------------------------------------------
def handle_delete(service: BudgetService, args: argparse.Namespace) -> None:
    tx_id = args.id
    service.delete_transaction(tx_id)
    print(f"[삭제 완료] id={tx_id}")


# ----------------------------------------------------
# 9. 가져오기 / 내보내기 (import / export)
# ----------------------------------------------------
def handle_import(service: BudgetService, args: argparse.Namespace) -> None:
    imported, skipped = service.import_csv(args.from_file)
    print(f"[완료] imported={imported}, skipped={skipped}")


def handle_export(service: BudgetService, args: argparse.Namespace) -> None:
    count = service.export_csv(
        out_path=args.out,
        month=args.month,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    print(f"[완료] {args.out} ({count} records)")


# ----------------------------------------------------
# 10. 백업 (backup - 보너스 과제 1)
# ----------------------------------------------------
def handle_backup(service: BudgetService, args: argparse.Namespace) -> None:
    backup_path = service.backup_data()
    print(f"[백업 완료] 안전하게 저장되었습니다: {backup_path}")


# ----------------------------------------------------
# CLI 메인 파서 정의 (단일 대시 '-' 와 이중 대시 '--' 모두 지원)
# ----------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m budget_app",
        description="나만의 용돈 기입장 (안전한 콘솔 가계부 프로그램)",
    )
    parser.add_argument(
        "-data-dir", "--data-dir",
        default=DEFAULT_DATA_DIR,
        help="데이터 저장소 디렉터리 경로 (기본값: ./data)",
    )

    subparsers = parser.add_subparsers(dest="command", help="사용 가능한 명령어 목록")

    # 1. add
    subparsers.add_parser("add", help="대화형으로 새로운 거래 추가")

    # 2. list
    list_p = subparsers.add_parser("list", help="최신순 거래 목록 조회")
    list_p.add_argument("-limit", "--limit", type=int, default=10, help="조회할 최대 거래 건수 (기본값: 10)")

    # 3. search
    search_p = subparsers.add_parser("search", help="조건별 거래 검색")
    search_p.add_argument("-from", "--from", dest="from_date", help="검색 시작 날짜 (YYYY-MM-DD)")
    search_p.add_argument("-to", "--to", dest="to_date", help="검색 종료 날짜 (YYYY-MM-DD)")
    search_p.add_argument("-category", "--category", help="카테고리 필터")
    search_p.add_argument("-type", "--type", choices=["income", "expense"], help="수입/지출 타입 필터")
    search_p.add_argument("-q", "--query", help="메모 키워드 검색")
    search_p.add_argument("-tag", "--tag", help="태그 필터")

    # 4. summary
    summary_p = subparsers.add_parser("summary", help="월별 수입/지출/예산 요약 통계")
    summary_p.add_argument("-month", "--month", required=True, help="조회할 월 (YYYY-MM)")
    summary_p.add_argument("-top", "--top", type=int, default=3, help="지출 상위 카테고리 개수 (기본값: 3)")

    # 5. budget
    budget_p = subparsers.add_parser("budget", help="월별 예산 설정 및 조회")
    budget_sub = budget_p.add_subparsers(dest="budget_action", required=True)
    b_set = budget_sub.add_parser("set", help="예산 설정")
    b_set.add_argument("-month", "--month", required=True, help="대상 월 (YYYY-MM)")
    b_set.add_argument("-amount", "--amount", type=int, required=True, help="예산 금액 (원)")
    b_get = budget_sub.add_parser("get", help="예산 조회")
    b_get.add_argument("-month", "--month", required=True, help="대상 월 (YYYY-MM)")

    # 6. category
    cat_p = subparsers.add_parser("category", help="카테고리 관리")
    cat_sub = cat_p.add_subparsers(dest="category_action", required=True)
    cat_sub.add_parser("list", help="카테고리 목록 조회")
    cat_add = cat_sub.add_parser("add", help="새 카테고리 추가")
    cat_add.add_argument("name", nargs="?", default="", help="카테고리 이름")
    cat_rem = cat_sub.add_parser("remove", help="카테고리 삭제")
    cat_rem.add_argument("name", help="삭제할 카테고리 이름")
    cat_rem.add_argument("-replace", "--replace", help="사용 중인 카테고리 삭제 시 대체할 카테고리 이름")

    # 7. update
    update_p = subparsers.add_parser("update", help="기존 거래 수정")
    update_p.add_argument("-id", "--id", required=True, help="수정할 거래 ID (예: TX-000001)")
    update_p.add_argument("-date", "--date", help="새 날짜 (YYYY-MM-DD)")
    update_p.add_argument("-type", "--type", choices=["income", "expense"], help="새 타입")
    update_p.add_argument("-category", "--category", help="새 카테고리")
    update_p.add_argument("-amount", "--amount", type=int, help="새 금액")
    update_p.add_argument("-memo", "--memo", help="새 메모")
    update_p.add_argument("-tags", "--tags", help="새 태그 (쉼표로 구분)")

    # 8. delete
    del_p = subparsers.add_parser("delete", help="거래 삭제")
    del_p.add_argument("-id", "--id", required=True, help="삭제할 거래 ID")

    # 9. import / export
    import_p = subparsers.add_parser("import", help="CSV 파일에서 거래 일괄 등록")
    import_p.add_argument("-from", "--from", dest="from_file", required=True, help="가져올 CSV 파일 경로")

    export_p = subparsers.add_parser("export", help="조건에 맞는 거래를 CSV로 내보내기")
    export_p.add_argument("-out", "--out", required=True, help="출력할 CSV 파일 경로")
    export_p.add_argument("-month", "--month", help="내보낼 월 (YYYY-MM)")
    export_p.add_argument("-from", "--from", dest="from_date", help="시작일 (YYYY-MM-DD)")
    export_p.add_argument("-to", "--to", dest="to_date", help="종료일 (YYYY-MM-DD)")

    # 10. backup
    subparsers.add_parser("backup", help="전체 데이터 디렉터리 백업 (보너스 과제)")

    return parser


@handle_errors
@measure_execution_time
def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    service = create_service(args.data_dir)

    handlers = {
        "add": handle_add,
        "list": handle_list,
        "search": handle_search,
        "summary": handle_summary,
        "budget": handle_budget,
        "category": handle_category,
        "update": handle_update,
        "delete": handle_delete,
        "import": handle_import,
        "export": handle_export,
        "backup": handle_backup,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(service, args)
    else:
        parser.print_help()
