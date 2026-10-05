import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { deactivateSlot, getUser, setUserStatus } from "../../api/admin";
import { ApiError } from "../../api/client";
import { ConfirmModal } from "../../components/admin/ConfirmModal";
import { STATUS_LABEL, STRATEGY_LABEL, formatDateTime, formatKrw } from "../../components/admin/format";
import { Toast } from "../../components/Toast";
import { useAuth } from "../../hooks/useAuth";
import type { AdminUserDetail } from "../../types/admin";
import type { Order } from "../../types/orders";
import type { StrategySlot } from "../../types/strategySlots";

const ORDER_STATUS_LABEL: Record<string, string> = { pending: "미체결", filled: "체결", canceled: "취소" };
const ORDER_TYPE_LABEL: Record<string, string> = { limit: "지정가", market: "시장가", reserved: "예약가" };

type PendingAction = { kind: "suspend" } | { kind: "unsuspend" } | { kind: "slot-off"; slot: StrategySlot };

// SCR-09 관리자 — 유저 상세 (확장판 05-admin.md 3-A·3-B·3-C).
export function AdminUserDetailPage() {
  const { token } = useAuth();
  const userId = Number(useParams().userId);
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !Number.isInteger(userId)) return;
    try {
      setDetail(await getUser(token, userId));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "유저 정보를 불러오지 못했습니다.");
    }
  }, [token, userId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <section className="wallet-panel">
        <p className="auth-error-message">{error}</p>
        <Link to="/admin/users" className="admin-link">
          ← 유저 목록
        </Link>
      </section>
    );
  }
  if (!detail) {
    return <p className="admin-loading">불러오는 중...</p>;
  }

  const activeSlots = detail.slots.filter((slot) => slot.is_active);
  const isAdminTarget = detail.role === "admin";

  const handleConfirm = async () => {
    if (!token || !pending) return;
    if (pending.kind === "slot-off") {
      await deactivateSlot(token, pending.slot.id);
      setToastMessage(`${pending.slot.coin_symbol} 슬롯을 껐습니다.`);
    } else {
      const result = await setUserStatus(token, detail.id, pending.kind === "suspend" ? "suspended" : "active");
      setToastMessage(
        pending.kind === "suspend"
          ? `계정을 정지했습니다. 슬롯 ${result.deactivated_slot_ids.length}개 OFF, 주문 ${result.canceled_order_ids.length}건 취소`
          : "정지를 해제했습니다. 슬롯은 사용자가 직접 다시 켜야 합니다.",
      );
    }
    setPending(null);
    await load();
  };

  return (
    <div className="admin-detail">
      <section className="wallet-panel">
        <Link to="/admin/users" className="admin-link">
          ← 유저 목록
        </Link>
        <div className="admin-detail-header">
          <div>
            <h2 className="admin-detail-email">
              {detail.email}
              {isAdminTarget && <span className="admin-badge is-admin">관리자</span>}
              <span className={`admin-badge is-${detail.status}`}>{STATUS_LABEL[detail.status]}</span>
            </h2>
            <p className="settings-caption">
              #{detail.id} · 가입 {formatDateTime(detail.created_at)}
            </p>
          </div>
          {isAdminTarget ? (
            <p className="settings-caption">관리자 계정은 정지할 수 없습니다. 권한 회수는 CLI로 합니다.</p>
          ) : detail.status === "active" ? (
            <button type="button" className="settings-danger-button" onClick={() => setPending({ kind: "suspend" })}>
              계정 정지
            </button>
          ) : (
            <button type="button" className="admin-primary-button" onClick={() => setPending({ kind: "unsuspend" })}>
              정지 해제
            </button>
          )}
        </div>

        <div className="admin-stat-grid">
          <Stat label="총 평가금액" value={formatKrw(detail.summary.total_valuation)} />
          <Stat label="원화 잔고" value={formatKrw(detail.summary.krw_balance)} />
          <Stat label="출금 가능액" value={formatKrw(detail.summary.withdrawable_krw)} />
          <Stat label="코인 평가액" value={formatKrw(detail.summary.coin_valuation)} />
          <Stat label="순투입원금" value={formatKrw(detail.summary.net_deposit)} />
        </div>
      </section>

      <section className="wallet-panel">
        <h3 className="admin-section-title">전략 슬롯 ({activeSlots.length}개 활성)</h3>
        {detail.slots.length === 0 ? (
          <p className="dashboard-empty-text">슬롯이 없습니다.</p>
        ) : (
          <Table head={["코인", "전략", "투자금", "상태", ""]}>
            {detail.slots.map((slot) => (
              <tr key={slot.id}>
                <td>{slot.coin_symbol}</td>
                <td>
                  {STRATEGY_LABEL[slot.strategy_type] ?? slot.strategy_type}
                  {slot.indicator ? ` · ${slot.indicator.toUpperCase()}` : ""}
                </td>
                <td className="is-numeric">{formatKrw(slot.invest_amount)}</td>
                <td>{slot.is_active ? "ON" : "OFF"}</td>
                <td className="is-numeric">
                  {slot.is_active && (
                    <button
                      type="button"
                      className="dashboard-chip-button"
                      onClick={() => setPending({ kind: "slot-off", slot })}
                    >
                      강제 OFF
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </section>

      <section className="wallet-panel">
        <h3 className="admin-section-title">보유 코인</h3>
        {detail.holdings.length === 0 ? (
          <p className="dashboard-empty-text">보유 코인이 없습니다.</p>
        ) : (
          <Table head={["코인", "수량", "평단", "평가금액", "손익률"]}>
            {detail.holdings.map((holding) => (
              <tr key={holding.coin_symbol}>
                <td>{holding.korean_name}</td>
                <td className="is-numeric">{Number(holding.quantity).toLocaleString("ko-KR")}</td>
                <td className="is-numeric">{formatKrw(holding.avg_buy_price)}</td>
                <td className="is-numeric">{formatKrw(holding.valuation)}</td>
                <td className={`is-numeric ${Number(holding.profit_pct) >= 0 ? "is-positive" : "is-negative"}`}>
                  {Number(holding.profit_pct).toFixed(2)}%
                </td>
              </tr>
            ))}
          </Table>
        )}
      </section>

      <OrderSection title="미체결 주문" orders={detail.pending_orders} empty="미체결 주문이 없습니다." />
      <OrderSection title="최근 주문" orders={detail.recent_orders} empty="주문 내역이 없습니다." />

      <section className="wallet-panel">
        <h3 className="admin-section-title">최근 입출금</h3>
        {detail.recent_transactions.length === 0 ? (
          <p className="dashboard-empty-text">입출금 내역이 없습니다.</p>
        ) : (
          <Table head={["유형", "금액", "처리 후 잔고", "메모", "일시"]}>
            {detail.recent_transactions.map((tx) => (
              <tr key={tx.id}>
                <td>{tx.type === "deposit" ? "입금" : "출금"}</td>
                <td className="is-numeric">{formatKrw(tx.amount)}</td>
                <td className="is-numeric">{formatKrw(tx.balance_after)}</td>
                <td>{tx.memo ?? "-"}</td>
                <td className="trade-history-time">{formatDateTime(tx.created_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </section>

      {pending?.kind === "suspend" && (
        <ConfirmModal title="계정 정지" confirmLabel="정지하기" danger onClose={() => setPending(null)} onConfirm={handleConfirm}>
          <p>{detail.email} 계정을 정지합니다.</p>
          <ul>
            <li>로그인과 모든 API 사용이 즉시 막힙니다 (이미 로그인한 세션 포함).</li>
            <li>활성 슬롯 {activeSlots.length}개를 OFF합니다. 보유 포지션은 그대로 남습니다.</li>
            <li>미체결 주문 {detail.pending_orders.length}건을 취소합니다.</li>
          </ul>
        </ConfirmModal>
      )}
      {pending?.kind === "unsuspend" && (
        <ConfirmModal title="정지 해제" confirmLabel="해제하기" onClose={() => setPending(null)} onConfirm={handleConfirm}>
          <p>{detail.email} 계정의 정지를 해제합니다. 꺼진 슬롯은 자동으로 다시 켜지지 않습니다.</p>
        </ConfirmModal>
      )}
      {pending?.kind === "slot-off" && (
        <ConfirmModal title="슬롯 강제 OFF" confirmLabel="끄기" danger onClose={() => setPending(null)} onConfirm={handleConfirm}>
          <p>
            {pending.slot.coin_symbol} {STRATEGY_LABEL[pending.slot.strategy_type]} 슬롯을 끕니다. 사용자가 직접 끈 것과
            같습니다 — 보유 포지션은 유지되고, 사용자가 다시 켤 수 있습니다.
          </p>
        </ConfirmModal>
      )}
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="admin-stat">
      <span className="admin-stat-label">{label}</span>
      <span className="admin-stat-value">{value}</span>
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="admin-table-scroll">
      <table className="admin-table">
        <thead>
          <tr>
            {head.map((label, index) => (
              <th key={index}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function OrderSection({ title, orders, empty }: { title: string; orders: Order[]; empty: string }) {
  return (
    <section className="wallet-panel">
      <h3 className="admin-section-title">{title}</h3>
      {orders.length === 0 ? (
        <p className="dashboard-empty-text">{empty}</p>
      ) : (
        <Table head={["코인", "구분", "유형", "가격", "수량", "상태", "출처", "일시"]}>
          {orders.map((order) => (
            <tr key={order.id}>
              <td>{order.coin_symbol}</td>
              <td className={order.side === "buy" ? "is-positive" : "is-negative"}>
                {order.side === "buy" ? "매수" : "매도"}
              </td>
              <td>{ORDER_TYPE_LABEL[order.order_type]}</td>
              <td className="is-numeric">{formatKrw(order.price)}</td>
              <td className="is-numeric">{Number(order.quantity).toLocaleString("ko-KR")}</td>
              <td>{ORDER_STATUS_LABEL[order.status]}</td>
              <td>{order.source === "auto" ? "자동" : "수동"}</td>
              <td className="trade-history-time">{formatDateTime(order.filled_at ?? order.created_at)}</td>
            </tr>
          ))}
        </Table>
      )}
    </section>
  );
}
