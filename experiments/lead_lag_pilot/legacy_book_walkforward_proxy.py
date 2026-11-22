#!/usr/bin/env python3
"""Daily W/M/H research gated by archived Gamma updatedAt proxy."""
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
    city=float(r['city']=='munich'); bid=float(r['best_bid']); ask=float(r['best_ask']); depth=math.log1p(float(r['ask_depth_top5_usdc'])); weather=float(r['running_max']); mid=(bid+ask)/2
    return {'W':[city,weather],'M_price':[city,mid],'M_book':[city,mid,ask-bid,depth],'H_book':[city,weather,mid,ask-bid,depth]}[kind]
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','decision_utc','method','y','p','train_rows','train_dates','train_positive','late_labels_excluded','latest_label_proxy_utc','limitations'])
for test in sorted(rows,key=lambda r:r['decision_utc']):
    decision=dt.datetime.fromisoformat(test['decision_utc']); eligible=[]; late=0
    for r in rows:
        if r['day']>=test['day']:continue
        seen=dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc'])
        if seen<=decision:eligible.append(r)
        else:late+=1
    y=np.array([int(r['outcome_gamma_yes']) for r in eligible])
    if len({r['day'] for r in eligible})<30 or sum(y)<5 or len(y)-sum(y)<5:continue
    pred={'constant':float(y.mean()),'midpoint':(float(test['best_bid'])+float(test['best_ask']))/2,'ask':float(test['best_ask'])}
    for kind in ('W','M_price','M_book','H_book'):
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(np.array([features(r,kind) for r in eligible]),y); pred[kind]=float(model.predict_proba(np.array([features(test,kind)]))[0,1])
    latest=max(dt.datetime.fromisoformat(timing[(r['city'],r['day'])]['max_updated_utc']) for r in eligible)
    for method,p in pred.items():w.writerow([test['city'],test['day'],test['decision_utc'],method,test['outcome_gamma_yes'],round(float(np.clip(p,1e-6,1-1e-6)),9),len(eligible),len({r['day'] for r in eligible}),int(sum(y)),late,latest.isoformat(),'archived updatedAt proxy not verified availability; weather latency assumed; no execution'])
