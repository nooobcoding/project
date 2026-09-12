// backend/app/schemas/notification_settings.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export interface NotificationSettings {
  signal_enabled: boolean;
  exit_enabled: boolean;
  error_enabled: boolean;
}

export type NotificationSettingKey = keyof NotificationSettings;
