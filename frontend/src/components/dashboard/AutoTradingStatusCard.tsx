// 07-auto-trading 완료 전까지 항상 빈 상태(OFF)로 표시한다 (02-dashboard.md 2-B).
// 07 완료 후 슬롯 목록 API가 생기면 여기서 조회해 상태 카드로 교체하고,
// 클릭 시 SCR-04로 이동하는 인터랙션도 그때 함께 연결한다.
export function AutoTradingStatusCard() {
  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">자동매매 상태</p>
      <p className="dashboard-empty-text">운용 중인 자동매매 없음</p>
    </div>
  );
}
