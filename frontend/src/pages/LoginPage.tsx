import { useState } from "react";
import { Navigate } from "react-router-dom";
import { LoginForm } from "../components/LoginForm";
import { RegisterForm } from "../components/RegisterForm";
import { Toast } from "../components/Toast";
import { useAuth } from "../hooks/useAuth";

// SCR-01 — 좌우 2분할: 왼쪽 로그인 / 오른쪽 회원가입 (01-auth.md 2장)
export function LoginPage() {
  const { isAuthenticated } = useAuth();
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="auth-page">
      <div className="auth-split">
        <div className="auth-panel">
          <LoginForm onServerError={setToastMessage} />
          <p className="auth-switch-link">
            계정이 없으신가요?{" "}
            <a
              href="#register-email"
              onClick={(event) => {
                event.preventDefault();
                document.getElementById("register-email")?.focus();
              }}
            >
              회원가입
            </a>
          </p>
        </div>
        <div className="auth-panel">
          <RegisterForm onServerError={setToastMessage} />
          <p className="auth-switch-link">
            이미 계정이 있으신가요?{" "}
            <a
              href="#login-email"
              onClick={(event) => {
                event.preventDefault();
                document.getElementById("login-email")?.focus();
              }}
            >
              로그인
            </a>
          </p>
        </div>
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
