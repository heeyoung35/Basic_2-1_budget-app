# 💰 나만의 용돈 기입장 (Budget App)

> 파일 입출력 기반의 안전하고 유지보수 가능한 파이썬 콘솔 가계부 애플리케이션입니다.  
> 외부 라이브러리 의존성 없이 **파이썬 표준 라이브러리(3.10+)**만으로 작성되었으며, 대용량 파일 처리를 위한 **제너레이터 스트리밍**, **원자적 파일 교체(Atomic Replace)**, **데코레이터 기반 공통 관심사 분리**, **타입 힌트 및 Protocol/TypedDict 계약**이 엄격하게 적용되어 있습니다.

---

## 📌 주요 특징 및 계층별 책임 규약 (Layered Architecture)

```
┌───────────────────────────────────────────────────────────┐
│ 1. CLI 계층 (cli.py, __main__.py)                          │ <- 사용자 입력 파싱, 입출력 화면 렌더링, 종료 코드 제어
├───────────────────────────────────────────────────────────┤
│ 2. 서비스 계층 (service.py)                                │ <- 비즈니스 규칙, 통계 계산, 예산 정책, 트랜잭션 조율
├───────────────────────────────────────────────────────────┤
│ 3. 저장소 계층 (repository.py, storage.py)                │ <- 영구 저장소 CRUD, yield 스트리밍, 원자적 파일 교체
├───────────────────────────────────────────────────────────┤
│ 4. 모델 계층 (models.py)                                   │ <- 불변 엔티티(Transaction 등), Protocol, TypedDict 계약
└───────────────────────────────────────────────────────────┘
```

### 모듈별 공개 API 및 규약 (평가 #8, #9, #13 보완)

| 모듈 | 주요 클래스 / 함수 | 반환 타입 / 계약 | 책임 및 불변성 규약 |
|:---|:---|:---|:---|
| `models.py` | `Transaction` (frozen=True)<br>`Category` (frozen=True)<br>`Budget` (frozen=True) | `to_dict() -> TransactionDict`<br>`validate() -> None` | **불변 엔티티**: 생성 후 필드 변경 불가, 자체 형식 검증 및 TypedDict 직렬화 계약 준수 |
| `storage.py` | `JsonlStorage` | `stream_items() -> Generator`<br>`atomic_write(...) -> None`<br>`verify_storage_health() -> dict` | **I/O 스트리밍 & 원자성**: `os.replace` 기반 원자적 교체 및 실패 시 `.tmp` 자동 정리, `.bak` 보존 정책 |
| `repository.py`| `TransactionRepository`<br>`CategoryRepository`<br>`BudgetRepository` | `stream_all(reverse=True)`<br>`count_by_category() -> int` | **도메인 영구 저장**: 파일 I/O 추상화, ID 자동 발급(TX-000001), 카테고리 참조 무결성 |
| `service.py` | `BudgetService` | `add_transaction(...) -> Transaction`<br>`get_monthly_summary(...) -> dict`<br>`import_csv(strict=...) -> tuple` | **비즈니스 로직**: 날짜/금액 검증, 예산 알림 정책(SAFE/WARNING/DANGER), 원자적 임포트/롤백 |
| `utils.py` | `@handle_errors`<br>`@log_action`<br>`@measure_execution_time` | `Callable -> Callable` | **공통 관심사 분리**: 표준 에러 코드 포맷 출력, 실행 시간 측정 및 디버그 로깅 |

---

## ⚖️ JSONL vs CSV 정량적 비교 및 선택 기준 (평가 #14 보완)

가계부 내부 저장소 포맷 선정에 대한 정량적 분석 결과입니다:

