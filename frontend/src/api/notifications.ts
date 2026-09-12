import { apiFetch } from "./client";
import type { Notification } from "../types/notifications";

export function getNotifications(token: string, unread = false): Promise<Notification[]> {
  return apiFetch<Notification[]>(`/api/notifications?unread=${unread}`, { token });
}

export function markNotificationRead(token: string, notificationId: number): Promise<Notification> {
  return apiFetch<Notification>(`/api/notifications/${notificationId}/read`, {
    method: "PATCH",
    token,
  });
}
