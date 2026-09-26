# 📘 초보자를 위한 [나만의 용돈 기입장] 단계별 구현 튜토리얼

> **환영합니다!**  
> 이 문서는 파이썬의 핵심 고급 문법(데이터클래스, 제너레이터, 데코레이터, 모듈화)을 적용하여 **"유지보수 가능하고 안전한 콘솔 가계부 프로그램"**을 단계별로 완성할 수 있도록 돕는 친절한 가이드북입니다.

---

## 🧭 전체 지도: 우리가 만들 프로그램의 구조

가장 먼저 "어떤 파일들을 만들고, 각 파일이 무슨 일을 하는지" 머릿속에 그림을 그려보겠습니다.

### 1. 계층형 아키텍처 (Layered Architecture)
코드를 하나의 큰 파일에 모두 넣으면 나중에 고치기 어렵고 버그를 찾기도 힘듭니다. 그래서 역할을 명확히 나눕니다.

```
┌──────────────────────────────────────────────┐
│  1. CLI 계층 (cli.py, __main__.py)           │  <- 사용자 입력(명령행/대화형) 처리 및 화면 출력
├──────────────────────────────────────────────┤
│  2. 서비스 계층 (service.py)                  │  <- 비즈니스 로직 (요약 계산, 검증 규칙 등)
├──────────────────────────────────────────────┤
│  3. 저장소 계층 (repository.py, storage.py)   │  <- 파일 읽기/쓰기 (JSONL/CSV, 제너레이터 스트리밍)
├──────────────────────────────────────────────┤
│  4. 모델 계층 (models.py)                    │  <- 데이터 규격 (Transaction, Budget 등)
└──────────────────────────────────────────────┘
```

### 2. 추천 디렉터리 구조
외부 라이브러리(`pip`) 설치 없이 **파이썬 표준 라이브러리만 사용**하여 만듭니다.

```text
Basic_2-1_budget-app/
├── budget_app/
│   ├── __init__.py          # 패키지 인식용 파일
│   ├── __main__.py          # python -m budget_app 실행 진입점
│   ├── models.py            # dataclass 기반 데이터 모델 (Transaction, Budget 등)
│   ├── utils.py             # 데코레이터 (예외 처리, 시간 측정) 및 헬퍼 함수
│   ├── storage.py           # JSONL 파일 I/O 및 제너레이터 스트리밍
│   ├── repository.py        # 도메인별 저장소 (Transaction, Category, Budget)
│   ├── service.py           # 핵심 비즈니스 로직 (통계, 요약, CRUD 검증)
│   └── cli.py               # argparse 기반 CLI 파서 및 대화형 입출력
├── data/                    # 데이터 파일 저장 폴더 (자동 생성)
│   ├── transactions.jsonl   # 거래 내역 (1행 = 1 JSON)
│   ├── categories.jsonl     # 카테고리 목록
│   └── budgets.jsonl        # 월별 예산 데이터
└── README.md                # 실행 방법 및 명세 설명서
```

---

## 💡 핵심 개념 4가지 쉽게 이해하기

### ① dataclass (데이터 모델)
- **개념**: 딕셔너리(`{"amount": 1000}`) 대신 속성 이름과 타입이 정해진 클래스 객체로 데이터를 다룹니다.
- **장점**: 오타 방지(`tx.ammount` 방지), 자동완성 지원, 코드 가독성 향상.
```python
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Transaction:
    id: str
    type: str             # "income" 또는 "expense"
    date: str             # "YYYY-MM-DD"
    amount: int           # 양의 정수
    category: str         # 등록된 카테고리
    memo: Optional[str] = ""
    tags: Optional[List[str]] = None
```

