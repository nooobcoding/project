import { useCallback, useEffect, useState } from "react";
import { getTransactions } from "../api/wallet";
import type { Transaction, TransactionType } from "../types/wallet";
import { useAuth } from "./useAuth";

const PAGE_SIZE = 10;

// 서버(routers/wallet.py)와 같은 문구 — 화면이 미리 막지 못한 경우에도 같은 안내가 나가게 한다.
export const INVERTED_DATE_RANGE_MESSAGE = "종료일은 시작일 이후로 설정해주세요.";

// YYYY-MM-DD 문자열은 사전순 비교가 곧 날짜 비교다. 한쪽만 고른 경우는 역전이 아니다.
export function isDateRangeInverted(start: string | null, end: string | null): boolean {
  return !!start && !!end && end < start;
}

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
    // 뒤집힌 기간은 서버가 400으로 거부하는데, 아래 effect가 오류를 삼키므로 그대로 두면
    // **직전 조회 결과가 화면에 남아** 필터가 적용된 것처럼 보인다. 요청하지 않고 비운다 —
    // 왜 비었는지는 패널이 같은 문구로 알려준다.
    if (isDateRangeInverted(start, end)) {
      setItems([]);
      setTotal(0);
      return;
    }
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
