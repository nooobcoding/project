# 04. 공통 설정

**상태**: 구현중 (코드 작성 완료, 로컬 DB 마이그레이션·수동 검증 대기)
**화면 ID**: SCR-08
**의존성**: `01-auth`
**연관 문서**: [00-overview.md](../00-overview.md) 6장 원칙 2(실 API 키 연동 없음), 3(알림 영속화)

---

## 1. 목적

v1.0의 Upbit API 키 등록 섹션은 제거되었다 (Paper Trading 서비스에 실거래소 인증 키가 불필요 — 00-overview 6장 참조). 대신 계정 관리 + 알림 설정 2개 섹션으로 구성한다.

레이아웃: 2컬럼 — 좌: 계정 설정 / 우: 알림 설정

---

## 2. 화면 구성

### 2-A. 좌측 — 계정 설정

| 컴포넌트 | 유형 | 설명 |
|---|---|---|
| 가입 이메일 표시 | Text (read-only) | 현재 로그인 계정 이메일 |
| 비밀번호 변경 폼 | Input×3 (현재/새/확인) | 새 비밀번호는 회원가입과 동일 조건(8자+영문+숫자) |
| 회원 탈퇴 버튼 | Button (danger) + Modal | "탈퇴 시 모든 자산·거래 내역이 삭제되며 복구할 수 없습니다" 확인 후 처리 |

### 2-B. 우측 — 알림 설정

| 컴포넌트 | 유형 | 설명 |
|---|---|---|
| 매매 신호 발생 토글 | Toggle Switch | 기본 ON |
| 손절·익절 체결 토글 | Toggle Switch | 기본 ON |
| 오류 발생 토글 | Toggle Switch | 기본 **ON** (변경 — 07의 "잔고 부족으로 매수 스킵" 알림이 이 타입이라 기본 OFF면 자동매매 중단을 사용자가 놓친다) |
| 브라우저 알림 권한 버튼 | Button (small) | 미허용 시에만 노출, 허용되면 숨김 |
| 안내 문구 | Caption | "브라우저 푸시는 접속 중 즉시 알림, 알림 센터는 미확인 내역 누적 확인용입니다" (00-overview 원칙 3 반영) |

---

## 3. 인터랙션 / 오류 처리

| 위치 | 이벤트 | 처리 | 결과 |
|---|---|---|---|
| 비밀번호 변경 저장 | Click | 현재 비밀번호 검증 → 변경 API 호출 | 성공 토스트 / 실패: "현재 비밀번호가 올바르지 않습니다" |
| 회원 탈퇴 확인 | Click | 계정 및 연관 데이터 삭제 → 로그아웃 → SCR-01 이동 | - |
| 알림 토글 | Toggle | 즉시 저장 API 호출 | 실패 시 토글 원상 복구 |
| 브라우저 알림 권한 버튼 | Click | Notification API 권한 요청 | 허용: 버튼 숨김 / 거부: 안내 문구 |

---

## 4. 데이터 모델

> 전체 스키마의 기준은 [01-erd.md](../01-erd.md)다. 아래는 이 기능 관점의 발췌.

```
notification_settings
  user_id (PK, FK)
  signal_enabled     boolean default true
  exit_enabled       boolean default true
  error_enabled      boolean default true   -- 변경: false → true (01-erd.md 참조)

notifications
  id (PK)
  user_id (FK)
  type               -- signal | exit | error
  message
  coin_symbol        nullable
  strategy_slot_id   nullable  -- FK, 07에서 어느 슬롯이 발생시켰는지 기록
  is_read            boolean default false
  created_at
```

`notifications`는 GNB 알림 아이콘의 미확인 배지 카운트(00-overview 원칙 3)에 쓰이며, 07(자동매매) 구현 시 실제 이벤트가 여기 적재된다.

---

## 5. API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/account` | 가입 이메일 조회 (2-A 표시용, 초안 이후 추가) |
| PATCH | `/api/account/password` | 비밀번호 변경 |
| DELETE | `/api/account` | 회원 탈퇴 |
| GET | `/api/settings/notifications` | 알림 설정 조회 |
| PATCH | `/api/settings/notifications` | 알림 설정 변경 |
| GET | `/api/notifications?unread=true` | 알림 목록/미확인 카운트 |
| PATCH | `/api/notifications/{id}/read` | 읽음 처리 |

---

## 6. 관련 요구사항 매핑

| FR ID | 내용 |
|---|---|
| FR-S01 (재정의) | 계정 설정 — 비밀번호 변경, 회원 탈퇴 (기존 API 키 설정 내용 삭제) |
| FR-S02 | 알림 설정 — 이벤트별 개별 ON/OFF |
