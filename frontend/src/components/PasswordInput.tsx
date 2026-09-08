import { forwardRef, useId, useState } from "react";

interface PasswordInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  error?: string;
  autoComplete?: string;
}

// 로그인·회원가입 폼이 공유하는 비밀번호 입력 (마스킹 + 표시/숨김 토글, 01-auth.md 2장)
export const PasswordInput = forwardRef<HTMLInputElement, PasswordInputProps>(
  function PasswordInput({ label, value, onChange, onBlur, error, autoComplete }, ref) {
    const [visible, setVisible] = useState(false);
    const inputId = useId();

    return (
      <div className="auth-field">
        <label htmlFor={inputId}>{label}</label>
        <div className="auth-password-row">
          <input
            id={inputId}
            ref={ref}
            type={visible ? "text" : "password"}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onBlur={onBlur}
            autoComplete={autoComplete}
            className={error ? "auth-input has-error" : "auth-input"}
          />
          <button
            type="button"
            className="auth-password-toggle"
            onClick={() => setVisible((prev) => !prev)}
            aria-label={visible ? "비밀번호 숨기기" : "비밀번호 표시"}
          >
            {visible ? "숨기기" : "표시"}
          </button>
        </div>
        {error && <p className="auth-error-message">{error}</p>}
      </div>
    );
  },
);
