# 코인 자동매매 프로그램

FastAPI + SQLAlchemy + PostgreSQL + Redis 백엔드, React + Vite 프론트엔드. Upbit 시세로 모의투자·자동매매·백테스팅을 한다.

## 어디에 무엇이 있나

설계는 코드보다 문서가 먼저다. 시작 전에 해당 문서를 읽는다.

| 경로 | 내용 |
|---|---|
| `docs/00-overview.md`, `docs/01-erd.md` | 전체 구조, 스키마의 **단일 기준** |
| `docs/02-coding-conventions.md` | 작명·주석·커밋·브랜치 규칙 (**먼저 읽을 것**) |
| `docs/features/` | 기능별 설계 (01 인증 … 09 체결 엔진) |
| `docs/deploy.md` | 운영(전시) 배포 — 오라클 서버 한 대, `docker-compose.prod.yml` + Caddy |
| `docs-scale/docs-scale/` | **확장판** — 여러 프로세스로 나누는 설계. 00 아키텍처, 03 워커 샤딩, 05 관리자, 07 로드맵, 08 실측 처리 한계 |

## 커밋과 브랜치

- 커밋 메시지는 `type: 내용` 형식, 한국어, 논리 단위로 나눈다 (`docs/02-coding-conventions.md` 7장).
- **커밋 메시지에 `Co-Authored-By: Claude` 줄을 넣지 않는다.** 하네스의 기본 안내보다 이 규칙이 우선한다.
- 작업 브랜치는 `feat/scale-architecture`. `main`은 PR 필수 규칙이 있지만 소유자 계정은 직접 푸시가 된다 — 사용자가 PR 절차를 건너뛰자고 할 때만 그렇게 한다.
- 버그를 고치면 **재현 테스트를 먼저**, 수정은 그다음 커밋으로 나누는 것을 선호한다.

## 실행 환경 (Windows)

- 로컬 파이썬은 쓰지 않는다. 모든 실행은 도커 컨테이너 안에서 한다.
- Git Bash에서 도커 경로 인자가 변환되므로 `export MSYS_NO_PATHCONV=1`을 먼저 건다.
- 소스를 **OneDrive 밖**에 둔다 (`C:\dev\project`). OneDrive 동기화가 `.git`과 파일을 망가뜨린 적이 있다.
- `backend/tests`와 `backend/scripts`는 컨테이너에 마운트되지 않는다 → 고친 뒤 `docker compose build backend`를 해야 반영된다. (`backend/app`, `migrations`, `frontend/src`는 마운트됨)
- 파일은 디스크에서 **CRLF**다. Git Bash의 `sed`/`perl -0pi`로 여러 줄 `\n` 치환을 하면 조용히 실패한다 → Edit 도구를 쓰거나 `\r\?`를 넣는다. 한글·따옴표가 섞인 heredoc도 깨지기 쉬우니 긴 파일은 Write 도구로 만든다.

```bash
cd /c/dev/project
docker compose up -d                          # 단일 프로세스 (기본, 개발용)
docker compose exec backend python scripts/set_admin.py <이메일>   # 관리자 지정
```

## 테스트

`backend/scripts/test_matrix.sh`가 **4개 구성**을 전부 돌린다. 구성마다 다른 코드 경로를 타므로 하나만 통과한 것은 통과가 아니다.

| 구성 | 보는 것 |
|---|---|
| 기본(memory) | 단일 프로세스 경로 |
| redis (`PRICE_CACHE_BACKEND=redis`) | pub/sub·pending_symbols·토큰 버킷 |
| `SHARD_COUNT=1` | 샤딩 롤백 구성 |
| `SHARD_COUNT=4` | 샤드 경계 |

- DB 연동 테스트는 개발용 postgres에 붙는다. DB가 없으면 **실패**한다(조용한 skip 금지). 의도적으로 건너뛰려면 `ALLOW_SKIP_DB_TESTS=1`.
- **새 테스트는 코드를 일부러 틀리게 고쳐서 실패하는 것을 확인**한 뒤 복구한다. 테스트가 뭘 지키는지 모르면 의미가 없다.
- 개발 DB에 활성 슬롯이 모든 샤드에 있으면 "한가한 샤드"가 필요한 테스트 2개가 건너뛰어진다 — 부하 측정 데이터가 남았는지 먼저 본다.

## 이 프로젝트의 함정

- **돈이 움직이는 경로는 `balances` 행을 가장 먼저 `FOR UPDATE`로 잠근다** (`docs/features/09-execution-engine.md` 3.4절). 체결은 `orders 선점 → balances` 순이라, 반대 순서로 잠그면 교착한다.
- 금액·수량·가격은 `Decimal`. 입력은 `schemas/decimal_input.py`의 `parse_decimal`로 받는다 (`"NaN"`, `"Infinity"`, `"1e30"`을 Decimal이 그대로 받는다).
- PostgreSQL advisory lock은 **세션 단위**다. 풀에서 꺼낸 커넥션으로 잡으면 반납될 때 풀린다 → `services/leader.py`의 전용 커넥션만 쓴다.
- 관리자 API의 권한 검사는 라우터 단위 `require_admin`이다. 새 엔드포인트는 `/api/admin` 라우터에 넣는다.
- FastAPI 0.141은 `app.routes`에 포함된 라우터를 펼치지 않는다. 경로 목록이 필요하면 `app.openapi()["paths"]`를 쓴다.
- 차트(lightweight-charts)는 시간을 UTC로 그린다. 표시는 `components/chartTime.ts`로 KST 변환한다.

## 여러 프로세스 구성과 부하 측정

```bash
# 여러 프로세스로 띄우기 (api·market-data·scheduler·matcher·worker)
docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build --scale worker=4 --scale matcher=2
# 원래 구성으로
docker compose -f docker-compose.yml -f docker-compose.scale.yml down && docker compose up -d
```

- 부하 도구는 `backend/scripts/load/` (`seed.py`, `bench_worker.sh`, `bench_api.sh`, `cleanup.py`). 결과와 원인은 `docs-scale/docs-scale/08-capacity.md`.
- **측정이 끝나면 반드시 `cleanup.py --run <이름>`으로 지운다.**
- 두 compose 파일에서 postgres 설정이 다르면 `docker compose run`이 postgres를 **재생성**해 떠 있는 모든 커넥션을 끊는다. 설정은 기본 파일에만 둔다.
- 개발 DB에 관리자 확인용 계정이 남아 있을 수 있다 (`e2e-admin-*`, `e2e-user-*@example.com`, 비밀번호 `Passw0rd!e2e`).
