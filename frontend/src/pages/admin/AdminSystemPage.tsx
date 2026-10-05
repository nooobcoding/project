import { useEffect, useState } from "react";
import { getSystemOverview } from "../../api/admin";
import { ApiError } from "../../api/client";
import { formatDateTime } from "../../components/admin/format";
import { useAuth } from "../../hooks/useAuth";
import type { ShardCoverage, SystemOverview } from "../../types/admin";

const REFRESH_MS = 10_000;

// SCR-09 관리자 — 시스템 대시보드 (확장판 05-admin.md 3-D, 06-observability.md 3.4절).
export function AdminSystemPage() {
  const { token } = useAuth();
  const [overview, setOverview] = useState<SystemOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let canceled = false;
    const load = () =>
      getSystemOverview(token)
        .then((result) => {
          if (canceled) return;
          setOverview(result);
          setError(null);
        })
        .catch((err) => {
          if (!canceled) setError(err instanceof ApiError ? err.message : "시스템 상태를 불러오지 못했습니다.");
        });
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      canceled = true;
      window.clearInterval(timer);
    };
  }, [token]);

  if (!overview) {
    return error ? <p className="auth-error-message">{error}</p> : <p className="admin-loading">불러오는 중...</p>;
  }

  const staleCount = overview.heartbeats.filter((h) => h.stale).length;
  const rateLimit = overview.upbit_rate_limit;

  return (
    <div className="admin-detail">
      {/* 맨 위에 둔다 — 나머지는 "느린가"를 보지만 이건 "아예 멈췄는가"를 본다 (05 3-D) */}
      <CoverageBanner label="자동매매 워커" coverage={overview.worker_coverage} shardCount={overview.shard_count}
        consequence="이 샤드 유저들의 자동매매(손절·익절 포함)가 평가되지 않고 있습니다." />
      <CoverageBanner label="체결 엔진(matcher)" coverage={overview.matcher_coverage} shardCount={overview.shard_count}
        consequence="이 샤드 코인의 지정가 주문이 체결되지 않고 있습니다." />
      {error && <p className="auth-error-message">갱신 실패: {error} (마지막으로 받은 값을 표시 중)</p>}

      <section className="wallet-panel">
        <div className="admin-stat-grid">
          <Stat label="정상 계정" value={overview.active_users.toLocaleString("ko-KR")} />
          <Stat label="정지 계정" value={overview.suspended_users.toLocaleString("ko-KR")} />
          <Stat label="활성 슬롯" value={overview.active_slots.toLocaleString("ko-KR")} />
          <Stat label="미체결 주문" value={overview.pending_orders.toLocaleString("ko-KR")} />
          <Stat
            label="Upbit 토큰 (high / low)"
            value={
              rateLimit
                ? `${rateLimit.buckets.high.tokens} / ${rateLimit.buckets.low.tokens}`
                : "조회 실패"
            }
            note={
              rateLimit
                ? `${rateLimit.backend}${rateLimit.penalty > 1 ? ` · 429 백오프 ×${rateLimit.penalty}` : ""}`
                : undefined
            }
          />
        </div>
      </section>

      <section className="wallet-panel">
        <h3 className="admin-section-title">
          프로세스 heartbeat {staleCount > 0 && <span className="admin-badge is-suspended">멈춤 {staleCount}</span>}
        </h3>
        <p className="settings-caption">
          역할·샤드마다 가장 최근 프로세스만 보여줍니다
          {overview.superseded_heartbeat_rows > 0 &&
            ` (샤드를 넘겨준 이전 프로세스 기록 ${overview.superseded_heartbeat_rows.toLocaleString("ko-KR")}행은 숨김)`}
          . 멈춤 = 마지막 tick이 그 역할의 주기 3배를 넘었습니다 — 락을 쥔 채 아무것도 안 하는 프로세스일 수 있고,
          그런 프로세스는 샤드를 놓지 않아 여기 계속 남습니다.
        </p>
        {overview.heartbeats.length === 0 ? (
          <p className="dashboard-empty-text">기록된 heartbeat가 없습니다.</p>
        ) : (
          <div className="admin-table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>역할</th>
                  <th>샤드</th>
                  <th>프로세스</th>
                  <th>마지막 tick</th>
                  <th className="is-numeric">소요(ms)</th>
                  <th className="is-numeric">최대(ms)</th>
                  <th className="is-numeric">예산 초과</th>
                  <th className="is-numeric">처리 수</th>
                  <th className="is-numeric">커넥션</th>
                  <th className="is-numeric">오류</th>
                  <th className="is-numeric">스킵</th>
                </tr>
              </thead>
              <tbody>
                {overview.heartbeats.map((h) => (
                  <tr key={`${h.role}-${h.shard_id}-${h.process_id}`} className={h.stale ? "is-stale" : undefined}>
                    <td>{h.role}</td>
                    <td>{h.shard_id ?? "-"}</td>
                    <td className="admin-mono">{h.process_id}</td>
                    <td title={formatDateTime(h.last_tick_at)}>
                      {h.seconds_since_tick}초 전{h.stale && " · 멈춤"}
                    </td>
                    <td className="is-numeric">{h.last_duration_ms}</td>
                    <td className="is-numeric">{h.max_duration_ms}</td>
                    <td className="is-numeric">{h.over_budget_count}</td>
                    <td className="is-numeric">{h.item_count}</td>
                    <td className="is-numeric">{h.db_connections}</td>
                    <td className={`is-numeric ${h.error_count > 0 ? "is-negative" : ""}`}>{h.error_count}</td>
                    <td className="is-numeric">{h.skip_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function CoverageBanner({
  label,
  coverage,
  shardCount,
  consequence,
}: {
  label: string;
  coverage: ShardCoverage;
  shardCount: number;
  consequence: string;
}) {
  if (!coverage.applicable) {
    return <div className="admin-banner is-muted">{label}: 단일 프로세스 구성이라 샤드 점유가 없습니다.</div>;
  }
  // 조회 실패를 "정상"으로 보이면 안 된다 — 모른다고 말한다
  if (coverage.missing === null) {
    return <div className="admin-banner is-warning">{label}: 샤드 점유 상태를 조회하지 못했습니다.</div>;
  }
  if (coverage.missing.length === 0) {
    return <div className="admin-banner is-ok">{label}: 샤드 {shardCount}개 모두 점유됨</div>;
  }
  return (
    <div className="admin-banner is-danger">
      <strong>
        {label}: 샤드 {coverage.missing.length}/{shardCount}개 미점유 ({coverage.missing.join(", ")})
      </strong>
      <span>{consequence}</span>
      {/* 화면은 지금 이 순간의 점유를 그대로 보여준다. 재기동 직후 샤드를 다시 잡기 전까지는 실제로
          비어 있어서 잠깐 뜰 수 있다 — 서버 경고 로그는 같은 이유로 3주기 연속일 때만 남긴다. */}
      <span className="admin-stat-label">
        방금 재기동했다면 샤드를 다시 잡는 중일 수 있습니다. 1분 뒤에도 남아 있으면 문제입니다.
      </span>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="admin-stat">
      <span className="admin-stat-label">{label}</span>
      <span className="admin-stat-value">{value}</span>
      {note && <span className="admin-stat-label">{note}</span>}
    </div>
  );
}
