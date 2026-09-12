import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { PasswordInput } from "./PasswordInput";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface LoginFormProps {
  onServerError: (message: string) => void;
}

export function LoginForm({ onServerError }: LoginFormProps) {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [emailError, setEmailError] = useState<string | undefined>();
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  const handleEmailBlur = () => {
    setEmailError(
      email && !EMAIL_PATTERN.test(email) ? "올바른 이메일 형식을 입력해주세요." : undefined,
    );
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!EMAIL_PATTERN.test(email)) {
      setEmailError("올바른 이메일 형식을 입력해주세요.");
      return;
    }

    setPasswordError(undefined);
    setIsSubmitting(true);
    try {
      await login(email, password, rememberMe);
      navigate("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 0) {
          onServerError(err.message);
        } else {
          // 01-auth.md 4장 — 입력 초기화 없이 표시, 비밀번호 필드 포커스
          setPasswordError(err.message);
          passwordRef.current?.focus();
        }
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <h2>로그인</h2>
      <div className="auth-field">
        <label htmlFor="login-email">이메일</label>
        <input
          id="login-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          onBlur={handleEmailBlur}
          autoComplete="email"
          className={emailError ? "auth-input has-error" : "auth-input"}
        />
        {emailError && <p className="auth-error-message">{emailError}</p>}
      </div>
      <PasswordInput
        ref={passwordRef}
        label="비밀번호"
        value={password}
        onChange={setPassword}
        error={passwordError}
        autoComplete="current-password"
      />
      <label className="auth-checkbox-row">
        <input
          type="checkbox"
          checked={rememberMe}
          onChange={(event) => setRememberMe(event.target.checked)}
        />
        로그인 유지
      </label>
      <button type="submit" className="auth-button" disabled={isSubmitting}>
        {isSubmitting ? "로그인 중..." : "로그인"}
      </button>
    </form>
  );
}
