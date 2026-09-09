import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CandleChart } from "../components/dashboard/CandleChart";
import { CoinListPanel } from "../components/manual-trading/CoinListPanel";
import { IntervalTabs } from "../components/manual-trading/IntervalTabs";
import { OrderBookPanel } from "../components/manual-trading/OrderBookPanel";
import { OrderFormPanel } from "../components/manual-trading/OrderFormPanel";
import { PendingOrdersList } from "../components/manual-trading/PendingOrdersList";
import { PriceHeaderPanel } from "../components/manual-trading/PriceHeaderPanel";
import { TransactionHistoryPanel } from "../components/manual-trading/TransactionHistoryPanel";
import { Toast } from "../components/Toast";
import { useAvailableBalance } from "../hooks/useAvailableBalance";
import { useCoins } from "../hooks/useCoins";
import { useOrderBook } from "../hooks/useOrderBook";
import { useOrderHistory } from "../hooks/useOrderHistory";
import { useOrders } from "../hooks/useOrders";
import { usePriceStream } from "../hooks/usePriceStream";
import type { CandleInterval } from "../types/candles";

const SELECTED_COIN_STORAGE_KEY = "coin_autotrading_trade_selected_coin";

export function ManualTradingPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { coins } = useCoins();
  const [candleInterval, setCandleInterval] = useState<CandleInterval>("1d");
  const [orderPrice, setOrderPrice] = useState("");
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const symbolFromParams = searchParams.get("symbol");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(
    () => symbolFromParams ?? localStorage.getItem(SELECTED_COIN_STORAGE_KEY),
  );

  useEffect(() => {
    // 목록이 아직 없거나(최초 로딩) 선택된 심볼이 목록에 없으면(상장폐지 등) 첫 항목으로 보정한다.
    if (coins.length === 0) return;
    if (!selectedSymbol || !coins.some((coin) => coin.symbol === selectedSymbol)) {
      setSelectedSymbol(coins[0].symbol);
    }
  }, [coins, selectedSymbol]);

  const selectSymbol = (symbol: string) => {
    setSelectedSymbol(symbol);
    setOrderPrice("");
    localStorage.setItem(SELECTED_COIN_STORAGE_KEY, symbol);
    setSearchParams({ symbol }, { replace: true });
  };

  const allSymbols = useMemo(() => coins.map((coin) => coin.symbol), [coins]);
  const { prices } = usePriceStream(allSymbols);
  const selectedCoin = coins.find((coin) => coin.symbol === selectedSymbol) ?? null;
  const selectedTick = selectedSymbol ? prices[selectedSymbol] ?? null : null;

  const { orderBook } = useOrderBook(selectedSymbol);
  const { orders, submitOrder, cancelOrder } = useOrders();
  const { balance, refresh: refreshBalance } = useAvailableBalance(selectedSymbol);
  const { history } = useOrderHistory(selectedSymbol);

  const pendingOrdersForSymbol = orders.filter((order) => order.coin_symbol === selectedSymbol);

  const handleOrderSuccess = () => {
    setToastMessage("주문이 접수되었습니다.");
    refreshBalance().catch(() => undefined);
  };

  const handleCancel = async (orderId: number) => {
    try {
      await cancelOrder(orderId);
      refreshBalance().catch(() => undefined);
    } catch {
      setToastMessage("주문 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <div className="dashboard-page">
      <div className="trade-grid">
        <CoinListPanel
          coins={coins}
          prices={prices}
          selectedSymbol={selectedSymbol}
          onSelect={selectSymbol}
        />
        <div className="trade-column">
          <PriceHeaderPanel coin={selectedCoin} tick={selectedTick} />
          <IntervalTabs interval={candleInterval} onChange={setCandleInterval} />
          <CandleChart symbol={selectedSymbol} tick={selectedTick} interval={candleInterval} />
          <PendingOrdersList orders={pendingOrdersForSymbol} onCancel={handleCancel} />
        </div>
        <OrderBookPanel
          orderBook={orderBook}
          currentPrice={selectedTick?.trade_price ?? null}
          onLevelClick={(clickedPrice) => setOrderPrice(String(clickedPrice))}
        />
      </div>
      <div className="trade-order-form-row">
        <OrderFormPanel
          symbol={selectedSymbol}
          currentPrice={selectedTick?.trade_price ?? null}
          availableBalance={balance}
          price={orderPrice}
          onPriceChange={setOrderPrice}
          onSubmit={submitOrder}
          onSuccess={handleOrderSuccess}
        />
      </div>
      <div className="trade-history-row">
        <TransactionHistoryPanel history={history} />
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
