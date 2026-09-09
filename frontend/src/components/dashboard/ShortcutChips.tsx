// SCR-07(입출금)/SCR-08(알림 설정)이 아직 구현되지 않아 비활성 상태로만 배치한다
// (05-deposit-withdraw, 04-settings 완료 후 라우팅 연결).
export function ShortcutChips() {
  return (
    <div className="dashboard-card dashboard-shortcut-chips">
      <button className="dashboard-chip-button" disabled title="추후 연동">
        입출금 바로가기
      </button>
      <button className="dashboard-chip-button" disabled title="추후 연동">
        알림 설정 바로가기
      </button>
    </div>
  );
}
