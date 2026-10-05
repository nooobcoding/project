import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { LoginForm } from "../components/LoginForm";
import { Toast } from "../components/Toast";
import { useAuth } from "../hooks/useAuth";

// SCR-01 — 로그인 전용 화면 (01-auth.md 2-A). 회원가입은 /register로 분리.
export function LoginPage() {
  const { isAuthenticated, notice, clearNotice } = useAuth();
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  if (isAuthenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="auth-page">
      <div className="auth-single">
        <p className="auth-brand">Gazua</p>
        <div className="auth-panel">
          {/* 정지로 강제 로그아웃된 경우 — 왜 튕겨 나왔는지 알려준다 */}
          {notice && <p className="auth-error-message">{notice}</p>}
          <LoginForm
            onServerError={setToastMessage}
            onSubmitStart={clearNotice}
          />
          <p className="auth-switch-link">
            계정이 없으신가요? <Link to="/register">회원가입</Link>
          </p>
        </div>
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
