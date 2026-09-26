# 💰 나만의 용돈 기입장 (Budget App)

> 파일 입출력 기반의 안전하고 유지보수 가능한 파이썬 콘솔 가계부 애플리케이션입니다.  
> 외부 라이브러리 의존성 없이 **파이썬 표준 라이브러리(3.10+)**만으로 작성되었으며, 대용량 파일 처리를 위한 **제너레이터 스트리밍**, **원자적 파일 교체(Atomic Replace)**, **데코레이터 기반 공통 관심사 분리**가 적용되어 있습니다.

---

## 📌 주요 특징 및 설계

1. **계층형 아키텍처 (Layered Architecture)**
   - `models.py`: dataclass 기반 데이터 규격 (Transaction, Category, Budget)
   - `storage.py`: JSONL 파일 I/O 및 `yield` 기반 스트리밍 처리, `os.replace`를 통한 안전한 파일 원자적 교체
   - `repository.py`: 도메인별 영구 저장 및 검색 CRUD 계층
   - `service.py`: 비즈니스 로직, 통계 요약, 유효성 검증 계층
   - `cli.py`: argparse 기반 CLI 파서 및 대화형 입출력
   - `utils.py`: 스택트레이스 차단 및 친절한 힌트 제공 데코레이터(`@handle_errors`), 시간 측정 데코레이터
2. **대용량 파일 스트리밍 (`yield`)**
   - 파일 전체를 한 번에 메모리에 올리지 않고, 파일 끝에서부터 버퍼 단위로 역방향 탐색하여 최신순으로 한 줄씩 스트리밍 처리합니다.
3. **견고한 예외 처리**
   - 사용자의 잘못된 입력 시 빨간색 스택트레이스(Traceback)를 숨기고 `[오류] 원인`과 `[힌트] 해결책`을 명확히 안내하며 비정상 종료 코드(exit code != 0)를 반환합니다.
4. **참조 무결성 보장**
   - 거래 내역에서 사용 중인 카테고리를 삭제할 때, 삭제를 차단하거나 대체 카테고리(`--replace`)를 지정하여 일괄 변경 후 안전하게 삭제합니다.

---

## 📂 저장 파일 위치 및 형식

모든 데이터는 `--data-dir` (기본값: `./data`) 디렉터리에 3개 이상의 독립된 파일로 분리되어 영구 저장됩니다.

| 파일명 | 형식 | 설명 |
|:---|:---:|:---|
| `data/transactions.jsonl` | JSONL | 개별 거래 내역 (id, type, date, amount, category, memo, tags) |
| `data/categories.jsonl` | JSONL | 등록된 카테고리 목록 (name) |
| `data/budgets.jsonl` | JSONL | 월별 예산 설정 정보 (month, amount) |

---

## 🛠️ 주요 명령어 및 사용 예시

모든 명령어는 리눅스 표준 옵션(`--`)을 따르며, `--help`로 상세 안내를 확인할 수 있습니다.

```bash
# 전체 도움말 확인
python -m budget_app --help
```

### 1. 거래 추가 (`add`)
대화형(interactive) 인터페이스로 값을 순차적으로 입력받습니다.
```bash
python -m budget_app add
```
*입력 예시:*
```text
새로운 거래를 등록합니다. 정보를 순차적으로 입력해주세요.
날짜(YYYY-MM-DD): 2024-01-15
타입(income/expense): expense
카테고리: food
금액(양수): 15000
메모(선택): 점심
태그(쉼표로 구분, 없으면 엔터): meal
[저장 완료] id=TX-000001
```

### 2. 거래 목록 조회 (`list`)
최신순으로 스트리밍 조회하며, `--limit` 옵션으로 출력 개수를 제한할 수 있습니다.
```bash
python -m budget_app list --limit 5
```

### 3. 거래 검색 (`search`)
기간, 카테고리, 타입, 메모 검색어, 태그 조건으로 필터링합니다.
```bash
# 특정 기간 및 카테고리 검색
python -m budget_app search --from 2024-01-01 --to 2024-01-31 --category food

# 지출(expense) 중 태그 검색
python -m budget_app search --type expense --tag meal

# 메모 키워드 검색
python -m budget_app search -q 점심
```

### 4. 월별 요약 및 예산 대비 통계 (`summary`)
총 수입, 총 지출, 잔액, 지출 상위 TOP N 카테고리 및 예산 사용률을 확인합니다.
```bash
python -m budget_app summary --month 2024-01 --top 3
```
*출력 예시:*
```text
총 수입: 3000000원
총 지출: 215000원
잔액: 2785000원
예산: 500000원 (사용률 43.0%)

지출 TOP 3
1) rent 150000원
2) food 45000원
3) transport 20000원
```

### 5. 예산 설정 및 조회 (`budget`)
```bash
# 2024년 1월 예산 50만원 설정
python -m budget_app budget set --month 2024-01 --amount 500000

# 예산 조회
python -m budget_app budget get --month 2024-01
```

### 6. 카테고리 관리 (`category`)
```bash
# 카테고리 목록 확인
python -m budget_app category list

# 카테고리 추가
python -m budget_app category add shopping

# 카테고리 삭제 (사용 중인 거래가 있을 시 대체 카테고리 지정)
python -m budget_app category remove food --replace shopping
```

### 7. 거래 수정 (`update`) 및 삭제 (`delete`)
```bash
# 거래 금액 및 메모 수정
python -m budget_app update --id TX-000001 --amount 18000 --memo "점심(식사)"

# 거래 삭제
python -m budget_app delete --id TX-000001
```

### 8. 데이터 내보내기/가져오기 (`export` / `import`)
```bash
# 특정 월 거래 내역을 CSV로 내보내기
python -m budget_app export --out export.csv --month 2024-01

# 기간 조건으로 내보내기
python -m budget_app export --out export.csv --from 2024-01-01 --to 2024-01-15

# CSV 파일에서 거래 일괄 등록
python -m budget_app import --from import.csv
```

### 9. 데이터 백업 (`backup`)
```bash
python -m budget_app backup
```

---

## 📋 CSV Import / Export 스키마

CSV 파일은 **UTF-8 인코딩**이어야 하며 첫 번째 행에 다음 헤더가 포함되어야 합니다.

| 컬럼명 (column) | 필수 여부 (required) | 설명 | 예시 |
|:---|:---:|:---|:---|
| `date` | Y | 거래 날짜 (YYYY-MM-DD) | 2024-01-15 |
| `type` | Y | 수입/지출 (`income` 또는 `expense`) | expense |
| `category` | Y | 등록된 카테고리명 | food |
| `amount` | Y | 금액 (0보다 큰 양의 정수) | 15000 |
| `memo` | N | 비고/메모 문자열 | 점심 식사 |
| `tags` | N | 태그 (쉼표 `,`로 구분) | meal,lunch |

---

## 🧪 테스트 실행

파이썬 내장 `unittest` 프레임워크를 통해 모든 검증 로직 및 비즈니스 규칙을 자동으로 테스트할 수 있습니다.

```bash
python -m unittest tests/test_budget_app.py
```
