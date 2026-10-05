import { Navigate, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

const ADMIN_TABS = [
  { label: "유저", path: "/admin/users" },
  { label: "시스템", path: "/admin/system" },
  { label: "감사 로그", path: "/admin/audit-logs" },
];

// 확장판 05-admin.md 2.3절 — /admin 이하 가드. ProtectedRoute 안쪽에 둔다(로그인은 거기서 본다).
// **편의일 뿐 보안 경계가 아니다.** 모든 관리자 API는 서버가 require_admin으로 다시 검사한다.
export function AdminRoute() {
  const { role } = useAuth();

  // 계정 조회 중 — 여기서 "관리자 아님"으로 단정하면 새로고침할 때마다 대시보드로 튕긴다.
  if (role === null) {
    return <p className="admin-loading">불러오는 중...</p>;
  }
  if (role !== "admin") {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="admin-page">
      <nav className="admin-tabs">
        {ADMIN_TABS.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) => (isActive ? "dashboard-chip-button is-active" : "dashboard-chip-button")}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
