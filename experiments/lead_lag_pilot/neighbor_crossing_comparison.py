#!/usr/bin/env python3
"""Paired target-vs-next-bracket price changes around historical METAR crossings.

Exploratory only: prices are historical points, weather timestamps are not
publication times, and no settlement outcomes are read. SQLite is read-only.
"""
import csv
import datetime as dt
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'experiments' / 'lead_lag_pilot'
DB = sqlite3.connect(f'file:{ROOT / "data/polymarket_weather_2026.sqlite"}?mode=ro', uri=True)
DB.execute('PRAGMA query_only=ON')
bracket_re = re.compile(r'(-?\d+)°C(?: or (below|higher))?')
events = csv.DictReader((BASE / 'all_crossings.csv').open(newline=''))
out = csv.writer(sys.stdout)
out.writerow(['city','day','obs_utc','target_bracket','control_bracket','horizon_min',
              'target_price','target_price_utc','control_price','control_price_utc',
              'target_delta_from_0','control_delta_from_0','paired_delta_difference',
              'target_age_sec','control_age_sec','pair_skew_sec','status'])

def quote(token, cutoff):
    if not token or not cutoff:
        return None
    stamp = int(dt.datetime.fromisoformat(cutoff).timestamp())
    return DB.execute('''SELECT ts,price FROM price_points
                         WHERE token_id=? AND fidelity_minutes=5 AND ts BETWEEN ? AND ?
                         ORDER BY ts DESC LIMIT 1''', (token, stamp-600, stamp)).fetchone()

for event in events:
    city, day = event['city'], event['day']
    try:
        target_label = event['bracket']
        target_match = bracket_re.fullmatch(target_label)
        if not target_match:
            continue
        target_upper = int(target_match.group(1))
        rows = DB.execute('''SELECT m.bracket,t.outcome,t.token_id
                             FROM markets m JOIN tokens t ON t.market_id=m.market_id
                             WHERE m.city=? AND m.market_date=? AND t.outcome='YES' ''',
                          (city, day)).fetchall()
        token_by_label = {label: token for label, outcome, token in rows}
        labels = []
        for label in token_by_label:
            match = bracket_re.fullmatch(label or '')
            if match and match.group(2) != 'higher':
                labels.append((int(match.group(1)), label))
        next_label = min((label for upper, label in labels if upper > target_upper),
                         key=lambda label: int(bracket_re.fullmatch(label).group(1)), default='')
        if not next_label:
            continue
        target_token, control_token = token_by_label.get(target_label), token_by_label.get(next_label)
        points = {}
        for horizon, time_field in [(0,'yes0_utc'), (5,'yes5_utc'),
                                    (10,'yes10_utc'), (15,'yes15_utc')]:
            cutoff = event.get(time_field, '')
            points[horizon] = (cutoff, quote(target_token, cutoff), quote(control_token, cutoff))
        base_t = points[0][1][1] if points[0][1] else None
        base_c = points[0][2][1] if points[0][2] else None
        for horizon, (cutoff, tq, cq) in points.items():
            td = tq[1]-base_t if tq and base_t is not None else None
            cd = cq[1]-base_c if cq and base_c is not None else None
            dd = td-cd if td is not None and cd is not None else None
            age_t = int(dt.datetime.fromisoformat(cutoff).timestamp())-tq[0] if cutoff and tq else ''
            age_c = int(dt.datetime.fromisoformat(cutoff).timestamp())-cq[0] if cutoff and cq else ''
            skew = abs(tq[0]-cq[0]) if tq and cq else ''
            status = ('missing_pair' if td is None or cd is None else
                      'paired' if skew <= 60 else 'timestamp_skew')
            out.writerow([city,day,event['obs_utc'],target_label,next_label,horizon,
                          tq[1] if tq else '',dt.datetime.fromtimestamp(tq[0],dt.timezone.utc).isoformat() if tq else '',
                          cq[1] if cq else '',dt.datetime.fromtimestamp(cq[0],dt.timezone.utc).isoformat() if cq else '',
                          round(td,6) if td is not None else '',round(cd,6) if cd is not None else '',
                          round(dd,6) if dd is not None else '',age_t,age_c,skew,status])
    except (KeyError, ValueError, TypeError):
        continue
DB.close()
