import { useNavigate } from "react-router-dom";

// 02-dashboard.md — 자주 쓰는 화면 바로가기. SCR-07(입출금)/SCR-08(설정) 구현 완료로 활성화.
export function ShortcutChips() {
  const navigate = useNavigate();

  return (
    <div className="dashboard-card dashboard-shortcut-chips">
      <button className="dashboard-chip-button" onClick={() => navigate("/deposit-withdraw")}>
        입출금 바로가기
      </button>
      <button className="dashboard-chip-button" onClick={() => navigate("/settings")}>
        알림 설정 바로가기
      </button>
    </div>
  );
}
