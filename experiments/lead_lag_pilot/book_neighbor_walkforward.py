#!/usr/bin/env python3
"""Exploratory walk-forward: target features plus next higher bracket."""
import csv,datetime as dt,math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
base=Path(__file__).resolve().parent
timing={(r['city'],r['day']):r for r in csv.DictReader((base/'gamma_label_times.csv').open()) if r['status']=='proxy_available'}
neighbors={(r['city'],r['day']):r for r in csv.DictReader((base/'book_neighbor_features.csv').open()) if r['status']=='provisional'}
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional' and (r['city'],r['day']) in timing and (r['city'],r['day']) in neighbors]
def features(r,kind):
    city=float(r['city']=='munich'); bid=float(r['best_bid']); ask=float(r['best_ask']); weather=float(r['running_max']); depth=math.log1p(float(r['ask_depth_top5_usdc'])); n=neighbors[(r['city'],r['day'])]; nb=float(n['neighbor_bid']); na=float(n['neighbor_ask'])
    common=[city,(bid+ask)/2,ask-bid,depth]; return common+([weather] if kind.startswith('H') else [])+([(nb+na)/2,na-nb] if kind.endswith('neighbor') else [])
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','decision_utc','method','y','p','train_rows','train_dates','train_positive','latest_gamma_proxy_utc'])
for test in sorted(rows,key=lambda r:r['decision_utc']):
    decision=dt.datetime.fromisoformat(test['decision_utc']); train=[r for r in rows if r['day']<test['day'] and dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc'])<=decision]; y=np.array([int(r['outcome_gamma_yes']) for r in train]); n_dates=len({r['day'] for r in train})
    if n_dates<30 or sum(y)<5 or len(y)-sum(y)<5:continue
    pred={'midpoint':(float(test['best_bid'])+float(test['best_ask']))/2}
    for kind in ('M_current','M_neighbor','H_current','H_neighbor'):
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(np.array([features(r,kind) for r in train]),y); pred[kind]=float(model.predict_proba(np.array([features(test,kind)]))[0,1])
    latest=max(dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc']) for r in train)
    for kind,p in pred.items():w.writerow([test['city'],test['day'],test['decision_utc'],kind,test['outcome_gamma_yes'],round(float(np.clip(p,1e-6,1-1e-6)),9),len(train),n_dates,int(sum(y)),latest.isoformat()])
