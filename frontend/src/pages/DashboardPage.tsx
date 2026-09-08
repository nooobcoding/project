import { useAuth } from "../hooks/useAuth";

// 로드맵 2번(대시보드)에서 실제 화면으로 대체될 임시 셸.
// 지금은 인증 흐름(01-auth) 검증용 목적지 역할만 한다.
export function DashboardPage() {
  const { logout } = useAuth();

  return (
    <div className="page-shell">
      <h1>대시보드</h1>
      <p>로그인에 성공했습니다.</p>
      <button className="auth-button" onClick={logout}>
        로그아웃
      </button>
    </div>
  );
}
