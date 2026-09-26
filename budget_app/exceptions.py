from typing import Optional


class BudgetAppError(Exception):
    """예산 앱 기본 예외 클래스"""
    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.hint = hint


class ValidationError(BudgetAppError):
    """사용자 입력 또는 데이터 포맷 유효성 검증 실패"""
    pass


class NotFoundError(BudgetAppError):
    """데이터(ID, 카테고리 등)를 찾을 수 없음"""
    pass


class ConflictError(BudgetAppError):
    """중복 데이터 또는 참조 무결성 제약 위반"""
    pass
