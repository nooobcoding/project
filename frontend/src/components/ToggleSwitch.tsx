import { useId } from "react";

interface ToggleSwitchProps {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  label: string;
}

// 04-settings.md 2-B 알림 설정 토글 3종이 공유하는 공용 스위치
export function ToggleSwitch({ checked, onChange, disabled, label }: ToggleSwitchProps) {
  const inputId = useId();

  return (
    <label className="toggle-switch" htmlFor={inputId}>
      <input
        id={inputId}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        aria-label={label}
      />
      <span className="toggle-switch-track" />
    </label>
  );
}
