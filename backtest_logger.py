"""
backtest_logger.py
==================
Analisa os logs de telemetria gerados pelo tick_logger.py.

Gera relatórios que respondem a perguntas como:
  - "Quantos ticks Munich teve com p_ensemble > 0.5 mas sem bet?"
  - "Qual era o ask do bracket alvo quando o P(pico) chegou a 0.7?"
  - "Em que horas do dia o modelo está mais confiante?"
  - "Qual a distribuição de p_ensemble por cidade ao longo do dia?"
  - "Se tivéssemos apostado em todos os ticks com p > 0.55, qual seria o P&L?"
  - "Quantas bets cada cidade teve? Qual o win rate?"
  - "Quantas bets foram race/eod vs normal?"

Uso:
    python backtest_logger.py --city munich --date 2026-06-18
    python backtest_logger.py --city munich --last 7  # últimos 7 dias
    python backtest_logger.py --all --last 30         # todas as cidades, últimos 30 dias
    python backtest_logger.py --city munich --date 2026-06-18 --csv  # exportar para CSV
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev
from typing import Optional


LOG_DIR = Path("live_bot_logs") / "ticks"


def read_jsonl(path: Path) -> list[dict]:
    """Lê um ficheiro JSONL e retorna lista de records."""
    if not path.exists():
        return []
    records = []
    try:
        with path.open() as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return records


def get_dates_last_n(n: int) -> list[str]:
    """Retorna últimas N datas em formato YYYY-MM-DD."""
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(n)]


# ════════════════════════════════════════════════════════════════════
#  ANÁLISES
# ════════════════════════════════════════════════════════════════════

def analyze_city_day(city: str, date_str: str) -> dict:
    """Faz análise completa de 1 cidade num dia."""
    ticks = read_jsonl(LOG_DIR / f"ticks_{city}_{date_str}.jsonl")
    bets = read_jsonl(LOG_DIR / f"bets_{city}_{date_str}.jsonl")
    outcome = read_jsonl(LOG_DIR / f"outcomes_{city}_{date_str}.jsonl")

    result = {
        "city":          city,
        "date":          date_str,
        "n_ticks":       len(ticks),
        "n_bets":        len(bets),
        "has_outcome":   len(outcome) > 0,
        "outcome":       outcome[0] if outcome else None,
    }

    if not ticks:
        result["error"] = "sem ticks"
        return result

    # ── Estatísticas de p_ensemble ──
    p_values = [t.get("p_ensemble", 0) for t in ticks if t.get("p_ensemble") is not None]
    if p_values:
        result["p_ensemble"] = {
            "min":      min(p_values),
            "max":      max(p_values),
            "mean":     mean(p_values),
            "median":   median(p_values),
            "stdev":    stdev(p_values) if len(p_values) > 1 else 0,
            "n_above_threshold": sum(1 for p in p_values if p >= (ticks[0].get("threshold") or 0.65)),
            "n_above_05": sum(1 for p in p_values if p >= 0.5),
            "n_above_07": sum(1 for p in p_values if p >= 0.7),
            "n_ticks_total": len(p_values),
        }
    else:
        result["p_ensemble"] = None

    # ── Estatísticas de temperatura ──
    temps = [t.get("temp_now") for t in ticks if t.get("temp_now") is not None]
    if temps:
        result["temp"] = {
            "min":      min(temps),
            "max":      max(temps),
            "mean":     mean(temps),
            "first":    temps[0],
            "last":     temps[-1],
        }
    else:
        result["temp"] = None

    # ── Running max ao longo do dia ──
    rmax_values = [t.get("running_max") for t in ticks if t.get("running_max") is not None]
    if rmax_values:
        result["running_max"] = {
            "final":    rmax_values[-1],
            "max":      max(rmax_values),
            "first":    rmax_values[0],
        }
    else:
        result["running_max"] = None

    # ── Quase-sinais (p >= threshold*0.85 mas sem bet) ──
    threshold = ticks[0].get("threshold") or 0.65
    near_signals = []
    bought_tick = None
    for t in ticks:
        if t.get("bought") and bought_tick is None:
            bought_tick = t
        if (not t.get("bought")
            and t.get("p_ensemble", 0) >= threshold * 0.85
            and t.get("p_ensemble", 0) < threshold):
            near_signals.append({
                "ts":         t.get("ts"),
                "hhmm":       t.get("city_local_hhmm"),
                "p_ensemble": t.get("p_ensemble"),
                "gap":        round(threshold - t.get("p_ensemble", 0), 4),
                "temp":       t.get("temp_now"),
                "rmax":       t.get("running_max"),
            })
    result["near_signals"] = {
        "count":        len(near_signals),
        "first_5":      near_signals[:5],
        "last_5":       near_signals[-5:] if len(near_signals) > 5 else [],
    }

    # ── Race mode usage ──
    race_ticks = [t for t in ticks if t.get("race_active")]
    eod_ticks = [t for t in ticks if t.get("eod_active")]
    result["race_mode"] = {
        "ticks_with_race": len(race_ticks),
        "ticks_with_eod":  len(eod_ticks),
    }

    # ── Bets breakdown ──
    if bets:
        result["bets"] = []
        for b in bets:
            result["bets"].append({
                "ts":          b.get("ts"),
                "tick_count":  b.get("tick_count"),
                "trigger":     b.get("trigger", "normal"),
                "bracket":     b.get("bracket_label") or b.get("bracket"),
                "ask":         b.get("ask"),
                "size":        b.get("size_usdc"),
                "p_at_buy":    b.get("p_ensemble_at_buy"),
                "race_rank":   b.get("race_rank"),
            })

    # ── Erros ──
    error_ticks = [t for t in ticks if t.get("errors")]
    result["errors"] = {
        "n_ticks_with_errors": len(error_ticks),
        "sample_errors":       [err for t in error_ticks[:5] for err in t.get("errors", [])][:5],
    }

    # ── Mercado: evolucão do ask do bracket alvo ──
    target_asks = []
    for t in ticks:
        tb = t.get("target_bracket")
        if tb and tb.get("ask") is not None:
            target_asks.append({
                "ts":      t.get("ts"),
                "hhmm":    t.get("city_local_hhmm"),
                "label":   tb.get("label"),
                "ask":     tb.get("ask"),
                "bid":     tb.get("bid"),
                "p_ens":   t.get("p_ensemble"),
            })
    if target_asks:
        result["target_bracket_evolution"] = {
            "n_observations": len(target_asks),
            "first":          target_asks[0],
            "last":           target_asks[-1],
            "min_ask":        min(o["ask"] for o in target_asks),
            "max_ask":        max(o["ask"] for o in target_asks),
            "ask_at_peak_p":  max(target_asks, key=lambda o: o["p_ens"] or 0),
        }
    else:
        result["target_bracket_evolution"] = None

    # ── Distribuição de p_ensemble por hora ──
    p_by_hour: dict[int, list[float]] = defaultdict(list)
    for t in ticks:
        hhmm = t.get("city_local_hhmm")
        if hhmm and ":" in hhmm:
            h = int(hhmm.split(":")[0])
            p = t.get("p_ensemble")
            if p is not None:
                p_by_hour[h].append(p)
    result["p_by_hour"] = {
        str(h): {
            "n":     len(ps),
            "min":   min(ps),
            "max":   max(ps),
            "mean":  mean(ps),
        }
        for h, ps in sorted(p_by_hour.items())
    }

    return result


def print_report(analysis: dict) -> None:
    """Imprime relatório formatado de uma cidade/dia."""
    city = analysis.get("city", "?")
    date_str = analysis.get("date", "?")
    print(f"\n{'='*70}")
    print(f"  RELATÓRIO — {city.upper()} — {date_str}")
    print(f"{'='*70}")

    if analysis.get("error"):
        print(f"  ❌ {analysis['error']}")
        return

    print(f"\n  Ticks registados: {analysis['n_ticks']}")
    print(f"  Bets registadas:  {analysis['n_bets']}")
    print(f"  Outcome gravado:  {'✓' if analysis['has_outcome'] else '✗ (ainda não)'}")

    # Outcome
    if analysis.get("outcome"):
        o = analysis["outcome"]
        print(f"\n  📊 OUTCOME DO DIA:")
        print(f"     Temp max actual:     {o.get('temp_max_actual')}°C @ {o.get('temp_max_hour')}h")
        print(f"     Bracket resolvido:   {o.get('bracket_resolved')}")
        print(f"     Comprou:             {'✓' if o.get('bought') else '✗'}")
        print(f"     Win:                 {o.get('win')}")
        print(f"     P&L:                 ${o.get('pnl_total', 0):+.2f}")
        print(f"     Investido:           ${o.get('invested', 0):.2f}")
        print(f"     P(pico) máximo:      {o.get('p_ensemble_max')}")
        print(f"     P(pico) no buy:      {o.get('p_ensemble_at_buy')}")
        print(f"     P(pico) no pico temp:{o.get('p_ensemble_at_peak_temp')}")
        print(f"     Race usado:          {'✓' if o.get('race_used') else '✗'}")
        print(f"     EOD usado:           {'✓' if o.get('eod_used') else '✗'}")
        print(f"     Erros no dia:        {o.get('errors_count')}")

    # P(ensemble) stats
    p_stats = analysis.get("p_ensemble")
    if p_stats:
        print(f"\n  🧠 P(ENSEMBLE) — LightGBM:")
        print(f"     Mínimo:   {p_stats['min']:.4f}")
        print(f"     Máximo:   {p_stats['max']:.4f}")
        print(f"     Média:    {p_stats['mean']:.4f}")
        print(f"     Mediana:  {p_stats['median']:.4f}")
        print(f"     Std:      {p_stats['stdev']:.4f}")
        print(f"     Ticks acima do threshold ({p_stats.get('n_above_threshold', 0)}): "
              f"{p_stats['n_above_threshold']}/{p_stats['n_ticks_total']} "
              f"({100*p_stats['n_above_threshold']/max(p_stats['n_ticks_total'],1):.1f}%)")
        print(f"     Ticks com p>=0.50: {p_stats['n_above_05']}")
        print(f"     Ticks com p>=0.70: {p_stats['n_above_07']}")

    # Temperatura
    t_stats = analysis.get("temp")
    if t_stats:
        print(f"\n  🌡 TEMPERATURA:")
        print(f"     Min: {t_stats['min']:.1f}°C  Max: {t_stats['max']:.1f}°C  Média: {t_stats['mean']:.1f}°C")
        print(f"     Primeira obs: {t_stats['first']:.1f}°C  Última: {t_stats['last']:.1f}°C")

    rmax_stats = analysis.get("running_max")
    if rmax_stats:
        print(f"     Running max final: {rmax_stats['final']:.1f}°C")

    # Quase-sinais
    ns = analysis.get("near_signals", {})
    print(f"\n  ⚡ QUASE-SINAIS (p >= thr*0.85 mas < thr):")
    print(f"     Total: {ns.get('count', 0)} ticks")
    if ns.get("first_5"):
        print(f"     Primeiros 5:")
        for s in ns["first_5"]:
            print(f"       {s['hhmm']} p={s['p_ensemble']:.4f} (faltam {s['gap']*100:.1f}pts) "
                  f"temp={s['temp']}°C rmax={s['rmax']}°C")

    # Race/EOD
    rm = analysis.get("race_mode", {})
    print(f"\n  🏁 RACE/EOD MODE:")
    print(f"     Ticks com race activo: {rm.get('ticks_with_race', 0)}")
    print(f"     Ticks com EOD activo:  {rm.get('ticks_with_eod', 0)}")

    # Bets
    bets = analysis.get("bets", [])
    if bets:
        print(f"\n  💰 BETS DO DIA:")
        for b in bets:
            print(f"     {b['ts']} | {b.get('trigger', 'normal'):12s} | "
                  f"{b.get('bracket', '?'):15s} ask={b.get('ask', 0)*100:.0f}¢ "
                  f"${b.get('size', 0):.2f} | p={b.get('p_at_buy', 0):.3f}")
    else:
        print(f"\n  💰 BETS DO DIA: 0")

    # Target bracket evolution
    tbe = analysis.get("target_bracket_evolution")
    if tbe:
        print(f"\n  🎯 TARGET BRACKET EVOLUTION:")
        print(f"     Observações: {tbe['n_observations']}")
        print(f"     Primeira: {tbe['first']['hhmm']} label={tbe['first']['label']} "
              f"ask={tbe['first']['ask']*100:.0f}¢ (p={tbe['first']['p_ens']:.3f})")
        print(f"     Última:   {tbe['last']['hhmm']} label={tbe['last']['label']} "
              f"ask={tbe['last']['ask']*100:.0f}¢ (p={tbe['last']['p_ens']:.3f})")
        print(f"     Ask min/max: {tbe['min_ask']*100:.0f}¢ / {tbe['max_ask']*100:.0f}¢")
        print(f"     Ask no pico de P: {tbe['ask_at_peak_p']['ask']*100:.0f}¢ "
              f"(p={tbe['ask_at_peak_p']['p_ens']:.3f} @ {tbe['ask_at_peak_p']['hhmm']})")

    # Distribuição por hora
    pbh = analysis.get("p_by_hour", {})
    if pbh:
        print(f"\n  📅 DISTRIBUIÇÃO DE P(ENSEMBLE) POR HORA:")
        print(f"     {'Hora':<6} {'N':>4} {'Min':>8} {'Méd':>8} {'Max':>8}")
        for h, stats in pbh.items():
            print(f"     {h:<6} {stats['n']:>4} {stats['min']:>8.3f} "
                  f"{stats['mean']:>8.3f} {stats['max']:>8.3f}")

    # Erros
    errs = analysis.get("errors", {})
    if errs.get("n_ticks_with_errors", 0) > 0:
        print(f"\n  ⚠ ERROS:")
        print(f"     Ticks com erro: {errs['n_ticks_with_errors']}")
        for e in errs.get("sample_errors", [])[:3]:
            print(f"       - {e}")


def analyze_multi_day(city: str, dates: list[str]) -> dict:
    """Aggrega resultados de vários dias para uma cidade."""
    results = []
    for d in dates:
        a = analyze_city_day(city, d)
        if not a.get("error"):
            results.append(a)

    if not results:
        return {"city": city, "n_days": 0, "error": "sem dados"}

    summary = {
        "city":   city,
        "n_days": len(results),
        "dates":  [r["date"] for r in results],
    }

    # Aggregar outcomes
    outcomes = [r["outcome"] for r in results if r.get("outcome")]
    if outcomes:
        n_wins = sum(1 for o in outcomes if o.get("win"))
        n_losses = sum(1 for o in outcomes if o.get("win") is False)
        total_pnl = sum(o.get("pnl_total", 0) for o in outcomes)
        total_invested = sum(o.get("invested", 0) for o in outcomes)
        summary["outcomes"] = {
            "n_days_with_outcome": len(outcomes),
            "n_wins":              n_wins,
            "n_losses":            n_losses,
            "win_rate":            n_wins / max(n_wins + n_losses, 1) * 100,
            "total_pnl":           total_pnl,
            "total_invested":      total_invested,
            "roi_pct":             (total_pnl / total_invested * 100) if total_invested > 0 else 0,
            "n_buys_total":        sum(o.get("n_buys", 0) for o in outcomes),
            "n_days_bought":       sum(1 for o in outcomes if o.get("bought")),
            "n_days_race":         sum(1 for o in outcomes if o.get("race_used")),
            "n_days_eod":          sum(1 for o in outcomes if o.get("eod_used")),
        }

    # Aggregar p_ensemble stats
    p_means = []
    p_maxes = []
    near_signal_counts = []
    for r in results:
        if r.get("p_ensemble"):
            p_means.append(r["p_ensemble"]["mean"])
            p_maxes.append(r["p_ensemble"]["max"])
        if r.get("near_signals"):
            near_signal_counts.append(r["near_signals"]["count"])

    if p_means:
        summary["p_ensemble_aggregate"] = {
            "mean_of_means":   mean(p_means),
            "mean_of_maxes":   mean(p_maxes),
            "max_of_maxes":    max(p_maxes),
        }

    if near_signal_counts:
        summary["near_signals_aggregate"] = {
            "total":        sum(near_signal_counts),
            "mean_per_day": mean(near_signal_counts),
            "max_per_day":  max(near_signal_counts),
        }

    return summary


def print_multi_day_summary(summary: dict) -> None:
    """Imprime resumo multi-dia."""
    city = summary.get("city", "?")
    n_days = summary.get("n_days", 0)
    print(f"\n{'='*70}")
    print(f"  RESUMO MULTI-DIA — {city.upper()} — {n_days} dias")
    print(f"{'='*70}")

    if summary.get("error"):
        print(f"  ❌ {summary['error']}")
        return

    print(f"\n  Datas analisadas: {', '.join(summary.get('dates', []))}")

    if summary.get("outcomes"):
        o = summary["outcomes"]
        print(f"\n  📊 OUTCOMES:")
        print(f"     Dias com outcome:    {o['n_days_with_outcome']}")
        print(f"     Wins:                {o['n_wins']}")
        print(f"     Losses:              {o['n_losses']}")
        print(f"     Win rate:            {o['win_rate']:.1f}%")
        print(f"     P&L total:           ${o['total_pnl']:+.2f}")
        print(f"     Investido total:     ${o['total_invested']:.2f}")
        print(f"     ROI:                 {o['roi_pct']:+.1f}%")
        print(f"     Total de buys:       {o['n_buys_total']}")
        print(f"     Dias com buy:        {o['n_days_bought']}/{o['n_days_with_outcome']}")
        print(f"     Dias com race:       {o['n_days_race']}")
        print(f"     Dias com EOD:        {o['n_days_eod']}")

    if summary.get("p_ensemble_aggregate"):
        p = summary["p_ensemble_aggregate"]
        print(f"\n  🧠 P(ENSEMBLE) AGGREGATE:")
        print(f"     Média das médias diárias: {p['mean_of_means']:.3f}")
        print(f"     Média dos máximos diários:{p['mean_of_maxes']:.3f}")
        print(f"     Máximo absoluto:          {p['max_of_maxes']:.3f}")

    if summary.get("near_signals_aggregate"):
        ns = summary["near_signals_aggregate"]
        print(f"\n  ⚡ QUASE-SINAIS:")
        print(f"     Total:        {ns['total']}")
        print(f"     Média/dia:    {ns['mean_per_day']:.1f}")
        print(f"     Máximo/dia:   {ns['max_per_day']}")


def export_csv(city: str, dates: list[str], output_path: Path) -> None:
    """Exporta todos os ticks para CSV para análise externa."""
    rows = []
    for d in dates:
        ticks = read_jsonl(LOG_DIR / f"ticks_{city}_{d}.jsonl")
        for t in ticks:
            tb = t.get("target_bracket") or {}
            rows.append({
                "ts":                 t.get("ts"),
                "city":               t.get("city"),
                "date":               t.get("date"),
                "city_local_hhmm":    t.get("city_local_hhmm"),
                "tick_count":         t.get("tick_count"),
                "temp_now":           t.get("temp_now"),
                "running_max":        t.get("running_max"),
                "slots_count":        t.get("slots_count"),
                "p_ensemble":         t.get("p_ensemble"),
                "p_lgbm":             t.get("p_lgbm"),
                "threshold":          t.get("threshold"),
                "bought":             t.get("bought"),
                "stop_loss_hit":      t.get("stop_loss_hit"),
                "forecast_wu":        t.get("forecast_wu"),
                "target_bracket_label": tb.get("label"),
                "target_bracket_ask":   tb.get("ask"),
                "target_bracket_bid":   tb.get("bid"),
                "market_volume":      t.get("market_volume"),
                "race_active":        t.get("race_active"),
                "eod_active":         t.get("eod_active"),
            })

    if not rows:
        print(f"  Sem dados para exportar")
        return

    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {len(rows)} linhas exportadas para {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Analisa logs de telemetria do live_bot.")
    parser.add_argument("--city", type=str, default=None,
                        help="Cidade (ex: munich). Se omisso, --all required.")
    parser.add_argument("--all", action="store_true",
                        help="Analisar todas as cidades com logs.")
    parser.add_argument("--date", type=str, default=None,
                        help="Data específica YYYY-MM-DD")
    parser.add_argument("--last", type=int, default=1,
                        help="Analisar últimos N dias (default 1)")
    parser.add_argument("--csv", action="store_true",
                        help="Exportar ticks para CSV")
    parser.add_argument("--csv-path", type=str, default=None,
                        help="Caminho do CSV (default: ticks_{city}.csv)")
    args = parser.parse_args()

    # Determinar cidades
    if args.all:
        cities = set()
        if LOG_DIR.exists():
            for p in LOG_DIR.glob("ticks_*_*.jsonl"):
                # ticks_{city}_{date}.jsonl
                parts = p.stem.split("_")
                if len(parts) >= 3:
                    cities.add("_".join(parts[1:-1]))
        cities = sorted(cities)
    elif args.city:
        cities = [args.city]
    else:
        parser.error("Especifica --city NAME ou --all")

    # Determinar datas
    if args.date:
        dates = [args.date]
    else:
        dates = get_dates_last_n(args.last)

    print(f"\nAnalisando {len(cities)} cidade(s) x {len(dates)} dia(s) = {len(cities)*len(dates)} combinações")

    for city in cities:
        if args.last > 1:
            # Multi-dia: mostrar resumo
            summary = analyze_multi_day(city, dates)
            print_multi_day_summary(summary)
        else:
            # 1 dia: mostrar detalhe
            for d in dates:
                analysis = analyze_city_day(city, d)
                print_report(analysis)

        # Export CSV se pedido
        if args.csv:
            csv_path = Path(args.csv_path or f"ticks_{city}.csv")
            export_csv(city, dates, csv_path)


if __name__ == "__main__":
    main()
