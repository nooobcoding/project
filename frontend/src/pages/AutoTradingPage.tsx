import { useMemo, useState } from "react";
import { AutoNotificationPanel } from "../components/auto-trading/AutoNotificationPanel";
import { AutoTradeHistoryPanel } from "../components/auto-trading/AutoTradeHistoryPanel";
import { SignalMonitorPanel } from "../components/auto-trading/SignalMonitorPanel";
import { SlotListPanel } from "../components/auto-trading/SlotListPanel";
import { Toast } from "../components/Toast";
import { useAutoNotifications } from "../hooks/useAutoNotifications";
import { useAutoTradeHistory } from "../hooks/useAutoTradeHistory";
import { useCoins } from "../hooks/useCoins";
import { useSlotSignals } from "../hooks/useSlotSignals";
import { useStrategySlots } from "../hooks/useStrategySlots";

// SCR-04 — 자동매매 (docs/features/07-auto-trading.md 3장): 3컬럼 —
// 전략 슬롯 목록(280px) / 신호 모니터링·체결 내역 / 알림 센터(280px).
// 페이지가 모든 데이터 훅을 소유하고 하위 패널은 props만 받는다 (ManualTradingPage와 동일 패턴).
export function AutoTradingPage() {
  const { coins } = useCoins();
  const { slots, createSlot, updateSlot, toggleSlot, deleteSlot } = useStrategySlots();
  const { history } = useAutoTradeHistory();
  const { notifications, markRead } = useAutoNotifications();
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const activeSlotIds = useMemo(
    () => slots.filter((slot) => slot.is_active).map((slot) => slot.id),
    [slots],
  );
  const signals = useSlotSignals(activeSlotIds);

  return (
    <div className="dashboard-page">
      <div className="auto-grid">
        <SlotListPanel
          slots={slots}
          coins={coins}
          onCreate={createSlot}
          onUpdate={updateSlot}
          onToggle={toggleSlot}
          onDelete={deleteSlot}
          onError={setToastMessage}
        />
        <div className="auto-center-column">
          <SignalMonitorPanel slots={slots} coins={coins} signals={signals} />
          <AutoTradeHistoryPanel history={history} slots={slots} coins={coins} />
        </div>
        <AutoNotificationPanel notifications={notifications} onMarkRead={markRead} />
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
