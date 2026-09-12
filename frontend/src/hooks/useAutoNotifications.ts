import { useCallback, useEffect, useState } from "react";
import { getNotifications, markNotificationRead } from "../api/notifications";
import type { Notification } from "../types/notifications";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 15000;

// 07-auto-trading.md 3-C "최근 알림 카드" 전용 폴링. hooks/useNotifications.ts는 GNB
// 드롭다운 배지 "한 곳에서만" 호출하도록 설계돼 있어(그 파일 주석 참고) 여기서 재사용하면
// 같은 API를 두 타이머가 중복으로 폴링하게 된다 — 그 결합을 건드리지 않고 이 페이지 전용으로
// 별도 인스턴스를 둔다 (다른 화면 훅들도 각자 자기 폴링을 갖는 것과 같은 패턴).
export function useAutoNotifications() {
  const { token } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const list = await getNotifications(token);
    setNotifications(list);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    refresh().catch(() => undefined);
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [token, refresh]);

  const markRead = useCallback(
    async (notificationId: number) => {
      if (!token) return;
      await markNotificationRead(token, notificationId);
      await refresh();
    },
    [token, refresh],
  );

  return { notifications, markRead };
}