### ② 제너레이터와 `yield` (스트리밍 처리)
- **왜 필요한가?**: 거래 내역이 100만 건이면, 한 번에 `read()`나 `list`로 메모리에 올릴 때 프로그램이 멈추거나 메모리가 부족해집니다.
- **해결책**: `yield`를 사용하면 한 줄씩 읽어서 전달하므로 메모리를 거의 쓰지 않고 빠르게 처리할 수 있습니다.
```python
def stream_transactions(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield parse_transaction(line)  # 한 줄씩 그때그때 반환!
```

### ③ 데코레이터 (Decorator)
- **왜 필요한가?**: 모든 함수마다 `try ... except`를 쓰거나 실행 시간 측정 코드를 중복 작성하지 않고, 모자(데코레이터)를 씌워 공통 기능을 분리합니다.
```python
import functools
import sys

def handle_errors(func):
    """스택트레이스를 숨기고 친절한 에러 메시지와 함께 비정상 종료(exit code 1)하는 데코레이터"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            print(f"[오류] {e}")
            print("[힌트] 입력 형식을 다시 확인해주세요.")
            sys.exit(1)
        except Exception as e:
            print(f"[시스템 오류] {e}")
            sys.exit(1)
    return wrapper
```

### ④ 파일 안전 교체 (원자적 교체, Atomic Replace)
- **수정/삭제 시 주의점**: 수정 도중 컴퓨터 전원이 꺼지면 파일이 손상될 수 있습니다.
- **안전한 방법**: `transactions.tmp` 임시 파일에 먼저 쓴 뒤, 쓰기가 완벽히 끝나면 `os.replace()`로 원본 파일과 바꿉니다.

---

## 🚀 단계별 구현 로드맵 (Step-by-Step)

### [Step 1] 데이터 모델과 저장소 설계 (`models.py`, `storage.py`)
1. `models.py`에 `Transaction`, `Category`, `Budget`의 `dataclass` 정의하기.
2. 데이터를 저장할 포맷으로 **JSONL (JSON Lines)** 선택 추천:
   - 각 줄이 독립된 JSON이므로 줄 단위 스트리밍(제너레이터) 구현이 매우 자연스럽고 강력합니다.
3. `storage.py`에 파일 읽기/쓰기 기본 함수 구현:
   - 파일이 없으면 자동 생성 또는 기본 폴더(`data/`) 생성
   - `yield`를 사용한 스트리밍 읽기 함수 작성

### [Step 2] 저장소 계층 구현 (`repository.py`)
1. **TransactionRepository**:
   - `save(transaction)`: 파일 끝에 추가 (append)
   - `stream_all()`: 최신순 또는 역순 스트리밍
   - `find_by_id(id)`: ID 일치 항목 탐색
   - `update(updated_tx)` & `delete(id)`: 임시 파일(`os.replace`)을 통한 원자적 갱신
2. **CategoryRepository**:
   - 초기 카테고리(`food`, `transport`, `rent` 등) 기본값 제공
   - 카테고리 추가/삭제/목록 조회
3. **BudgetRepository**:
   - `set_budget(month, amount)`, `get_budget(month)`

### [Step 3] 비즈니스 로직과 서비스 계층 (`service.py`)
1. **유효성 검사**:
   - 날짜 포맷 (`YYYY-MM-DD`) 검증
   - 금액 양수 검증 (`amount > 0`)
   - 타입 검증 (`income` / `expense`)
   - 존재하는 카테고리인지 확인
2. **검색 및 필터링 (제너레이터 체이닝)**:
   - 날짜 범위(`--from`, `--to`), 카테고리, 메모 키워드 검색
3. **통계 및 요약 계산**:
   - 특정 월(`--month YYYY-MM`) 총 수입/지출/잔액 합산
   - 카테고리별 지출 Top N 추출
   - 예산 대비 지출 사용률(%) 및 초과 경고 알림

### [Step 4] 공통 관심사 데코레이터 분리 (`utils.py`)
1. 스택트레이스(Traceback) 대신 **[원인] + [해결 힌트]**를 출력하고 `sys.exit(1)` 처리하는 예외 처리 데코레이터 구현.
2. (선택) 실행 시간 측정 데코레이터 또는 로깅 데코레이터 추가.

