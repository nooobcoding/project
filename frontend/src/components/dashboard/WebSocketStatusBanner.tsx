import type { PriceStreamStatus } from "../../hooks/usePriceStream";

interface WebSocketStatusBannerProps {
  status: PriceStreamStatus;
}

// 02-dashboard.md 2-A "WebSocket 상태 안내" + 3장 인터랙션 표(재연결 실패 시 배너).
export function WebSocketStatusBanner({ status }: WebSocketStatusBannerProps) {
  if (status === "failed") {
    return (
      <div className="dashboard-ws-banner" role="alert">
        실시간 시세 연결에 실패했습니다. 새로고침 후 다시 시도해주세요.
      </div>
    );
  }

  return (
    <p className="dashboard-ws-caption">
      {status === "open" ? "실시간 시세 연결됨" : "실시간 시세 연결 중..."}
    </p>
  );
}
