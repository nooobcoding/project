import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listAuditLogs } from "../../api/admin";
import { ApiError } from "../../api/client";
import { ACTION_LABEL, formatDateTime } from "../../components/admin/format";
import { useAuth } from "../../hooks/useAuth";
import type { AuditLogItem } from "../../types/admin";

const PAGE_SIZE = 20;

// SCR-09 관리자 — 감사 로그 (확장판 05-admin.md 4장).
export function AdminAuditLogsPage() {
  const { token } = useAuth();
  const [action, setAction] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let canceled = false;
    listAuditLogs(token, { action, targetId: null, page, pageSize: PAGE_SIZE })
      .then((result) => {
        if (canceled) return;
        setItems(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch((err) => {
        if (!canceled) setError(err instanceof ApiError ? err.message : "감사 로그를 불러오지 못했습니다.");
      });
    return () => {
      canceled = true;
    };
  }, [token, action, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="wallet-panel">
      <div className="wallet-filter-chip-row">
        {[null, ...Object.keys(ACTION_LABEL)].map((value) => (
          <button
            key={value ?? "all"}
            type="button"
            className={action === value ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => {
              setAction(value);
              setPage(1);
            }}
          >
            {value === null ? "전체" : ACTION_LABEL[value]}
          </button>
        ))}
      </div>

      {error && <p className="auth-error-message">{error}</p>}

      {items.length === 0 ? (
        <p className="dashboard-empty-text">기록이 없습니다.</p>
      ) : (
        <div className="admin-table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>일시</th>
                <th>행위</th>
                <th>행위자</th>
                <th>대상</th>
                <th>내용</th>
              </tr>
            </thead>
            <tbody>
              {items.map((log) => (
                <tr key={log.id}>
                  <td className="trade-history-time">{formatDateTime(log.created_at)}</td>
                  <td>{ACTION_LABEL[log.action] ?? log.action}</td>
                  <td>{actorLabel(log)}</td>
                  <td>
                    {log.target_type === "user" ? (
                      <Link to={`/admin/users/${log.target_id}`} className="admin-link">
                        유저 #{log.target_id}
                      </Link>
                    ) : (
                      `슬롯 #${log.target_id}`
                    )}
                  </td>
                  <td className="settings-caption">{describe(log)}</td>
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

function actorLabel(log: AuditLogItem): string {
  if (log.actor_email === null) return "CLI";
  // 행위한 관리자가 탈퇴하면 id만 지워지고 이메일은 남는다
  return log.actor_user_id === null ? `${log.actor_email} (탈퇴)` : log.actor_email;
}

function describe(log: AuditLogItem): string {
  const detail = log.detail ?? {};
  const count = (key: string) => (Array.isArray(detail[key]) ? (detail[key] as unknown[]).length : 0);
  switch (log.action) {
    case "user.suspend":
      return `슬롯 ${count("deactivated_slot_ids")}개 OFF · 주문 ${count("canceled_order_ids")}건 취소`;
    case "slot.deactivate":
      return `유저 #${String(detail.user_id ?? "?")} · ${String(detail.coin_symbol ?? "")}`;
    default:
      return "";
  }
}
