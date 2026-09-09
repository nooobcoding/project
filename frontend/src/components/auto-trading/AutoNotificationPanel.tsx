import type { Notification } from "../../types/notifications";

interface AutoNotificationPanelProps {
  notifications: Notification[];
  onMarkRead: (id: number) => void;
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

// 07-auto-trading.md 3-C "최근 알림 카드 — 매수신호(녹색)/익절체결(파랑)/손절체결(빨강)".
// Notification.type은 signal/exit/error 3종뿐이라 익절·손절을 구분하는 필드가 없다 — 대신
// services/matcher.py _build_fill_message가 항상 "실현손익 +N원"/"실현손익 -N원" 형태로
// 부호를 포함해 적으므로 그 부호로 구분한다. 메시지 문구가 바뀌면 이 파싱도 함께 깨지니,
// 더 견고하게 하려면 notifications에 손익 부호를 별도 컬럼으로 저장하는 스키마 확장이 필요하다
// (지금은 이번 스텝 범위 밖으로 남긴다).
function colorClassFor(notification: Notification): string {
  if (notification.type === "signal") return "is-buy-signal";
  if (notification.type === "error") return "is-error";
  return notification.message.includes("실현손익 +") ? "is-take-profit" : "is-stop-loss";
}

export function AutoNotificationPanel({ notifications, onMarkRead }: AutoNotificationPanelProps) {
  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">알림 센터</p>
      {notifications.length === 0 ? (
        <p className="dashboard-empty-text">알림이 없습니다.</p>
      ) : (
        <ul className="auto-notification-list">
          {notifications.map((notification) => (
            <li
              key={notification.id}
              className={`auto-notification-item ${colorClassFor(notification)} ${
                notification.is_read ? "" : "is-unread"
              }`}
              onClick={() => onMarkRead(notification.id)}
            >
              <p className="auto-notification-message">{notification.message}</p>
              <span className="auto-notification-time">{formatTime(notification.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