### [Step 5] CLI 인터페이스 구축 (`cli.py`, `__main__.py`)
1. `argparse`를 활용하여 서브커맨드 구조 설계:
   - `add`: 대화형 `input()`으로 날짜, 타입, 카테고리, 금액, 메모, 태그 순차 입력받기
   - `list`: `--limit` 옵션 처리
   - `search`: `--from`, `--to`, `--category`, `--type`, `-q`, `--tag` 옵션 처리
   - `summary`: `--month`, `--top` 옵션 처리
   - `budget`: `set --month --amount` 처리
   - `category`: `add`, `list`, `remove` 처리
   - `update` / `delete`: `--id` 인자 처리
   - `import` / `export`: CSV 파일 변환 및 스키마 검증
2. 공통 옵션 `--data-dir` 및 리눅스 표준 옵션(`--`) 통일.

### [Step 6] CSV Import / Export 기능
- 파이썬 내장 `csv` 모듈 활용
- CSV 스키마: `date,type,category,amount,memo,tags`
- 필수 필드 누락 검증 및 일괄 등록/내보내기

---

## 🎯 요구사항 점검 체크리스트 (자가 진단표)

| 번호 | 요구사항 항목 | 체크 포인트 |
|:---:|:---|:---|
| 1 | **거래 추가 (`add`)** | 대화형 입력 방식인가? 없는 카테고리 입력 시 친절히 안내하는가? 생성된 ID가 출력되는가? |
| 2 | **거래 목록 (`list`)** | 최신순 정렬인가? `--limit` 옵션이 잘 동작하는가? 제너레이터 스트리밍인가? |
| 3 | **거래 검색 (`search`)** | 날짜 범위, 카테고리, 검색어, 태그 조건이 올바르게 필터링되는가? |
| 4 | **월별 요약 (`summary`)** | 수입/지출/잔액, 지출 Top N, 예산 사용률 및 초과 경고가 잘 나오는가? |
| 5 | **예산 관리 (`budget`)** | 월별 예산이 영구 저장되며 summary와 연동되는가? |
| 6 | **카테고리 관리 (`category`)** | 추가/조회/삭제 및 "사용 중인 카테고리 삭제 방지" 로직이 있는가? |
| 7 | **수정/삭제 (`update`/`delete`)** | 없는 ID 예외 처리와 임시 파일을 통한 안전한 갱신이 되는가? |
| 8 | **가져오기/내보내기 (`import/export`)** | 지정된 CSV 규격(헤더 포함, UTF-8)을 준수하는가? |
| 9 | **아키텍처 & 제약** | 외부 pip 없이 표준 라이브러리만 사용했는가? 파일 3개 이상(transactions, categories, budgets) 분리 저장되는가? |
| 10 | **예외 처리 & 데코레이터** | 스택트레이스(Traceback)가 노출되지 않고 힌트와 비정상 종료 코드가 반환되는가? |

---

## 💡 개발 팁: 초보자가 자주 마주치는 난관과 꿀팁

1. **"대화형 입력에서 잘못 입력했을 때 어떻게 하나요?"**
   - 루프(`while True`)를 돌면서 유효한 값이 들어올 때까지 재입력을 받도록 구현하면 사용성이 훨씬 좋아집니다.
2. **"JSONL vs CSV 중 무엇이 좋은가요?"**
   - **JSONL**을 적극 추천합니다! JSON 형태라서 태그 리스트(`tags: ["식비", "외식"]`)나 빈 메모 등을 다루기 훨씬 편리하고 안전합니다.
3. **"스택트레이스(Traceback) 숨기기"**
   - 모든 메인 함수 호출부에 데코레이터를 적용하거나, CLI 진입점에서 `try-except`로 걸러서 사용자에게 에러 메시지와 힌트만 출력합니다.
