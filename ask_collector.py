"""
ask_collector.py — snapshot dos order books das brackets de temperatura.
Corre em loop; grava ask_collector_data.csv (append, à prova de restart).

Uso:
    python ask_collector.py --cities munich,london --interval 3600
"""
import argparse, csv, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from cities.config import get_city

GAMMA = "https://gamma-api.polymarket.com"
CLOB_BOOK = "https://clob.polymarket.com/book"
CSV_PATH = Path("ask_collector_data.csv")
FIELDS = ["ts", "city", "hour_local", "slug", "bracket", "temp_lo", "temp_hi",
          "gamma_price", "best_bid", "best_ask", "spread", "ask_depth_usdc"]

def get_book(token_id):
    """Book público — curl_cffi (Cloudflare) com fallback requests."""
    try:
        from curl_cffi import requests as rq
        r = rq.get(CLOB_BOOK, params={"token_id": token_id}, timeout=15, impersonate="chrome")
    except ImportError:
        import requests as rq
        r = rq.get(CLOB_BOOK, params={"token_id": token_id}, timeout=15)
    if r.status_code != 200:
        return None
    d = r.json()
    def side(k):
        lv = d.get(k) or []
        return sorted([(float(x.get("price", x.get("p", 0))),
                        float(x.get("size", x.get("q", 0)))) for x in lv],
                      key=lambda t: t[0])
    bids, asks = side("bids"), side("asks")
    return {"bid": bids[-1][0] if bids else None,
            "ask": asks[0][0] if asks else None,
            "ask_depth": round(sum(p * s for p, s in asks[:5]), 2)} if (bids or asks) else None

def fetch_market(slug):
    import requests
    r = requests.get(f"{GAMMA}/events", params={"slug": slug}, timeout=15)
    ev = r.json()
    if not ev:
        return None
    event = ev[0] if isinstance(ev, list) else ev
    import json as _json
    def _parse_price(v):
        import json as _j
        try:
            if isinstance(v, str):
                v = _j.loads(v)
            if isinstance(v, (list, tuple)) and v:
                x = v[0]
                return float(x)               # json.loads ja tirou as aspas
        except (TypeError, ValueError, IndexError):
            pass
        return None

    out = []
    for m in event.get("markets", []):
        tids = m.get("clobTokenIds", "[]")
        tids = _json.loads(tids) if isinstance(tids, str) else (tids or [])
        if not tids:
            continue
        out.append({"label": m.get("groupItemTitle") or m.get("question", "?"),
                    "token": tids[0],
                    "price": _parse_price(m.get("outcomePrices")) or 0.5})
    return out

def snapshot(city_name):
    city = get_city(city_name)
    now = datetime.now(ZoneInfo(city.timezone))
    slug = f"{city.polymarket_slug_pfx}-{['january','february','march','april','may','june','july','august','september','october','november','december'][now.month-1]}-{now.day}-{now.year}"
    brackets = fetch_market(slug)
    rows = []
    for b in (brackets or []):
        book = get_book(b["token"]) if b["token"] else None
        rows.append({"ts": datetime.now(timezone.utc).isoformat(), "city": city_name,
                     "hour_local": now.hour, "slug": slug, "bracket": b["label"],
                     "temp_lo": "", "temp_hi": "",
                     "gamma_price": b["price"],
                     "best_bid": book["bid"] if book else "",
                     "best_ask": book["ask"] if book else "",
                     "spread": round(book["ask"] - book["bid"], 4) if book and book["ask"] and book["bid"] else "",
                     "ask_depth_usdc": book["ask_depth"] if book else ""})
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", required=True)
    ap.add_argument("--interval", type=int, default=3600)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cities = [c.strip().lower() for c in args.cities.split(",")]

    first = not CSV_PATH.exists()
    while True:
        n = 0
        for c in cities:
            try:
                rows = snapshot(c)
                with open(CSV_PATH, "a", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDS)
                    if first:
                        w.writeheader(); first = False
                    w.writerows(rows)
                n += len(rows)
                print(f"[{datetime.now(timezone.utc):%H:%M}] {c}: {len(rows)} brackets registadas")
            except Exception as e:
                print(f"[{datetime.now(timezone.utc):%H:%M}] {c}: ERRO {e}")
        if args.once:
            break
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
