import { useAuth } from "../../hooks/useAuth";

// SCR-02 로컬 상단바. 화면이 더 늘어나는 03~04 즈음 공용 GNB로 대체될 예정.
export function TopBar() {
  const { logout } = useAuth();

  return (
    <header className="dashboard-topbar">
      <span className="dashboard-topbar-title">코인 자동매매 프로그램</span>
      <button className="dashboard-logout-button" onClick={logout}>
        로그아웃
      </button>
    </header>
  );
}
