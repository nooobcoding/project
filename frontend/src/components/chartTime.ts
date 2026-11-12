import { TickMarkType, type Time } from "lightweight-charts";

// lightweight-charts는 시간을 **UTC 그대로** 그린다 (브라우저 시간대를 따르지 않는다). 그래서 봉
// 데이터를 UTC 타임스탬프로 넘기면 축과 십자선이 9시간 이른 시각을 보여준다 — 오후 6시 봉이
// "09:00"으로 찍혔다. 표시만 한국 시간으로 바꾼다. 데이터 자체(타임스탬프)는 건드리지 않으므로
// 실시간 틱을 봉에 합치는 계산(CandleChart의 bucketStart)은 그대로다.
const TIME_ZONE = "Asia/Seoul";

const formatters = {
  full: new Intl.DateTimeFormat("ko-KR", {
    timeZone: TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }),
  year: new Intl.DateTimeFormat("ko-KR", { timeZone: TIME_ZONE, year: "numeric" }),
  month: new Intl.DateTimeFormat("ko-KR", { timeZone: TIME_ZONE, month: "short" }),
  day: new Intl.DateTimeFormat("ko-KR", { timeZone: TIME_ZONE, month: "numeric", day: "numeric" }),
  time: new Intl.DateTimeFormat("ko-KR", {
    timeZone: TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }),
};

// 이 프로젝트의 차트는 시간을 항상 UTC 초 단위 숫자로 넘긴다
function toDate(time: Time): Date | null {
  return typeof time === "number" ? new Date(time * 1000) : null;
}

const TICK_FORMATTER: Record<TickMarkType, Intl.DateTimeFormat> = {
  [TickMarkType.Year]: formatters.year,
  [TickMarkType.Month]: formatters.month,
  [TickMarkType.DayOfMonth]: formatters.day,
  [TickMarkType.Time]: formatters.time,
  [TickMarkType.TimeWithSeconds]: formatters.time,
};

// createChart 옵션에 펼쳐 넣는다. timeScale은 호출부 옵션과 합쳐야 하므로 따로 내보낸다.
export const kstLocalization = {
  locale: "ko-KR",
  timeFormatter: (time: Time) => {
    const date = toDate(time);
    return date ? formatters.full.format(date) : String(time);
  },
};

export const kstTickMarkFormatter = (time: Time, tickMarkType: TickMarkType) => {
  const date = toDate(time);
  return date ? TICK_FORMATTER[tickMarkType].format(date) : String(time);
};
