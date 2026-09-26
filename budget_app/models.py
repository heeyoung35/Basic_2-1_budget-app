"""
데이터 모델 계층 (Domain Models)
-------------------------------
이 모듈은 가계부 도메인의 핵심 엔티티와 타입 계약(Protocol, TypedDict)을 정의합니다.

책임 경계:
- Transaction, Category, Budget 객체의 불변성과 필드 타입 정의
- 딕셔너리 직렬화/역직렬화 계약
- 기본 도메인 자체 검증(self-validation)
"""

from __future__ import annotations
from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Protocol, TypedDict


class TransactionDict(TypedDict, total=False):
    """Transaction 외부 인터페이스를 위한 TypedDict 계약 (평가 #13 보완)"""
    id: str
    type: str
    date: str
    amount: int
    category: str
    memo: str
    tags: List[str]


class CategoryDict(TypedDict):
    name: str


class BudgetDict(TypedDict):
    month: str
    amount: int


class RepositoryProtocol(Protocol):
    """저장소 인터페이스에 대한 정적 타입 계약 (Protocol)"""
    def generate_next_id(self) -> str: ...


@dataclass(frozen=True)
class Transaction:
    """
    거래 내역 엔티티 (불변 객체: frozen=True)
    - id: 고유 식별자 (예: 'TX-000001')
    - type: 'income' 또는 'expense'
    - date: 거래 일자 (YYYY-MM-DD)
    - amount: 거래 금액 (양의 정수)
    - category: 카테고리명
    - memo: 비고/메모 (기본값 "")
    - tags: 태그 목록 (기본값 [])
    """
    id: str
    type: str
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: List[str] = field(default_factory=list)

    def validate(self) -> None:
        """엔티티 자체 유효성 검증 (평가 #9 보완)"""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", self.date):
            raise ValueError(f"유효하지 않은 날짜 형식입니다: {self.date}")
        if self.type not in ("income", "expense"):
            raise ValueError(f"유효하지 않은 거래 타입입니다: {self.type}")
        if self.amount <= 0:
            raise ValueError(f"금액은 양수여야 합니다: {self.amount}")
        if not self.category.strip():
            raise ValueError("카테고리는 비어있을 수 없습니다.")

    def to_dict(self) -> TransactionDict:
        """딕셔너리 직렬화"""
        return {
            "id": self.id,
            "type": self.type,
            "date": self.date,
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Transaction:
        """딕셔너리로부터 엔티티 역직렬화"""
        instance = cls(
            id=str(data["id"]),
            type=str(data["type"]),
            date=str(data["date"]),
            amount=int(data["amount"]),
            category=str(data["category"]),
            memo=str(data.get("memo", "") or ""),
            tags=list(data.get("tags") or []),
        )
        instance.validate()
        return instance


@dataclass(frozen=True)
class Category:
    """
    카테고리 엔티티 (불변 객체)
    - name: 카테고리 고유 식별명
    """
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("카테고리 이름은 공백일 수 없습니다.")

    def to_dict(self) -> CategoryDict:
        return {"name": self.name}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Category:
        return cls(name=str(data["name"]))


@dataclass(frozen=True)
class Budget:
    """
    월별 예산 엔티티 (불변 객체)
    - month: 대상 월 (YYYY-MM)
    - amount: 예산 설정 금액 (0 이상의 정수)
    """
    month: str
    amount: int

    def __post_init__(self) -> None:
        if not re.match(r"^\d{4}-\d{2}$", self.month):
            raise ValueError(f"유효하지 않은 월 형식입니다: {self.month}")
        if self.amount < 0:
            raise ValueError(f"예산 금액은 0 이상이어야 합니다: {self.amount}")

    def to_dict(self) -> BudgetDict:
        return {
            "month": self.month,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Budget:
        return cls(
            month=str(data["month"]),
            amount=int(data["amount"]),
        )
