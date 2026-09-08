import { useEffect } from "react";

interface ToastProps {
  message: string;
  onDismiss: () => void;
}

// 01-auth.md 4장 — 서버 통신 오류는 토스트로 표시한다. 4초 후 자동으로 사라진다.
export function Toast({ message, onDismiss }: ToastProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className="auth-toast" role="alert">
      {message}
    </div>
  );
}
