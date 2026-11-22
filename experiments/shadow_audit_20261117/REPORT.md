# Shadow audit — temporal provenance and fees

**Date:** 2026-11-17  
**Scope:** read-only audit of `opportunity_logger.py`, `shadow_ledger.py`, local winner cache and fee implementations. No SQLite access, downloads, bot/config changes, or writes to source data.

## Executive finding

The existing shadow outcomes are useful for exploratory price-band screening, but they cannot support an entry-hour study. `opportunity_logger.py` timestamps the hourly log collection (`captured_at`), not the original blocked trade line; its own header says approximately ±1 hour. `shadow_ledger.py` then associates the opportunity to the nearest collector quote within ±90 minutes and ±1.5¢. In the 589 resolved numeric observations inspected, `matched_ts` was 30.8 minutes from `captured_at` at the median, 71.7 minutes at p90, and 89.6 minutes maximum. The median absolute ask difference was 0.9¢.

Therefore:

- Do not classify these events by local hour using `captured_at`.
- `matched_ts` is a nearby orderbook sample, not the signal timestamp. It may describe market state near the opportunity, not the bot's exact decision time.
- `matched_ask` is a collector observation selected under the matching tolerance; it is not proof of an executable fill, available depth, or queue position.
- The log lacks a structured event timestamp plus contemporaneous `p_rebound`, running maximum, selected bracket and gate reasons. Existing records cannot reconstruct these fields safely.

## Sample structure

The examined set contains **589 resolved numeric contract–bracket candidates** across **352 unique slugs/city-days**. There are 150 slugs with multiple bracket candidates (up to six). `shadow_ledger.py` already deduplicates by `(city, slug, bracket_lo)`, but candidates from one slug share the same settlement outcome and are correlated. A candidate row is not an independent contract, and the data do not encode a pre-registered rule for choosing one bracket when several were blocked.

Settlement labels came from `live_bot_logs/market_winners.json`; this audit did not verify each contract's official settlement source or rounding rule. Only numeric winners were retained, matching the existing dashboard endpoint's limitation.

## Fee reconciliation

Three local implementations were compared:

| Location | Implemented formula |
|---|---|
| `polymarket_clob.py` | Weather taker fee = `0.05 × p × (1−p) × shares` |
| `dashboard/server.py` | Per-share fee = `0.05 × p × (1−p)` |
| `shadow_ledger.py` | `FEE = 0.009`; report subtracts `0.009 × p` per share |

Polymarket Help Center's Trading Fees page (dated 2026-07-10) specifies `C × feeRate × p × (1−p)`, Weather taker rate 0.05, and zero maker fee. That matches the CLOB helper and dashboard formula, not the `shadow_ledger.py` report. The market's applicable fee configuration should still be checked where it is exposed; do not use the stale 0.009 constant for Weather taker EV.

For the 589 candidate rows, fixed-price outcomes using the official Weather fee assumption are:

| Assumed entry price | Mean hit rate | Row-weighted EV/share after fee | Fee in `shadow_ledger.py` | Weather fee formula |
|---:|---:|---:|---:|---:|
| 0.65 | 37.86% | −28.277¢ | 0.585¢ | 1.137¢ |
| 0.71 | 37.86% | −34.169¢ | 0.639¢ | 1.030¢ |
| 0.83 | 37.86% | −45.845¢ | 0.747¢ | 0.706¢ |

Rows within a slug were also clustered for uncertainty, averaging candidate outcomes within each slug before resampling 352 slugs (10,000 bootstrap draws). The corresponding descriptive cluster means and 95% intervals were −20.49¢ [−24.84, −16.05] at 0.65, −26.38¢ [−30.78, −21.97] at 0.71, and −38.06¢ [−42.39, −33.65] at 0.83. This is **not a deployable policy estimate**: it averages multiple candidate brackets per contract and does not model a choice rule, executable ask, depth, slippage, or fills. It only confirms that this particular candidate set does not show positive EV under the tested fixed prices.

The fixed-price 0.65/0.71/0.83 outcomes are hypothetical prices; the logger's observed `ask_at_fire` values and nearest collector prices are not execution evidence. Official fee reference: [Polymarket Help Center — Trading Fees](https://help.polymarket.com/en/articles/13364478-trading-fees).

## Operational status check

At the check on 2026-11-17, `tmux list-sessions` could not connect because no tmux server/socket was present. A privileged process listing did not show an active named Python bot, collector, or dashboard process (one generic Python PID disappeared before inspection). Thus A/B/C, `pm_books`, D REAL, D PAPER and the dashboard could not be independently confirmed as running. No process was started or stopped. Treat service status as **unverified**, not as proof that a specific bot is stopped.

## Next experiment, safe and causal

1. Keep the existing 589-row report as price-band screening only; no time-of-day conclusions.
2. Report candidate outcomes by city and broad price band with slug-cluster uncertainty, while clearly exposing the unresolved multi-bracket selection rule.
3. Analyze `matched_ts`/`matched_ask` only as approximate market-snapshot context, retaining the time-match lag and quote-age fields; do not call this the bot's entry timestamp or an executable price.
4. For future hour-window and gate-reason research, require structured opportunity events containing the original event timestamp, local timezone, model outputs, observed/running maximum, target bracket, exact decision reason, market snapshot timestamp and bid/ask/depth. Any instrumentation change to a running bot requires explicit approval.
5. Reconcile fee rate per relevant market/contract before any updated performance claim. Do not change `shadow_ledger.py` in place as part of this audit.

## Reproducibility note

Calculations read JSONL/cache files in place and used the locally configured Python standard library only. Bootstrap seed: `20261117`; 10,000 cluster resamples. No outputs were written to logs, market data, SQLite or bot state.
