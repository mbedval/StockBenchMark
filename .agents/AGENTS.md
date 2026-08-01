# StockBenchMark Project Rules

This document outlines the rules, architectural decisions, and constraints for the **StockBenchMark** framework, focusing on data collection, design, strategy benchmarking, and data analysis.

---

## 1. Report & Visual Output Format
- **Default Dashboard Format is HTML only.** All benchmarks, performance comparison reports, and interactive analytics dashboards must be generated as HTML files by default.
- **Data Export Formats (CSV/JSON):** Raw benchmark metrics, trade-by-trade logs, and strategy stats should be exported as CSV/JSON alongside the HTML reports to facilitate further quantitative analysis.
- **Embedded Visualization:** Charts, equity curves, and drawdown plots must be embedded inside the HTML report (either as base64-encoded PNGs or interactive JS plotting libraries) by default. Storing separate PNG files in `output/plots/` is optional and should be configured via a CLI flag (e.g. `--save-plots`).

---

## 2. Output Directory — Single Canonical Root
- **All generated artefacts MUST be written under `output/`** (the project root `output/` directory).
- Sub-directory layout inside `output/` is fixed:

  | Artefact Type | Path | Description |
  |---|---|---|
  | HTML dashboards & reports | `output/htmls/` | Interactive summary files |
  | Raw metrics & logs | `output/metrics/` | CSV/JSON backtest outputs |
  | Performance Plots & charts | `output/plots/` | Saved PNG/SVG visualizations |
  | Benchmark Database | `output/db/` | SQLite database storage |
  | Log files | `output/` (root) | Master log file (`stockbenchmark.log`) |

---

## 3. Data Collection, Caching, and Fallback
- **Rate-Limit Mitigation:** All raw historical OHLCV data, F&O chain details, or fundamental data downloaded (via `yfinance` or other source APIs) must be cached in a local SQLite cache database or cached file system (`data/cache/`).
- **No Redundant API Hits:** Before requesting data from external endpoints, scripts must check the cache first. If cache hit is valid for the query window (e.g. up to current date for end-of-day data), load data from cache instead of hitting external servers.
- **Synthetic Fallback Layer:** If network requests fail or rate limits are reached, the data loader must seamlessly fall back to generating synthetic stock data (e.g., geometric Brownian motion based on historical volatility) or using mock files, enabling benchmarks to run offline without crashing.

---

## 4. Benchmark & Backtesting Integrity
- **Look-Ahead Bias Prevention:** Algorithms and strategies must strictly operate on historical data chronologically. Accessing future indicators, close prices, or corporate action information before their simulated event timestamps is strictly forbidden.
- **Transaction Costs & Slippage:** Every strategy benchmark run must incorporate configurable transaction fees, brokerage fees, taxes, and slippage (e.g., default 0.1% or 0.2% per leg) to ensure realistic performance results.
- **Benchmark Baselines:** All strategy backtests must be benchmarked against standard buy-and-hold indexes (e.g., Nifty 50, S&P 500, or index ETFs) over the exact same period for objective comparison.

---

## 5. Database Management & Deduplication
- **Benchmark Run Tracking:** Store all completed benchmark results, strategy parameters, and performance scores in a central SQLite database (`output/db/benchmark.db`).
- **Run Deduplication Rule:** Before inserting a new benchmark run record, verify if a run with identical configuration (same strategy name, tickers, parameter set, start date, and end date) already exists.
  - If a matching run exists, update the existing record with the latest execution results and timestamp in-place rather than inserting a duplicate record.
