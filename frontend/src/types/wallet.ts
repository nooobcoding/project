// backend/app/schemas/wallet.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export type TransactionType = "deposit" | "withdraw";

export interface Transaction {
  id: number;
  type: TransactionType;
  amount: string;
  balance_after: string;
  memo: string | null;
  created_at: string;
}

export interface TransactionListResponse {
  items: Transaction[];
  total: number;
}

export interface WalletBalance {
  krw_balance: string;
  withdrawable_krw: string;
}
