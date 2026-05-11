# ZAI Bug Fixes

This document summarizes the fixes that were actually applied across the
multi-city Polymarket temperature bot.

It is a consolidation of the bugfix rounds already committed in this repo.

## Live bot and bootstrap

- Fixed `live_bot.py --run paper` startup failure by always defining
  `private_key` before building `ClobClient`.
- Aligned market slug handling so live orders, logs, and anti-dup checks use
  the same Polymarket slug format.
- Aligned bracket selection parity around `floor(running_max)` in live,
  backtest, and calibration paths.
- Added a safer market fetch path with 10-minute buckets instead of only hourly
  refreshes.
- Reduced CLOB orderbook enrichment to a small candidate window instead of
  enriching every bracket on every tick.
- Added fresh orderbook peek before order submission in live execution.
- Added retry for bootstrap when the API is temporarily unavailable.
- Filtered bootstrap Open-Meteo rows so future forecast hours are not treated
  as past observations.
- Added protection against late-arriving observations inflating the running
  max after a buy has already happened.
- Added `series_today` keys that survive duplicate hours / DST cases.
- Added state restoration for restart-in-the-middle-of-day scenarios.
- Restored internal `SingleEntry` state after duplicate detection.
- Made Telegram alerts fire-and-forget so they do not block the main loop.

## Predictor and weather

- Removed mutable city globals from predictor inference paths.
- Kept seasonal prior lookup explicit through `seasonal_prior_map`.
- Aligned `compute_prev7()` with backtester behavior and pruned old history.
- Added sane fallback behavior when `history_max` is empty on the first day.
- Added a plausibility filter for temperature spikes before they can corrupt
  live state or backtest input.
- Fixed WU wind parsing so `0.0 km/h` is not replaced by the default value.
- Added a sanity check for WU temperature scale mismatches.
- Ensured bootstrap slots carry explicit dates for downstream history writes.

## Backtester and calibration

- Fixed `round()` vs `floor()` parity for running max bracket selection.
- Fixed percent sizing so bankroll below the minimum does not force a fake
  $5 bet.
- Fixed stop-loss PnL accounting and aligned it with share math.
- Added fee-aware PnL handling to backtest calculations.
- Reduced backtester market generation to only relevant brackets.
- Fixed duplicate/legacy market rows in the backtest data loader.
- Fixed calibration to use the same bracket semantics as live/backtest.
- Reworked calibration so the realistic market path does not invent prices
  from model output.
- Added a penalty for short calibration windows to reduce overfitting.

## Polymarket CLOB and persistence

- Removed the global HTTP monkey patch and kept the public orderbook fallback
  local to the client.
- Made `PositionManager._save()` atomic with a temp file and `os.replace()`.
- Preserved live/paper position metadata consistently, including `token_id`,
  `market_slug`, and `strategy`.
- Added a best-effort fill-size extraction path for live orders.
- Aligned buy/sell execution to tick size before order submission.
- Moved live execution to GTC for the current code path.
- Added a local anti-duplicate check inside the CLOB client.
- Applied taker fee handling in buy/sell and paper settlement PnL.
- Added `token_id` to simulated brackets so backtest/live schemas stay closer.

## Dashboard and observability

- Fixed the Flask dashboard header to show capital fields in paper mode.
- Updated the dashboard cards and panels to distinguish monitoring,
  resolved, and active markets more clearly.
- Added API key protection for the dashboard when configured.
- Fixed terminal dashboard rendering to avoid noisy clear-screen behavior.
- Improved Telegram startup/status alerts.

## Remaining known follow-ups

These are still worth revisiting before real-money trading:

- Overlapping tick protection is still worth hardening further.
- Explicit CLOB HTTP client timeout injection is not yet enforced end-to-end.
- Rate-limit backoff / Retry-After handling is still a future improvement.
- The GTC fill accounting path is best-effort, not a full exchange simulator.

## Current read on PAPER

For `--run paper`, the bot is in a usable state and there are no known
release-blocking syntax or startup issues in the current code.

For `--run real`, I would treat the four follow-ups above as the main remaining
risks and keep a small paper soak test before moving money.
