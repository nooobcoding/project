// API 처리량 측정 (k6). 고정 VU 수로 일정 시간 요청을 퍼붓고 RPS·p95를 본다.
//
// 한 반복 = 로그인한 유저가 화면을 둘러보는 묶음: 대시보드 요약, 보유 자산, 미체결 주문,
// 전략 슬롯. 열 번에 한 번 소액 시장가 매수를 섞는다 — 쓰기 경로(balances 행 잠금 + 즉시 체결)가
// 빠지면 읽기만 재는 셈이 된다.
//
// 실행은 bench_api.sh가 한다 (k6 컨테이너, --network host).

import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const users = JSON.parse(open("/load/users.json"));

export const options = {
  scenarios: {
    steady: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 50),
      duration: __ENV.DURATION || "40s",
    },
  },
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max"],
};

export default function () {
  const user = users[(__VU - 1) % users.length];
  const params = { headers: { Authorization: `Bearer ${user.token}`, "Content-Type": "application/json" } };

  const reads = http.batch([
    ["GET", `${BASE}/api/dashboard/summary`, null, params],
    ["GET", `${BASE}/api/portfolio/holdings`, null, params],
    ["GET", `${BASE}/api/orders`, null, params],
    ["GET", `${BASE}/api/strategy-slots`, null, params],
  ]);
  reads.forEach((r) => check(r, { "read 200": (res) => res.status === 200 }));

  if (__ITER % 10 === 0) {
    const order = http.post(
      `${BASE}/api/orders`,
      JSON.stringify({ coin_symbol: user.order_coin, side: "buy", order_type: "market", quantity: "1" }),
      params,
    );
    check(order, { "order 201": (res) => res.status === 201 });
  }
  sleep(0.2);
}
