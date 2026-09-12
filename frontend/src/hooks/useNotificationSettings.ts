import { useCallback, useEffect, useState } from "react";
import { getNotificationSettings, updateNotificationSettings } from "../api/settings";
import type { NotificationSettingKey, NotificationSettings } from "../types/settings";
import { useAuth } from "./useAuth";

// 04-settings.md 3장 — 토글은 즉시 저장하고, 실패 시 원상 복구한다.
export function useNotificationSettings() {
  const { token } = useAuth();
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    getNotificationSettings(token)
      .then(setSettings)
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token]);

  const toggle = useCallback(
    async (key: NotificationSettingKey, value: boolean) => {
      if (!token) return;
      setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
      try {
        const updated = await updateNotificationSettings(token, { [key]: value });
        setSettings(updated);
      } catch (err) {
        setSettings((prev) => (prev ? { ...prev, [key]: !value } : prev));
        throw err;
      }
    },
    [token],
  );

  return { settings, isLoading, toggle };
}
