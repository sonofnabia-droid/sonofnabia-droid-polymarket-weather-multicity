#!/usr/bin/env python3
"""Exploratory feature ablation with archived Gamma label timestamp proxy."""
import csv,datetime as dt,math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
base=Path(__file__).resolve().parent
timing={(r['city'],r['day']):r for r in csv.DictReader((base/'gamma_label_times.csv').open()) if r['status']=='proxy_available'}
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional' and (r['city'],r['day']) in timing]
def features(r,kind):
    city=float(r['city']=='munich'); bid=float(r['best_bid']); ask=float(r['best_ask']); mid=(bid+ask)/2; spread=ask-bid; depth=math.log1p(float(r['ask_depth_top5_usdc'])); temp=float(r['running_max'])
    return {'M_price':[city,mid],'M_spread':[city,mid,spread],'M_depth':[city,mid,depth],'M_both':[city,mid,spread,depth],'H_price':[city,temp,mid],'H_both':[city,temp,mid,spread,depth]}[kind]
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','decision_utc','method','y','p','train_dates','train_rows','latest_proxy_utc'])
for test in sorted(rows,key=lambda r:r['decision_utc']):
    decision=dt.datetime.fromisoformat(test['decision_utc']); train=[r for r in rows if r['day']<test['day'] and dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc'])<=decision]; y=np.array([int(r['outcome_gamma_yes']) for r in train]); n_dates=len({r['day'] for r in train})
    if n_dates<30 or sum(y)<5 or len(y)-sum(y)<5:continue
    latest=max(dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc']) for r in train)
    for method in ('M_price','M_spread','M_depth','M_both','H_price','H_both'):
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(np.array([features(r,method) for r in train]),y); p=float(model.predict_proba(np.array([features(test,method)]))[0,1]); w.writerow([test['city'],test['day'],test['decision_utc'],method,test['outcome_gamma_yes'],round(p,9),n_dates,len(train),latest.isoformat()])
