import { useMemo } from "react";
import { AssetSummaryCard } from "../components/dashboard/AssetSummaryCard";
import { AutoTradingStatusCard } from "../components/dashboard/AutoTradingStatusCard";
import { CandleChart } from "../components/dashboard/CandleChart";
import { CoinPriceList } from "../components/dashboard/CoinPriceList";
import { CoinTabSelector } from "../components/dashboard/CoinTabSelector";
import { RecentTradesList } from "../components/dashboard/RecentTradesList";
import { ShortcutChips } from "../components/dashboard/ShortcutChips";
import { WebSocketStatusBanner } from "../components/dashboard/WebSocketStatusBanner";
import { useCoins } from "../hooks/useCoins";
import { useDashboardSummary } from "../hooks/useDashboardSummary";
import { useRecentTrades } from "../hooks/useRecentTrades";
import { usePriceStream } from "../hooks/usePriceStream";
import { useWatchlist } from "../hooks/useWatchlist";

export function DashboardPage() {
  const { summary, isLoading: isSummaryLoading } = useDashboardSummary();
  const { items, selectedSymbol, selectSymbol, addItem, removeItem } = useWatchlist();
  const { trades, isLoading: isTradesLoading } = useRecentTrades();
  const { coins } = useCoins();

  const watchlistSymbols = useMemo(() => items.map((item) => item.coin_symbol), [items]);
  const { prices, status } = usePriceStream(watchlistSymbols);
  const selectedTick = selectedSymbol ? prices[selectedSymbol] ?? null : null;

  return (
    <div className="dashboard-page">
      <div className="dashboard-grid">
        <div className="dashboard-column">
          <AssetSummaryCard summary={summary} isLoading={isSummaryLoading} />
          <CoinPriceList
            items={items}
            prices={prices}
            coins={coins}
            onAdd={addItem}
            onRemove={removeItem}
          />
          <WebSocketStatusBanner status={status} />
        </div>
        <div className="dashboard-column">
          <CoinTabSelector items={items} selectedSymbol={selectedSymbol} onSelect={selectSymbol} />
          <CandleChart symbol={selectedSymbol} tick={selectedTick} interval="1d" />
          <AutoTradingStatusCard />
        </div>
        <div className="dashboard-column">
          <RecentTradesList trades={trades} isLoading={isTradesLoading} />
          <ShortcutChips />
        </div>
      </div>
    </div>
  );
}