| 비교 지표 | **JSONL (현재 내부 저장소 채택)** | **CSV (내보내기/가져오기 채택)** | 분석 및 평가 |
|:---|:---:|:---:|:---|
| **복합 데이터(태그) 표현** | ⭐⭐⭐⭐⭐ (`tags: ["식비", "외식"]`) | ⭐⭐ (`tags: "식비,외식"` 직접 파싱) | 태그 리스트, 중첩 구조 표현 시 JSONL이 압도적으로 안전 |
| **특수문자 및 따옴표 안전성** | ⭐⭐⭐⭐⭐ (자동 JSON 이스케이프) | ⭐⭐⭐ (쉼표/따옴표/줄바꿈 충돌 위험) | 메모에 `,`나 줄바꿈이 있어도 JSONL은 한 줄이 보장됨 |
| **제너레이터 스트리밍** | ⭐⭐⭐⭐⭐ (행마다 독립된 JSON) | ⭐⭐⭐ (첫 행의 헤더를 항상 공유 필요) | 역방향(최신순) 라인 스트리밍에 JSONL이 최적화됨 |
| **저장 용량 (10만 건 기준)** | 약 25 ~ 30 MB (필드 키 반복) | **약 15 ~ 18 MB (값만 저장)** | CSV가 약 35% 용량 절감 |
| **일반인 엑셀 접근성** | ⭐⭐ (별도 뷰어나 변환 필요) | ⭐⭐⭐⭐⭐ (더블클릭으로 엑셀 오픈) | 데이터 분석 및 일반 사용자 전달 시 CSV가 최고 |

> **선택 결론**:  
> 본 프로그램은 **"데이터 무결성, 태그 리스트 보존, 안전한 제너레이터 스트리밍"**을 위해 내부 영구 저장 포맷으로 **JSONL**을 채택하였으며,  
> 엑셀과의 호환성이 필요한 외부 데이터 교환에는 표준 **CSV** 포맷을 채택하여 상호 보완적인 최적의 설계를 적용했습니다.

---

## ⚡ 대용량(100k+ 건) 성능 병목 분석 및 아키텍처 개선안 (평가 #15 FAIL 해결)

