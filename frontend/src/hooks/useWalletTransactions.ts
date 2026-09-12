import { useCallback, useEffect, useState } from "react";
import { getTransactions } from "../api/wallet";
import type { Transaction, TransactionType } from "../types/wallet";
import { useAuth } from "./useAuth";

const PAGE_SIZE = 10;

interface UseWalletTransactionsOptions {
  type: TransactionType | null;
  start: string | null;
  end: string | null;
  page: number;
}

// 05-deposit-withdraw 입출금 내역 — 유형/날짜 필터·페이지네이션 조회 전용(제출 없음).
export function useWalletTransactions({ type, start, end, page }: UseWalletTransactionsOptions) {
  const { token } = useAuth();
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const result = await getTransactions(token, { type, start, end, page, pageSize: PAGE_SIZE });
    setItems(result.items);
    setTotal(result.total);
  }, [token, type, start, end, page]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token, refresh]);

  return { items, total, pageSize: PAGE_SIZE, isLoading, refresh };
}
