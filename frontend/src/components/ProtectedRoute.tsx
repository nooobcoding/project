import { Navigate, Outlet } from "react-router-dom";
import { Gnb } from "./Gnb";
import { useAuth } from "../hooks/useAuth";

// 로그인 화면(SCR-01)은 이 레이아웃 밖에 있으므로, GNB는 인증된 화면에서만 렌더링된다.
// 즉 "비로그인 상태에서 보호된 메뉴 클릭 시 로그인 모달"(00-overview.md 6장 원칙 6)은
// 이 라우팅 구조상 발생할 수 없는 경로다 — 비로그인 사용자는 GNB 자체를 볼 수 없다.
export function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return (
    <div className="app-shell">
      <Gnb />
      <Outlet />
    </div>
  );
}
