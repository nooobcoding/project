import { NavLink } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

interface NavItem {
  label: string;
  path: string;
  isBuilt: boolean;
}

// 00-overview.md 6장 원칙 6 — GNB는 화면마다 새로 그리지 않고 공통으로 고정한다.
// 아직 구현되지 않은 화면(04~08)은 ShortcutChips와 동일하게 비활성 링크로만 노출하고,
// 해당 로드맵 항목이 완료되면 isBuilt만 true로 바꾸면 된다.
const NAV_ITEMS: NavItem[] = [
  { label: "대시보드", path: "/dashboard", isBuilt: true },
  { label: "수동매매", path: "/trade", isBuilt: true },
  { label: "자동매매", path: "/auto", isBuilt: false },
  { label: "백테스팅", path: "/backtest", isBuilt: false },
  { label: "포트폴리오", path: "/portfolio", isBuilt: false },
  { label: "입출금", path: "/deposit-withdraw", isBuilt: false },
];

export function Gnb() {
  const { logout } = useAuth();

  return (
    <header className="gnb">
      <span className="gnb-logo">코인 자동매매</span>
      <nav className="gnb-nav">
        {NAV_ITEMS.map((item) =>
          item.isBuilt ? (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) => (isActive ? "gnb-link is-active" : "gnb-link")}
            >
              {item.label}
            </NavLink>
          ) : (
            <span key={item.path} className="gnb-link is-disabled" title="추후 연동">
              {item.label}
            </span>
          ),
        )}
      </nav>
      <div className="gnb-actions">
        {/* 04-settings 미구현이라 알림 목록/배지 카운트는 연결하지 않는다.
            아이콘만 앞당겨 배치하고, 04 완료 후 미확인 배지(01-erd.md notifications.is_read)를 연결한다. */}
        <button className="gnb-icon-button" disabled title="추후 연동(알림 설정 완료 후)">
          🔔
        </button>
        <span
          className="gnb-link is-disabled"
          title="추후 연동"
          role="link"
          aria-disabled="true"
        >
          설정
        </span>
        <button className="gnb-logout-button" onClick={logout}>
          로그아웃
        </button>
      </div>
    </header>
  );
}
