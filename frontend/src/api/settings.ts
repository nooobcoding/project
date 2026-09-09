import { apiFetch } from "./client";
import type { NotificationSettings } from "../types/settings";

export function getNotificationSettings(token: string): Promise<NotificationSettings> {
  return apiFetch<NotificationSettings>("/api/settings/notifications", { token });
}

export function updateNotificationSettings(
  token: string,
  input: Partial<NotificationSettings>,
): Promise<NotificationSettings> {
  return apiFetch<NotificationSettings>("/api/settings/notifications", {
    method: "PATCH",
    token,
    body: JSON.stringify(input),
  });
}
