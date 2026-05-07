/**
 * Ticker display helper.
 *
 * Yahoo Finance / yfinance uses suffixes after the dot to specify the exchange,
 * because the same ticker can list on multiple exchanges (e.g. VWRL.L on London,
 * VWCE.DE on Xetra, AAPL on NASDAQ).
 *
 * For UI we want to show the bare ticker plus a separate "Exchange" column
 * so the symbol stays readable. The original full ticker (with suffix) stays
 * in the database and in URL paths since it's the unambiguous identifier
 * yfinance + our pipeline use.
 */

const EXCHANGE_NAMES: Record<string, string> = {
  L: "LSE",
  DE: "Xetra",
  AS: "Euronext AS",
  PA: "Euronext PA",
  MI: "Borsa IT",
  MC: "BME",
  SW: "SIX",
  ST: "Stockholm",
  HE: "Helsinki",
  CO: "Copenhagen",
  OL: "Oslo",
  IR: "Euronext IR",
  WA: "GPW Warsaw",
  TO: "Toronto",
  V: "TSX-V",
  HK: "HKEX",
  T: "Tokyo",
};

const EXCHANGE_FULL: Record<string, string> = {
  L: "London Stock Exchange",
  DE: "Xetra (Germany)",
  AS: "Euronext Amsterdam",
  PA: "Euronext Paris",
  MI: "Borsa Italiana (Milan)",
  MC: "Bolsa de Madrid",
  SW: "SIX Swiss Exchange",
  ST: "Nasdaq Stockholm",
  HE: "Nasdaq Helsinki",
  CO: "Nasdaq Copenhagen",
  OL: "Oslo Børs",
  IR: "Euronext Dublin",
  WA: "Warsaw Stock Exchange",
  TO: "Toronto Stock Exchange",
  V: "TSX Venture",
  HK: "Hong Kong Stock Exchange",
  T: "Tokyo Stock Exchange",
};

export interface ParsedTicker {
  /** The full ticker including suffix — what's stored in the DB and used by yfinance. */
  full: string;
  /** Bare ticker without exchange suffix — for clean display. */
  display: string;
  /** Short exchange label suitable for a column. */
  exchange: string;
  /** Long exchange description for tooltips. */
  exchangeFull: string;
}

export function parseTicker(ticker: string): ParsedTicker {
  const match = ticker.match(/^(.+)\.([A-Z]+)$/);
  if (!match) {
    return {
      full: ticker,
      display: ticker,
      exchange: "US",
      exchangeFull: "NYSE / NASDAQ (US)",
    };
  }
  const [, base, suffix] = match;
  return {
    full: ticker,
    display: base,
    exchange: EXCHANGE_NAMES[suffix] ?? suffix,
    exchangeFull: EXCHANGE_FULL[suffix] ?? `Exchange suffix .${suffix}`,
  };
}
