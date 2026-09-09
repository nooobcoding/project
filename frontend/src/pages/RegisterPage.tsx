import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { RegisterForm } from "../components/RegisterForm";
import { Toast } from "../components/Toast";
import { useAuth } from "../hooks/useAuth";

// SCR-01 — 회원가입 전용 화면 (01-auth.md 2-B). 로그인은 /login으로 분리.
export function RegisterPage() {
  const { isAuthenticated } = useAuth();
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="auth-page">
      <div className="auth-single">
        <p className="auth-brand">Gazua</p>
        <div className="auth-panel">
          <RegisterForm onServerError={setToastMessage} />
          <p className="auth-switch-link">
            이미 계정이 있으신가요? <Link to="/login">로그인</Link>
          </p>
        </div>
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
