import type { Transaction, TransactionType } from "../../types/wallet";

interface WalletTransactionHistoryPanelProps {
  items: Transaction[];
  total: number;
  page: number;
  pageSize: number;
  typeFilter: TransactionType | null;
  startDate: string;
  endDate: string;
  onTypeFilterChange: (type: TransactionType | null) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onPageChange: (page: number) => void;
}

const TYPE_LABEL: Record<TransactionType, string> = {
  deposit: "입금",
  withdraw: "출금",
};

// 05-deposit-withdraw.md 2-B — 유형 필터 칩 / 날짜 범위 / 내역 테이블 / 10건 페이지네이션.
export function WalletTransactionHistoryPanel({
  items,
  total,
  page,
  pageSize,
  typeFilter,
  startDate,
  endDate,
  onTypeFilterChange,
  onStartDateChange,
  onEndDateChange,
  onPageChange,
}: WalletTransactionHistoryPanelProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <section className="wallet-panel wallet-history-panel">
      <div className="wallet-history-filters">
        <div className="wallet-filter-chip-row">
          <button
            type="button"
            className={typeFilter === null ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => onTypeFilterChange(null)}
          >
            전체
          </button>
          <button
            type="button"
            className={
              typeFilter === "deposit" ? "dashboard-chip-button is-active" : "dashboard-chip-button"
            }
            onClick={() => onTypeFilterChange("deposit")}
          >
            입금
          </button>
          <button
            type="button"
            className={
              typeFilter === "withdraw" ? "dashboard-chip-button is-active" : "dashboard-chip-button"
            }
            onClick={() => onTypeFilterChange("withdraw")}
          >
            출금
          </button>
        </div>
        <div className="wallet-date-range-row">
          <input
            type="date"
            className="wallet-date-input"
            value={startDate}
            onChange={(event) => onStartDateChange(event.target.value)}
          />
          <span>~</span>
          <input
            type="date"
            className="wallet-date-input"
            value={endDate}
            onChange={(event) => onEndDateChange(event.target.value)}
          />
        </div>
      </div>

      {items.length === 0 ? (
        <p className="dashboard-empty-text">입출금 내역이 없습니다.</p>
      ) : (
        <ul className="wallet-history-list">
          <li className="wallet-history-item wallet-history-header">
            <span>유형</span>
            <span>금액</span>
            <span>처리 후 잔고</span>
            <span>메모</span>
            <span>일시</span>
          </li>
          {items.map((item) => (
            <li key={item.id} className="wallet-history-item">
              <span
                className={
                  item.type === "deposit" ? "wallet-type-badge is-deposit" : "wallet-type-badge is-withdraw"
                }
              >
                {TYPE_LABEL[item.type]}
              </span>
              <span className={item.type === "deposit" ? "is-positive" : "is-negative"}>
                {item.type === "deposit" ? "+" : "-"}
                {Math.round(Number(item.amount)).toLocaleString("ko-KR")}원
              </span>
              <span>{Math.round(Number(item.balance_after)).toLocaleString("ko-KR")}원</span>
              <span className="wallet-history-memo">{item.memo ?? "-"}</span>
              <span className="trade-history-time">{new Date(item.created_at).toLocaleString("ko-KR")}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="wallet-pagination">
        <button
          type="button"
          className="dashboard-chip-button"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          이전
        </button>
        <span className="wallet-pagination-label">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          className="dashboard-chip-button"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          다음
        </button>
      </div>
    </section>
  );
}
