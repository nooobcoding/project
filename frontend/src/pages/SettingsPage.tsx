import { useState } from "react";
import { AccountSettingsPanel } from "../components/settings/AccountSettingsPanel";
import { NotificationSettingsPanel } from "../components/settings/NotificationSettingsPanel";
import { Toast } from "../components/Toast";

// SCR-08 — 공통 설정 (docs/features/04-settings.md): 좌 계정 설정 / 우 알림 설정 2컬럼
export function SettingsPage() {
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  return (
    <div className="settings-page">
      <div className="settings-grid">
        <AccountSettingsPanel onToast={setToastMessage} />
        <NotificationSettingsPanel onToast={setToastMessage} />
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
