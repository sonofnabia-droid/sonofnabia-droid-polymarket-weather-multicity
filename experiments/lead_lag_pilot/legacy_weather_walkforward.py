#!/usr/bin/env python3
"""Exploratory incremental weather features with Gamma timestamp proxy."""
import csv,datetime as dt,math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
base=Path(__file__).resolve().parent
timing={(r['city'],r['day']):r for r in csv.DictReader((base/'gamma_label_times.csv').open()) if r['status']=='proxy_available'}
weather={(r['city'],r['day']):r for r in csv.DictReader((base/'legacy_weather_features.csv').open()) if r['status']=='provisional'}
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional' and (r['city'],r['day']) in timing and (r['city'],r['day']) in weather]
def features(r,kind):
    wx=weather[(r['city'],r['day'])]; city=float(r['city']=='munich'); bid=float(r['best_bid']); ask=float(r['best_ask']); book=[(bid+ask)/2,ask-bid,math.log1p(float(r['ask_depth_top5_usdc']))]; temp=[float(wx['running_max'])]; extra=[float(wx['temp_below_max']),float(wx['warming_1h']),float(wx['minutes_since_last_max'])]
    return [city]+(book if kind.startswith('H') or kind=='M_book' else [])+(temp if kind!='M_book' else [])+(extra if kind.endswith('full') else [])
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','decision_utc','method','y','p','train_rows','train_dates','train_positive','latest_gamma_proxy_utc'])
for test in sorted(rows,key=lambda r:r['decision_utc']):
    decision=dt.datetime.fromisoformat(test['decision_utc']); train=[r for r in rows if r['day']<test['day'] and dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc'])<=decision]; y=np.array([int(r['outcome_gamma_yes']) for r in train]); days=len({r['day'] for r in train})
    if days<30 or sum(y)<5 or len(y)-sum(y)<5:continue
    predictions={'midpoint':(float(test['best_bid'])+float(test['best_ask']))/2}
    for kind in ('M_book','W_base','W_full','H_base','H_full'):
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(np.array([features(r,kind) for r in train]),y); predictions[kind]=float(model.predict_proba(np.array([features(test,kind)]))[0,1])
    latest=max(dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc']) for r in train)
    for name,p in predictions.items():w.writerow([test['city'],test['day'],test['decision_utc'],name,test['outcome_gamma_yes'],round(float(np.clip(p,1e-6,1-1e-6)),9),len(train),days,int(sum(y)),latest.isoformat()])
