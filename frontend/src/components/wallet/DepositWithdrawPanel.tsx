import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { NumberInput } from "../NumberInput";
import type { WalletBalance } from "../../types/wallet";

// 05-deposit-withdraw.md 2-A — +10만/50만/100만/300만/500만/1,000만원, 클릭 시 누적
const QUICK_AMOUNTS = [100000, 500000, 1000000, 3000000, 5000000, 10000000];

type WalletTabType = "deposit" | "withdraw";

interface DepositWithdrawPanelProps {
  balance: WalletBalance | null;
  onDeposit: (amount: string, memo: string | null) => Promise<void>;
  onWithdraw: (amount: string, memo: string | null) => Promise<void>;
  onSuccess: (message: string) => void;
}

export function DepositWithdrawPanel({
  balance,
  onDeposit,
  onWithdraw,
  onSuccess,
}: DepositWithdrawPanelProps) {
  const [type, setType] = useState<WalletTabType>("deposit");
  const [amount, setAmount] = useState("");
  const [memo, setMemo] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setAmount("");
    setMemo("");
    setError(undefined);
  }, [type]);

  const krwBalance = balance ? Number(balance.krw_balance) : 0;
  const withdrawableKrw = balance ? Number(balance.withdrawable_krw) : 0;
  const parsedAmount = Number(amount || "0");
  const previewBalance = type === "deposit" ? krwBalance + parsedAmount : krwBalance - parsedAmount;

  const handleQuickAdd = (value: number) => {
    setAmount(String(Number(amount || "0") + value));
  };

  const isSubmitDisabled =
    isSubmitting || parsedAmount <= 0 || (type === "withdraw" && parsedAmount > withdrawableKrw);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitDisabled) return;

    setIsSubmitting(true);
    setError(undefined);
    try {
      const trimmedMemo = memo.trim() ? memo.trim() : null;
      if (type === "deposit") {
        await onDeposit(amount, trimmedMemo);
        onSuccess("입금이 완료되었습니다.");
      } else {
        await onWithdraw(amount, trimmedMemo);
        onSuccess("출금이 완료되었습니다.");
      }
      setAmount("");
      setMemo("");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="wallet-panel">
      <div className="wallet-balance-card">
        <p className="dashboard-card-label">가상 원화 잔고</p>
        <p className="wallet-balance-amount">{Math.round(krwBalance).toLocaleString("ko-KR")}원</p>
      </div>

      <div className="wallet-tab-row">
        <button
          type="button"
          className={type === "deposit" ? "wallet-tab is-deposit is-active" : "wallet-tab is-deposit"}
          onClick={() => setType("deposit")}
        >
          입금
        </button>
        <button
          type="button"
          className={type === "withdraw" ? "wallet-tab is-withdraw is-active" : "wallet-tab is-withdraw"}
          onClick={() => setType("withdraw")}
        >
          출금
        </button>
      </div>

      <form className="wallet-form" onSubmit={handleSubmit}>
        <NumberInput label="금액" value={amount} onChange={setAmount} placeholder="금액을 입력하세요" suffix="원" />

        <div className="wallet-quick-amount-grid">
          {QUICK_AMOUNTS.map((value) => (
            <button
              type="button"
              key={value}
              className="dashboard-chip-button"
              onClick={() => handleQuickAdd(value)}
            >
              +{(value / 10000).toLocaleString("ko-KR")}만
            </button>
          ))}
        </div>

        <div className="order-field">
          <label htmlFor="wallet-memo">메모 (선택)</label>
          <input
            id="wallet-memo"
            type="text"
            className="wallet-memo-input"
            value={memo}
            onChange={(event) => setMemo(event.target.value.slice(0, 30))}
            placeholder="예: 용돈 입금"
            maxLength={30}
          />
        </div>

        <p className="wallet-preview-text">
          {type === "deposit" ? "입금" : "출금"} 후 잔고: {Math.round(krwBalance).toLocaleString("ko-KR")}
          원 → {Math.round(previewBalance).toLocaleString("ko-KR")}원
        </p>

        {type === "withdraw" && (
          <p className="wallet-warning-box">
            출금 금액이 보유 잔고를 초과할 수 없습니다. (자동매매에 배정된 금액이 있다면 이를 제외한 금액
            기준)
          </p>
        )}

        {error && <p className="auth-error-message">{error}</p>}

        <button
          type="submit"
          className={
            type === "deposit"
              ? "auth-button wallet-submit-button is-deposit"
              : "auth-button wallet-submit-button is-withdraw"
          }
          disabled={isSubmitDisabled}
        >
          {type === "deposit" ? "입금" : "출금"}
        </button>
      </form>
    </section>
  );
}