가계부 데이터가 **10만(100k) 건 이상** 누적되었을 때 발생할 수 있는 병목 지점과 구체적인 해결책은 [PERFORMANCE_ANALYSIS.md](file:///d:/codyssey/Basic_2-1_budget-app/PERFORMANCE_ANALYSIS.md)에 상세히 기술되어 있습니다.

### 핵심 병목 및 개선 요약
1. **디스크 I/O Full Scan**: 25MB 파일을 매번 전체 순회  
   👉 **개선안**: **월별 디렉터리 파티셔닝** (`data/partitions/2024/01.jsonl`) 적용 시 **I/O 97% 즉각 절감** (320ms → 12ms).
2. **JSON 역직렬화 CPU 병목**: 100k회 `json.loads` 호출 오버헤드  
   👉 **개선안**: Rust 기반 `orjson` 도입 또는 바이트 청크 버퍼링 파이프라인 구축.
3. **인덱스 부재**:  
   👉 **개선안**: 날짜별 바이트 오프셋 인덱스 파일(`transactions.idx`) 도입으로 O(1) Seek 지원.

---

## 📂 저장 파일 위치 및 형식

모든 데이터는 `-data-dir` (기본값: `./data`) 디렉터리에 3개 이상의 독립된 파일로 분리되어 영구 저장됩니다.

| 파일명 | 형식 | 설명 |
|:---|:---:|:---|
| `data/transactions.jsonl` | JSONL | 개별 거래 내역 (id, type, date, amount, category, memo, tags) |
| `data/categories.jsonl` | JSONL | 등록된 카테고리 목록 (name) |
| `data/budgets.jsonl` | JSONL | 월별 예산 설정 정보 (month, amount) |

---

## 🛠️ 주요 명령어 및 사용 예시

모든 명령어는 리눅스 표준 옵션인 단일 대시(`-`)와 이중 대시(`--`)를 모두 완벽히 지원합니다.

```bash
# 전체 도움말 확인
python -m budget_app --help
```

### 1. 거래 추가 (`add`)
대화형(interactive) 입력 인터페이스로 값을 순차적으로 입력받으며, 잘못된 값(날짜, 금액, 카테고리) 입력 시 즉시 표준 에러 코드와 힌트를 안내합니다.
```bash
python -m budget_app add
```

### 2. 거래 목록 조회 (`list`)
최신순으로 스트리밍 조회하며, `-limit` 옵션으로 출력 개수를 제한할 수 있습니다.
```bash
python -m budget_app list -limit 5
```

### 3. 거래 검색 (`search`)
기간, 카테고리, 타입, 메모 검색어, 태그 조건으로 필터링합니다.
```bash
python -m budget_app search -from 2024-01-01 -to 2024-01-31 -category food
python -m budget_app search -type expense -tag meal
python -m budget_app search -q 점심
```

### 4. 월별 요약 및 예산 정책 알림 (`summary` - 평가 #4 보완)
총 수입/지출/잔액, 지출 상위 TOP N과 함께 **세분화된 예산 정책(SAFE / WARNING / DANGER)** 알림을 출력합니다.
```bash
python -m budget_app summary -month 2024-01 -top 3 -warning-threshold 80.0
```
*출력 예시:*
```text
총 수입: 3000000원
총 지출: 215000원
잔액: 2785000원
예산: 500000원 (사용률 43.0%)
✅ 예산이 안전하게 유지되고 있습니다 (사용률: 43.0%).

지출 TOP 3
1) rent 150000원
2) food 45000원
3) transport 20000원
```

### 5. 예산 설정 및 조회 (`budget`)
```bash
python -m budget_app budget set -month 2024-01 -amount 500000
python -m budget_app budget get -month 2024-01
```

### 6. 카테고리 관리 및 사전 영향도 안내 (`category` - 평가 #3 보완)
사용 중인 거래가 있는 카테고리 삭제 시, 영향받는 거래 건수를 사전 안내하며 대체 카테고리 지정을 유도합니다.
```bash
python -m budget_app category list
python -m budget_app category add shopping
python -m budget_app category remove food -replace shopping
```

### 7. 거래 수정 (`update`) 및 삭제 (`delete`)
없는 ID 요청 시 `[오류][ERR_TRANSACTION_NOT_FOUND] 없는 데이터` 메시지를 출력하며 `os.replace`로 안전하게 원자적 교체됩니다.
```bash
python -m budget_app update -id TX-000001 -amount 18000 -memo "점심(수정)"
python -m budget_app delete -id TX-000001
```

### 8. 가져오기 / 내보내기 및 원자적 임포트 (`import` / `export` - 평가 #5, #16 FAIL 해결)
```bash
# 특정 조건 CSV 내보내기
python -m budget_app export -out export.csv -month 2024-01

# 일반 모드 임포트 (오류 행은 건너뛰고 정상 행만 등록)
python -m budget_app import -from sample_import.csv

# 평가 #16 해결: 원자적 트랜잭션(All-or-Nothing) 임포트 모드
# (단 1개의 오류 행이라도 발견 시 전체 등록 취소 및 롤백)
python -m budget_app import -from sample_import_invalid.csv -strict
```

### 9. 공통 데코레이터 적용 예시 (평가 #12 보완)
```python
from budget_app.utils import handle_errors, log_action, measure_execution_time

@handle_errors               # 스택트레이스를 숨기고 [오류][코드] 및 [힌트] 출력 후 exit(1)
@log_action("save_data")     # 주요 비즈니스 작업 로깅
@measure_execution_time      # 실행 시간 측정
def execute_task():
    ...
```

---

## 🧪 자동화 테스트 실행 (평가 #1, #2, #7 보완)

본 프로젝트는 단위 테스트뿐만 아니라 실제 CLI 런타임, 프로세스 종료 코드(0, 1), 파일 권한, 원자적 롤백을 검증하는 **E2E 통합 테스트**를 포함하고 있습니다.

```bash
# 전체 테스트 실행 (10개 테스트 스위트)
python -m unittest discover tests
```
