// 관리자 화면 공용 표시 규칙.

export function formatKrw(value: string | number): string {
  return `${Math.round(Number(value)).toLocaleString("ko-KR")}원`;
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("ko-KR");
}

export const STATUS_LABEL: Record<string, string> = {
  active: "정상",
  suspended: "정지",
};

export const STRATEGY_LABEL: Record<string, string> = {
  trend: "추세추종",
  counter_trend: "역추세",
  grid: "그리드",
  dca: "분할매수",
};

export const ACTION_LABEL: Record<string, string> = {
  "user.suspend": "계정 정지",
  "user.unsuspend": "정지 해제",
  "slot.deactivate": "슬롯 강제 OFF",
  "role.grant": "관리자 권한 부여",
  "role.revoke": "관리자 권한 회수",
};
