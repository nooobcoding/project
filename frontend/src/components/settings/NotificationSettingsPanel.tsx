import { useEffect, useState } from "react";
import { useNotificationSettings } from "../../hooks/useNotificationSettings";
import { ToggleSwitch } from "../ToggleSwitch";

interface NotificationSettingsPanelProps {
  onToast: (message: string) => void;
}

const TOGGLE_ITEMS = [
  { key: "signal_enabled" as const, label: "매매 신호 발생" },
  { key: "exit_enabled" as const, label: "손절·익절 체결" },
  { key: "error_enabled" as const, label: "오류 발생" },
];

function getBrowserPermission(): NotificationPermission | "unsupported" {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  return Notification.permission;
}

export function NotificationSettingsPanel({ onToast }: NotificationSettingsPanelProps) {
  const { settings, isLoading, toggle } = useNotificationSettings();
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(
    getBrowserPermission,
  );

  useEffect(() => {
    setPermission(getBrowserPermission());
  }, []);

  const handleToggle = async (key: (typeof TOGGLE_ITEMS)[number]["key"], value: boolean) => {
    try {
      await toggle(key, value);
    } catch {
      onToast("설정 저장에 실패했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  const handleRequestPermission = async () => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    const result = await Notification.requestPermission();
    setPermission(result);
  };

  return (
    <section className="settings-panel">
      <h2>알림 설정</h2>
      {TOGGLE_ITEMS.map((item) => (
        <div className="settings-toggle-row" key={item.key}>
          <span className="settings-toggle-label">{item.label}</span>
          <ToggleSwitch
            checked={settings?.[item.key] ?? false}
            disabled={isLoading || !settings}
            onChange={(value) => handleToggle(item.key, value)}
            label={item.label}
          />
        </div>
      ))}
      {permission !== "granted" && permission !== "unsupported" && (
        <button type="button" className="dashboard-chip-button" onClick={handleRequestPermission}>
          브라우저 알림 권한 허용
        </button>
      )}
      {permission === "denied" && (
        <p className="settings-caption">
          브라우저 알림이 차단되어 있습니다. 브라우저 설정에서 허용해주세요.
        </p>
      )}
      <p className="settings-caption">
        브라우저 푸시는 접속 중 즉시 알림, 알림 센터는 미확인 내역 누적 확인용입니다.
      </p>
    </section>
  );
}
