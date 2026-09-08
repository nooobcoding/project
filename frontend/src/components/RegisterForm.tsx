import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { checkEmailAvailable } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { PasswordInput } from "./PasswordInput";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// 01-auth.md 2-B와 동일 규칙 — backend/app/schemas/auth.py의 검증과 동기화되어야 한다
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

interface RegisterFormProps {
  onServerError: (message: string) => void;
}

export function RegisterForm({ onServerError }: RegisterFormProps) {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
  const [isCheckingEmail, setIsCheckingEmail] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);

  const passwordError =
    password.length > 0 && !PASSWORD_PATTERN.test(password)
      ? "비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다."
      : undefined;
  const passwordConfirmError =
    passwordConfirm.length > 0 && passwordConfirm !== password
      ? "비밀번호가 일치하지 않습니다."
      : undefined;

  const isValid =
    EMAIL_PATTERN.test(email) &&
    !emailError &&
    PASSWORD_PATTERN.test(password) &&
    passwordConfirm === password;

  const handleEmailBlur = async () => {
    if (!EMAIL_PATTERN.test(email)) {
      setEmailError("올바른 이메일 형식을 입력해주세요.");
      return;
    }
    setIsCheckingEmail(true);
    try {
      const { available } = await checkEmailAvailable(email);
      setEmailError(available ? undefined : "이미 사용 중인 이메일입니다.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        onServerError(err.message);
      }
      // 중복확인 실패는 제출 시 서버가 다시 검증하므로 여기서는 조용히 넘어간다
    } finally {
      setIsCheckingEmail(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isValid) return;

    setIsSubmitting(true);
    try {
      await register(email, password);
      navigate("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 0) {
          onServerError(err.message);
        } else {
          // 01-auth.md 4장 — 중복 이메일: 이메일 필드 포커스 유지
          setEmailError(err.message);
          emailRef.current?.focus();
        }
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <h2>회원가입</h2>
      <div className="auth-field">
        <label htmlFor="register-email">이메일</label>
        <input
          id="register-email"
          ref={emailRef}
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          onBlur={handleEmailBlur}
          autoComplete="email"
          className={emailError ? "auth-input has-error" : "auth-input"}
        />
        {isCheckingEmail && <p className="auth-hint">중복 확인 중...</p>}
        {emailError && <p className="auth-error-message">{emailError}</p>}
      </div>
      <PasswordInput
        label="비밀번호"
        value={password}
        onChange={setPassword}
        error={passwordError}
        autoComplete="new-password"
      />
      <PasswordInput
        label="비밀번호 확인"
        value={passwordConfirm}
        onChange={setPasswordConfirm}
        error={passwordConfirmError}
        autoComplete="new-password"
      />
      <button type="submit" className="auth-button" disabled={!isValid || isSubmitting}>
        {isSubmitting ? "계정 생성 중..." : "계정 생성"}
      </button>
    </form>
  );
}
