# Update: portfolio quotes and clearer research

See [RUNNING.md](RUNNING.md) for the setup and background-start instructions.

- Quotes for holdings and the shortlist refresh independently every 60 seconds, with timestamps and errors.
- Enter exact share quantities once to enable automatic portfolio value and daily P&L.
- Explore starts with your holdings and top 15 scanned stocks; company search needs no manually maintained list.
- Momentum scores are shown separately from immutable future-return forecasts.
- Completed outcomes update the regression with modest decay of older training influence. Forward accuracy remains separate from historical fitting.
- Automatic startup scripts are provided for Mac and Windows; Linux service instructions are included.

Live provider verification timed out in the build environment. A working network connection to Yahoo Finance and NSE is required; no synthetic quotes replace failed requests.

# Project Mentalist

A local NSE equity scanner with a portfolio ledger, separate short/long technical scores, and **recorded 5-session and 21-session return forecasts that learn from completed outcomes**.

## Run

Requires Python 3.10+. No Streamlit, pip packages, API key or frontend build step.

```sh
python3 server.py --open
```

On Windows, use `py server.py --open`. Alternatively open `Start-Mac.command` or `Start-Windows.bat`. The dashboard opens at **http://127.0.0.1:8765**. Keep the terminal running. If that port is occupied, stop the previous version or add `--port 8766` (a new browser origin has separate portfolio storage).

The public repository contains source code, not personal holdings or downloaded market-data snapshots. On first start it obtains NSE's EQ universe and downloads real daily history. Missing seed scripts are handled by the local server; use the launcher rather than opening index.html directly.

## What changed

### Faster scanning

- **Continuous bounded queue:** a worker starts another symbol when it finishes; one slow stock no longer holds up an entire batch.
- **Persistent compressed histories for every stock:** research and scanning share the same cache, including in-flight request deduplication.
- **Reuse valid scores:** skip unchanged benchmark-date/model-version results once that stock has been registered with the learner.
- Universe cached for 24 hours; completed history for 30 minutes, invalidated on the next India calendar day. Benchmark refresh is limited to 15 minutes.
- Provider failures have a short retry cooldown; HTTP 429 backs off instead of hammering another host. Permanent missing-symbol errors wait longer.
- Browser polling returns a small unchanged response when no scan state changed.
- Checkpoints happen every three seconds and at completion, outside the main status lock.

Default: 8 workers, configurable between 1 and 16 with `MENTALIST_SCAN_WORKERS`. A first full scan still depends on provider latency and availability; this does not turn the free daily feed into a real-time feed.

The server checks again every 30 minutes while running, even if the browser is closed. Reopening the app catches up after downtime. Partial-market rankings remain hidden unless explicitly requested; company order is interleaved rather than alphabetical.

### Forecasts that learn

Open **Prediction history** in the sidebar, or a stock's **Why?** panel.

1. The model observes completed price/volume history and records a 5-session and a 21-session expected net return.
2. It saves the original prediction, features, timestamp, model version and training count in `.scanner/learning.sqlite`.
3. The measurement starts at the first session open **strictly after the actual forecast issue date**, not after an old source-price date. This prevents retrospectively predicting an entry price already in the past.
4. Once the horizon finishes, the app records the actual adjusted open-to-open return and forecast error.
5. That completed label updates the model's coefficients. Earlier predictions are never revised to make them look better.

There is at most one outstanding prediction per stock/horizon. Repeated scans do not count the same outcome twice. Missing endpoint prices defer evaluation instead of silently shifting the horizon. Current-day and future bars are excluded.

The learner is a shared **online ridge regression** with fixed, bounded features: short/medium momentum, relative strength, long trend, volatility, volume and drawdown. Small sufficient-statistic matrices let it update incrementally without retraining from scratch. It warms up once per symbol on past, non-overlapping completed labels. Historical training is kept **separate** from forward-tested accuracy. Before 30 training labels it records a clearly marked no-price-change baseline.

Both predictions and actual results include an assumed 0.20% cost per side. The no-price-change benchmark uses the same costs. Predicted net log return is bounded to ±0.4 as an outlier guard, not as a claim that this is a safe return range.

The accuracy page reports mean absolute error, direction accuracy, sample count and error against that baseline, using the latest 200 resolved predictions per horizon. After 30 resolved predictions, stock cards can show a band based on the 90th percentile of previous absolute errors. This is a descriptive historical-error band, **not a calibrated confidence interval**.

Learning can improve or worsen accuracy. “Below baseline” is shown when its measured error is worse. Cross-stock observations are correlated, historical samples are selected from the current universe, and no profitable predictive edge has been established. Forecasts remain experimental paper research and do not override entry rules or place orders.

## Existing features

- Long-term strength, short-term boost and 60/40 combined technical scores.
- A separate two-stock short-term entry watch, allowed to show no qualifying entries.
- Full company names and exchange links; source-linked news checked on demand.
- Shared-budget whole-share allocation with stock exposure and planned-loss limits.
- Original transaction dates and prices, FIFO cost basis, fees, dividends, splits and progress snapshots.
- Opening-holdings snapshots when exact quantities/dates are not available; no invented trades.

Scores are technical screening measures, not probabilities or fundamental valuations. News is context rather than automatic headline sentiment. The data source is unofficial Yahoo daily history; today’s candle is excluded. NSE EQ stocks are covered, not BSE-only listings or every instrument series.

## Keep your existing portfolio

Use the same browser and `http://127.0.0.1:8765`; its existing ledger and opening-holdings storage keys are preserved. Export backups before changing browser, device or port. Opening-holdings backups restore through **Update holdings**; transaction backups through **Data & settings**. A private `portfolio-seed.js` from an earlier download can also be copied locally; it is ignored by git.

Keep `.scanner/` to preserve downloaded history and the learning record. It is ignored by git, as are database files, private seeds and downloaded snapshots. No portfolio values, credentials or market-data bundles are published in this repository.

## Test

Python and JavaScript suites use controlled fixtures and run without market access:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/core.test.js tests/allocation.test.cjs
python3 tests/benchmark_scanner.py
```

`tests/browser.cjs` uses Playwright/Chromium for development checks. Node and browser-test packages are not needed to run the application. `--no-scan` is a developer server flag that disables automatic scans.

See [TEST_REPORT.md](TEST_REPORT.md) for executed checks and performance limits.
