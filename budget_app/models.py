from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Transaction:
    id: str
    type: str  # "income" | "expense"
    date: str  # "YYYY-MM-DD"
    amount: int  # 양의 정수
    category: str
    memo: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "date": self.date,
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Transaction:
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            date=str(data["date"]),
            amount=int(data["amount"]),
            category=str(data["category"]),
            memo=str(data.get("memo", "") or ""),
            tags=list(data.get("tags") or []),
        )


@dataclass
class Category:
    name: str

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Category:
        return cls(name=str(data["name"]))


@dataclass
class Budget:
    month: str  # "YYYY-MM"
    amount: int  # 0 이상 정수

    def to_dict(self) -> Dict[str, Any]:
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
