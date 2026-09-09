import { useEffect, useRef, useState } from "react";
import { useNotifications } from "../hooks/useNotifications";

const TYPE_LABEL: Record<string, string> = {
  signal: "매매 신호",
  exit: "손절·익절",
  error: "오류",
};

function formatTime(iso: string): string {
  const date = new Date(iso);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

// 04-settings.md 2-B, 00-overview.md 6장 원칙 3 — GNB 알림 아이콘: 미확인 배지 + 알림 센터 드롭다운
export function NotificationBell() {
  const { notifications, unreadCount, markRead } = useNotifications();
  const [isOpen, setIsOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const handleItemClick = (id: number, isRead: boolean) => {
    if (!isRead) {
      markRead(id).catch(() => undefined);
    }
  };

  return (
    <div className="gnb-notification-wrap" ref={wrapRef}>
      <button
        className="gnb-icon-button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label="알림"
      >
        🔔
        {unreadCount > 0 && (
          <span className="gnb-notification-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
        )}
      </button>
      {isOpen && (
        <div className="gnb-notification-dropdown">
          {notifications.length === 0 ? (
            <p className="gnb-notification-empty">알림이 없습니다.</p>
          ) : (
            notifications.map((notification) => (
              <button
                key={notification.id}
                type="button"
                className={
                  notification.is_read
                    ? "gnb-notification-item"
                    : "gnb-notification-item is-unread"
                }
                onClick={() => handleItemClick(notification.id, notification.is_read)}
              >
                {TYPE_LABEL[notification.type] ?? notification.type} — {notification.message}
                <span className="gnb-notification-time">{formatTime(notification.created_at)}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
