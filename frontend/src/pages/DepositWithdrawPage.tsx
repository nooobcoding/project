import { useState } from "react";
import { depositWallet, withdrawWallet } from "../api/wallet";
import { DepositWithdrawPanel } from "../components/wallet/DepositWithdrawPanel";
import { WalletTransactionHistoryPanel } from "../components/wallet/WalletTransactionHistoryPanel";
import { Toast } from "../components/Toast";
import { useAuth } from "../hooks/useAuth";
import { useWalletBalance } from "../hooks/useWalletBalance";
import { useWalletTransactions } from "../hooks/useWalletTransactions";
import type { TransactionType } from "../types/wallet";

// SCR-07 — 입출금 (docs/features/05-deposit-withdraw.md): 좌(340px) 잔고+입금출금 폼 / 우 내역 2컬럼
export function DepositWithdrawPage() {
  const { token } = useAuth();
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<TransactionType | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [page, setPage] = useState(1);

  const { balance, refresh: refreshBalance } = useWalletBalance();
  const { items, total, pageSize, refresh: refreshTransactions } = useWalletTransactions({
    type: typeFilter,
    start: startDate || null,
    end: endDate || null,
    page,
  });

  const handleSuccess = (message: string) => {
    setToastMessage(message);
    setPage(1);
    refreshBalance().catch(() => undefined);
    refreshTransactions().catch(() => undefined);
  };

  const handleDeposit = async (amount: string, memo: string | null) => {
    if (!token) return;
    await depositWallet(token, amount, memo);
  };

  const handleWithdraw = async (amount: string, memo: string | null) => {
    if (!token) return;
    await withdrawWallet(token, amount, memo);
  };

  return (
    <div className="wallet-page">
      <div className="wallet-grid">
        <DepositWithdrawPanel
          balance={balance}
          onDeposit={handleDeposit}
          onWithdraw={handleWithdraw}
          onSuccess={handleSuccess}
        />
        <WalletTransactionHistoryPanel
          items={items}
          total={total}
          page={page}
          pageSize={pageSize}
          typeFilter={typeFilter}
          startDate={startDate}
          endDate={endDate}
          onTypeFilterChange={(type) => {
            setTypeFilter(type);
            setPage(1);
          }}
          onStartDateChange={(value) => {
            setStartDate(value);
            setPage(1);
          }}
          onEndDateChange={(value) => {
            setEndDate(value);
            setPage(1);
          }}
          onPageChange={setPage}
        />
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
