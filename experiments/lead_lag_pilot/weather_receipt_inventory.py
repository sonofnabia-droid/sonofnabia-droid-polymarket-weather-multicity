#!/usr/bin/env python3
"""Inventory archived AWC timestamp fields; no assumed publication semantics."""
import csv,datetime as dt,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(root))
from noaa_metar_eligibility_audit import parse_report
w=csv.writer(sys.stdout); w.writerow(['city','observation_utc','awc_receipt_field_utc','collector_run_start_utc','receipt_minus_observation_min','run_start_minus_receipt_min','report_kind','temp_method','report_temp_c','raw_json_temp_c','timing_note'])
with (root/'forecast_benchmark'/'metar_raw.jsonl').open() as f:
    for line in f:
        try:
            r=json.loads(line); city=r.get('city')
            if city not in ('lucknow','munich'):continue
            obs=dt.datetime.fromtimestamp(int(r['obs_time']),dt.timezone.utc); receipt=dt.datetime.fromisoformat(r['raw']['receiptTime'].replace('Z','+00:00')); start=dt.datetime.fromisoformat(r['collected_utc'].replace('Z','+00:00'))
            if start<dt.datetime.fromisoformat('2026-11-14T20:38:00+00:00'):continue
            kind,corrected,temp,method=parse_report(r['raw'].get('rawOb'),r['icao'])
            w.writerow([city,obs.isoformat(),receipt.isoformat(),start.isoformat(),round((receipt-obs).total_seconds()/60,3),round((start-receipt).total_seconds()/60,3),kind,method,temp if temp is not None else '',r['raw'].get('temp',''),'receiptTime semantics unverified; run start precedes HTTP response'])
        except (ValueError,KeyError,TypeError):continue
