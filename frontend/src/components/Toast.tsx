import { useEffect } from "react";

interface ToastProps {
  message: string;
  onDismiss: () => void;
}

// 01-auth.md 4장 — 서버 통신 오류는 토스트로 표시한다. 3초 후 자동으로 사라진다.
export function Toast({ message, onDismiss }: ToastProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 3000);
    return () => clearTimeout(timer);
    // onDismiss는 부모 렌더마다 새로 생성되는 인라인 함수라 의존성에 넣으면
    // (예: 가격 스트림 틱으로 인한 리렌더 시) 타이머가 계속 리셋되어 사라지지 않는다.
    // message가 바뀔 때만 타이머를 새로 시작한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message]);

  return (
    <div className="auth-toast" role="alert">
      {message}
    </div>
  );
}
