import { ApiError, API_BASE_URL, apiFetch, extractErrorDetail } from "./client";
import type {
  HoldingItem,
  PortfolioReport,
  PortfolioSummary,
  ReportPeriod,
  TradeListResponse,
  TradeSide,
  TradeSource,
} from "../types/portfolio";

export function getPortfolioSummary(token: string): Promise<PortfolioSummary> {
  return apiFetch<PortfolioSummary>("/api/portfolio/summary", { token });
}

export function getPortfolioHoldings(token: string): Promise<HoldingItem[]> {
  return apiFetch<HoldingItem[]>("/api/portfolio/holdings", { token });
}

export interface TradeFilter {
  side: TradeSide | null;
  source: TradeSource | null;
  coinSymbol: string | null;
}

function buildFilterParams({ side, source, coinSymbol }: TradeFilter): URLSearchParams {
  const params = new URLSearchParams();
  if (side) params.set("side", side);
  if (source) params.set("source", source);
  if (coinSymbol) params.set("coin_symbol", coinSymbol);
  return params;
}

export function getPortfolioTrades(
  token: string,
  filter: TradeFilter,
  page: number,
  pageSize: number,
): Promise<TradeListResponse> {
  const params = buildFilterParams(filter);
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  return apiFetch<TradeListResponse>(`/api/portfolio/trades?${params.toString()}`, { token });
}

export function getPortfolioReport(token: string, period: ReportPeriod): Promise<PortfolioReport> {
  return apiFetch<PortfolioReport>(`/api/portfolio/report?period=${period}`, { token });
}

// client.ts의 apiFetch는 항상 response.json()을 하므로 CSV(text/csv) 응답에는 쓸 수 없다
// (08-portfolio.md 2-B 구현 노트). raw fetch로 Blob을 받아 다운로드를 트리거한다.
export async function downloadPortfolioTradesCsv(token: string, filter: TradeFilter): Promise<void> {
  const params = buildFilterParams(filter);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/portfolio/trades/export?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError("서버와 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", 0);
  }
  if (!response.ok) {
    throw new ApiError(await extractErrorDetail(response), response.status);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? "trades.csv";

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
