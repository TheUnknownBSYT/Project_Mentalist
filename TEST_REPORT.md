# Verification — 22 September 2026

- 45 Python tests passed: server access boundaries, scanner scheduling/cache, quote parsing, previous-close changes, failed-refresh retention, immutable forecasts, no future leakage, single learning updates, completed-session timing and adaptive weighting.
- 32 JavaScript tests passed: FIFO ledger, fees, splits, capital limits, historical execution timing, data validation and allocation.
- Browser checks passed: startup, forecast history/cards, share-quantity setup, a controlled 90-share × ₹10 daily change = ₹900, portfolio valuation, research chooser, removal of bulk watchlist input, mobile overflow and absence of JavaScript page errors.

Live COALINDIA quote verification timed out in this environment. No actual current price is claimed verified. Provider-dependent end-to-end quote delivery must be checked on the user's network. Tests use clearly isolated fixtures, not production quote substitutions.

Mac launchd and Windows login installers were not executed on their target operating systems here. Linux service instructions were not deployed to a remote host. Automatic startup requires running the installer on the user's device. These checks establish application behavior, not profitable forecasts.
