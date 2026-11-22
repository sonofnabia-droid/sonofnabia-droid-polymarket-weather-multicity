# Exit management — shadow protocol V01

**Date frozen:** 2026-11-16 UTC  
**Scope:** Munich and Lucknow; existing PAPER entries from A/B/C only.  
**Mode:** offline/shadow, read-only. No order submission, no changes to bots, services, collector, or SQLite.  
**Status:** protocol prepared; executable orderbook coverage is currently absent for the audited PAPER positions.

## Research question

Does an exit rule improve net outcomes or reduce downside relative to holding the same PAPER YES position to verified contract settlement, after realistic bid-side depth, fees, and latency? An exit is evaluated on the same entry positions as the hold baseline. The experiment does not compare different entry selection rules.

## Frozen arms

1. **HOLD:** retain the position to independently checked contract settlement.
2. **TP-0.95:** first recorded CLOB snapshot after entry where the held token's best bid is at least 0.95; simulate a limit sale at 0.95, consuming only visible bid levels priced at or above 0.95.
3. **STOP-0.50:** first recorded CLOB snapshot after entry where best bid is at most 0.50; simulate a marketable sale, consuming visible bids from best to worst.
4. **COMBINED:** act on whichever of TP-0.95 or STOP-0.50 occurs first. One trigger is terminal for the filled quantity; any unfilled remainder stays open and continues under HOLD unless separately specified before the next cohort.

These thresholds are the user's proposed exploratory levels and remain fixed for this protocol. They will not be retuned against the exposed 2026 sample.

## Signal and execution accounting

- Use `book_snapshots.sampled_at` for event ordering and the held `token_id`; never trigger on YES marks, Gamma quotes, or the opposite token.
- At the first qualifying snapshot, walk the visible bid ladder and cap simulated fills at the PAPER position's remaining shares. For TP, only bids ≥0.95 are eligible; for the stop, all visible bids are eligible. Record partial fills and unfilled remainder separately. The book is a snapshot, so this is a conditional fill estimate, not proof of a real queue fill.
- Preserve all levels and quote timestamps. Record the best bid, total visible depth, depth at/above the TP limit, simulated filled shares, average execution price, and residual shares.
- Apply verified contract fees to fills. Until the applicable fee rule is sourced and implemented, report gross execution scenarios separately and make no net-edge claim.
- Stress latency by applying the first available later snapshot at +1 sampling interval and +2 intervals (nominally 5 and 10 minutes). If the data cannot identify an actual sampling time, do not use the tick logger's write time as a substitute.
- No temperature-triggered exit in V01. Add one only after recording source, observation time, publication/availability time, and contract eligibility causally.

## Baseline and outcomes

- Pair each exit arm with HOLD on identical entries, position size, and event-day exposure.
- Resolve only from the applicable contract's documented settlement source and precision. Keep disagreement between PAPER, Gamma metadata, and source records explicit; unresolved cases are excluded from the primary comparison and reported separately.
- Report paired net P&L, return on capital actually tied up, drawdown by event day, peak-to-trough duration, time to exit, exposure-hours, fills/partial fills, and coverage. Include a no-reinvestment comparison and a clearly separated capital-redeployment scenario; do not assume proceeds were reinvested profitably.
- Bootstrap paired differences by unique city-day, not by token or repeated bot entry. Show per-city results and the full distribution; do not optimize solely on hit rate.
- Do not claim independent validation from any entry/outcome already examined in this discovery. The 26-entry 2026 sample is exploratory only.

## Prospective eligibility and reporting

A position is eligible for the primary execution analysis only if the held token has timestamped CLOB bids after entry through settlement, the sample timestamps are ordered and interpretable, and position size can be compared with visible depth. Missing books, gaps, and stale observations are coverage outcomes, never zero prices or assumed fills.

Before opening labels for a new cohort, freeze this script/version, the thresholds, fee source, latency stress, exclusions, and report metrics. Keep a new future date range untouched until this freeze. At review, require positive paired net improvement for any promotion, with drawdown no worse than HOLD under a predeclared tolerance and adequate event-day coverage. Otherwise retain HOLD and document rejection or inconclusiveness. PAPER A/B/C remain the operational reference; this protocol creates no order instructions.

## Current data gate

The audited 26 PAPER entries have zero post-entry `book_snapshots` in SQLite. The two Lucknow tick books from 11–12/11 have no per-book `sampled_at` and are not eligible. At the latest check on 2026-11-16 12:13 UTC, no snapshot had been written in the preceding two hours for the 44 Munich/Lucknow tokens of that date. Therefore V01 is frozen as a protocol, but no executable shadow result can yet be produced from the current archive.
