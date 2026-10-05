import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listUsers } from "../../api/admin";
import { ApiError } from "../../api/client";
import { STATUS_LABEL, formatDateTime, formatKrw } from "../../components/admin/format";
import { useAuth } from "../../hooks/useAuth";
import type { AdminUserItem, UserStatus } from "../../types/admin";

const PAGE_SIZE = 20;

// SCR-09 관리자 — 유저 목록 (확장판 05-admin.md 3-A). 읽기 전용.
export function AdminUsersPage() {
  const { token } = useAuth();
  const [status, setStatus] = useState<UserStatus | null>(null);
  const [hasActiveSlots, setHasActiveSlots] = useState<boolean | null>(null);
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<AdminUserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let canceled = false;
    listUsers(token, { status, hasActiveSlots, q: submittedQuery, sort, page, pageSize: PAGE_SIZE })
      .then((result) => {
        if (canceled) return;
        setItems(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch((err) => {
        if (!canceled) setError(err instanceof ApiError ? err.message : "목록을 불러오지 못했습니다.");
      });
    return () => {
      canceled = true;
    };
  }, [token, status, hasActiveSlots, submittedQuery, sort, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const chip = (active: boolean) => (active ? "dashboard-chip-button is-active" : "dashboard-chip-button");

  return (
    <section className="wallet-panel">
      <div className="admin-filter-row">
        <div className="wallet-filter-chip-row">
          {([null, "active", "suspended"] as const).map((value) => (
            <button
              key={value ?? "all"}
              type="button"
              className={chip(status === value)}
              onClick={() => {
                setStatus(value);
                setPage(1);
              }}
            >
              {value === null ? "전체" : STATUS_LABEL[value]}
            </button>
          ))}
        </div>
        <div className="wallet-filter-chip-row">
          {([null, true, false] as const).map((value) => (
            <button
              key={String(value)}
              type="button"
              className={chip(hasActiveSlots === value)}
              onClick={() => {
                setHasActiveSlots(value);
                setPage(1);
              }}
            >
              {value === null ? "슬롯 전체" : value ? "자동매매 중" : "자동매매 없음"}
            </button>
          ))}
        </div>
        <form
          className="admin-search-form"
          onSubmit={(event) => {
            event.preventDefault();
            setSubmittedQuery(query);
            setPage(1);
          }}
        >
          <input
            className="wallet-date-input"
            placeholder="이메일 검색"
            value={query}
            maxLength={255}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            className="wallet-date-input"
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as "newest" | "oldest");
              setPage(1);
            }}
          >
            <option value="newest">최근 가입순</option>
            <option value="oldest">오래된 가입순</option>
          </select>
        </form>
      </div>

      {error && <p className="auth-error-message">{error}</p>}
      <p className="settings-caption">총 {total.toLocaleString("ko-KR")}명</p>

      {items.length === 0 ? (
        <p className="dashboard-empty-text">조건에 맞는 유저가 없습니다.</p>
      ) : (
        <div className="admin-table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>이메일</th>
                <th>상태</th>
                <th>가입일</th>
                <th className="is-numeric">활성 슬롯</th>
                <th className="is-numeric">원화 잔고</th>
                <th className="is-numeric">총 평가금액</th>
              </tr>
            </thead>
            <tbody>
              {items.map((user) => (
                <tr key={user.id}>
                  <td>
                    <Link to={`/admin/users/${user.id}`} className="admin-link">
                      {user.email}
                    </Link>
                    {user.role === "admin" && <span className="admin-badge is-admin">관리자</span>}
                  </td>
                  <td>
                    <span className={`admin-badge is-${user.status}`}>{STATUS_LABEL[user.status]}</span>
                  </td>
                  <td className="trade-history-time">{formatDateTime(user.created_at)}</td>
                  <td className="is-numeric">{user.active_slot_count}</td>
                  <td className="is-numeric">{formatKrw(user.krw_balance)}</td>
                  <td className="is-numeric">{formatKrw(user.total_valuation)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="wallet-pagination">
        <button type="button" className="dashboard-chip-button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          이전
        </button>
        <span className="wallet-pagination-label">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          className="dashboard-chip-button"
          disabled={page >= totalPages}
          onClick={() => setPage(page + 1)}
        >
          다음
        </button>
      </div>
    </section>
  );
}
