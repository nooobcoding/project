// backend/app/schemas/notifications.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export type NotificationType = "signal" | "exit" | "error";

export interface Notification {
  id: number;
  type: NotificationType;
  message: string;
  coin_symbol: string | null;
  is_read: boolean;
  created_at: string;
}
