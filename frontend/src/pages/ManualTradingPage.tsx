import { useCallback, useEffect, useMemo, useState } from "react";
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

  const selectSymbol = useCallback(
    (symbol: string) => {
      setSelectedSymbol(symbol);
      setOrderPrice("");
      localStorage.setItem(SELECTED_COIN_STORAGE_KEY, symbol);
      setSearchParams({ symbol }, { replace: true });
    },
    [setSearchParams],
  );

  useEffect(() => {
    // 목록이 아직 없거나(최초 로딩) 선택된 심볼이 목록에 없으면(상장폐지 등) 첫 항목으로 보정한다.
    // selectSymbol을 거쳐야 localStorage·URL도 같이 갱신되어, 다음 방문 때 다시
    // 임의의 첫 코인으로 되돌아가지 않는다 (기존엔 setSelectedSymbol만 호출해 보정 결과가
    // 저장되지 않았고, 재방문 시 매번 이 보정 로직이 다시 타면서 다른 코인이 뽑힐 수 있었다).
    if (coins.length === 0) return;
    if (!selectedSymbol || !coins.some((coin) => coin.symbol === selectedSymbol)) {
      selectSymbol(coins[0].symbol);
    }
  }, [coins, selectedSymbol, selectSymbol]);

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
        <div className="trade-column">
          <PriceHeaderPanel coin={selectedCoin} tick={selectedTick} />
          <IntervalTabs interval={candleInterval} onChange={setCandleInterval} />
          <CandleChart symbol={selectedSymbol} tick={selectedTick} interval={candleInterval} />
        </div>
        <CoinListPanel
          coins={coins}
          prices={prices}
          selectedSymbol={selectedSymbol}
          onSelect={selectSymbol}
        />
        <div className="trade-order-row">
          <OrderBookPanel
            orderBook={orderBook}
            currentPrice={selectedTick?.trade_price ?? null}
            onLevelClick={(clickedPrice) => setOrderPrice(String(clickedPrice))}
          />
          <div className="trade-order-column">
            <OrderFormPanel
              symbol={selectedSymbol}
              currentPrice={selectedTick?.trade_price ?? null}
              availableBalance={balance}
              price={orderPrice}
              onPriceChange={setOrderPrice}
              onSubmit={submitOrder}
              onSuccess={handleOrderSuccess}
            />
            <TransactionHistoryPanel history={history} />
            <PendingOrdersList orders={pendingOrdersForSymbol} onCancel={handleCancel} />
          </div>
        </div>
      </div>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
