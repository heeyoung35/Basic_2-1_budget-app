from typing import Optional


class BudgetAppError(Exception):
    """
    예산 앱 최상위 기본 예외 클래스
    - error_code: 표준 에러 식별 코드
    - message: 사용자 친화적 오류 원인 설명
    - hint: 오류 해결 가이드
    """
    def __init__(self, message: str, hint: Optional[str] = None, error_code: str = "ERR_GENERAL"):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.error_code = error_code


class ValidationError(BudgetAppError):
    """입력 데이터 형식 또는 도메인 규칙 위반 (예: 잘못된 날짜, 음수 금액)"""
    def __init__(self, message: str, hint: Optional[str] = None, error_code: str = "ERR_VALIDATION"):
        super().__init__(message, hint, error_code)


class NotFoundError(BudgetAppError):
    """요청한 리소스(거래 ID, 카테고리 등)가 존재하지 않음"""
    def __init__(self, message: str, hint: Optional[str] = None, error_code: str = "ERR_NOT_FOUND"):
        super().__init__(message, hint, error_code)


class ConflictError(BudgetAppError):
    """데이터 무결성 충돌 또는 참조 무결성 제약 위반 (예: 사용 중인 카테고리 삭제)"""
    def __init__(self, message: str, hint: Optional[str] = None, error_code: str = "ERR_CONFLICT"):
        super().__init__(message, hint, error_code)


class AtomicImportError(BudgetAppError):
    """CSV 일괄 등록 중 원자성(All-or-Nothing) 위반으로 롤백됨"""
    def __init__(self, message: str, hint: Optional[str] = None, error_code: str = "ERR_ATOMIC_IMPORT"):
        super().__init__(message, hint, error_code)
