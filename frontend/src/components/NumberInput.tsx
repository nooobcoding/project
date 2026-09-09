import { forwardRef, useId, type ChangeEvent } from "react";

interface NumberInputProps {
  label: string;
  value: string;
  onChange: (rawValue: string) => void;
  placeholder?: string;
  suffix?: string;
  disabled?: boolean;
  error?: string;
}

function formatWithCommas(rawValue: string): string {
  if (rawValue === "") return "";
  const [integerPart, decimalPart] = rawValue.split(".");
  const formattedInteger = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return decimalPart === undefined ? formattedInteger : `${formattedInteger}.${decimalPart}`;
}

function stripToRawNumber(displayValue: string): string {
  // 숫자와 소수점 하나만 남긴다 — 두 번째 이후의 점은 무시(03-manual-trading.md 2-D 콤마 포매팅)
  const cleaned = displayValue.replace(/[^\d.]/g, "");
  const firstDot = cleaned.indexOf(".");
  if (firstDot === -1) return cleaned;
  return cleaned.slice(0, firstDot + 1) + cleaned.slice(firstDot + 1).replace(/\./g, "");
}

// 가격/수량 입력에 쓰는 콤마 포매팅 숫자 입력 (03-manual-trading.md 2-D). 표시는 콤마 포함,
// onChange로 넘기는/부모 state에 저장하는 값은 콤마 없는 원시 숫자 문자열이다.
export const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(function NumberInput(
  { label, value, onChange, placeholder, suffix, disabled, error },
  ref,
) {
  const inputId = useId();

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(stripToRawNumber(event.target.value));
  };

  return (
    <div className="order-field">
      <label htmlFor={inputId}>{label}</label>
      <div className="order-number-input-row">
        <input
          id={inputId}
          ref={ref}
          type="text"
          inputMode="decimal"
          value={formatWithCommas(value)}
          onChange={handleChange}
          placeholder={placeholder}
          disabled={disabled}
          className={error ? "order-number-input has-error" : "order-number-input"}
        />
        {suffix && <span className="order-number-input-suffix">{suffix}</span>}
      </div>
      {error && <p className="auth-error-message">{error}</p>}
    </div>
  );
});
