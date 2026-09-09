import { apiFetch } from "./client";
import type { Transaction, TransactionListResponse, TransactionType, WalletBalance } from "../types/wallet";

export function getWalletBalance(token: string): Promise<WalletBalance> {
  return apiFetch<WalletBalance>("/api/wallet/balance", { token });
}

export function depositWallet(token: string, amount: string, memo: string | null): Promise<Transaction> {
  return apiFetch<Transaction>("/api/wallet/deposit", {
    method: "POST",
    token,
    body: JSON.stringify({ amount, memo }),
  });
}

export function withdrawWallet(token: string, amount: string, memo: string | null): Promise<Transaction> {
  return apiFetch<Transaction>("/api/wallet/withdraw", {
    method: "POST",
    token,
    body: JSON.stringify({ amount, memo }),
  });
}

interface TransactionQuery {
  type: TransactionType | null;
  start: string | null;
  end: string | null;
  page: number;
  pageSize: number;
}

export function getTransactions(token: string, query: TransactionQuery): Promise<TransactionListResponse> {
  const params = new URLSearchParams();
  if (query.type) params.set("type", query.type);
  if (query.start) params.set("start", query.start);
  if (query.end) params.set("end", query.end);
  params.set("page", String(query.page));
  params.set("page_size", String(query.pageSize));
  return apiFetch<TransactionListResponse>(`/api/wallet/transactions?${params.toString()}`, { token });
}
