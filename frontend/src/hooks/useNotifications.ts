import { useCallback, useEffect, useState } from "react";
import { getNotifications, markNotificationRead } from "../api/notifications";
import type { Notification } from "../types/notifications";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 15000;

// GNB 알림 아이콘 배지/드롭다운용 — Gnb.tsx 한 곳에서만 호출해 폴링이 중복되지 않게 한다
// (00-overview.md 6장 원칙 3 — 알림은 DB에 영속화되고 미확인 배지로 표시한다).
export function useNotifications() {
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

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  return { notifications, unreadCount, markRead, refresh };
}
