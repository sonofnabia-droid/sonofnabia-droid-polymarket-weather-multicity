#!/usr/bin/env python3
"""Daily expanding W/M/H pilot on legacy books; exploratory only."""
import argparse,csv,datetime as dt,math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
parser=argparse.ArgumentParser(); parser.add_argument('--label-lag-days',type=int,default=2); args=parser.parse_args()
if args.label_lag_days<1:raise SystemExit('Label lag must be at least one day')
base=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']
def features(r,kind):
    city=float(r['city']=='munich'); bid=float(r['best_bid']); ask=float(r['best_ask']); depth=math.log1p(float(r['ask_depth_top5_usdc'])); weather=float(r['running_max']); mid=(bid+ask)/2
    return {'W':[city,weather],'M_price':[city,mid],'M_book':[city,mid,ask-bid,depth],'H_book':[city,weather,mid,ask-bid,depth]}[kind]
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','method','y','p','train_rows','train_dates','train_positive','limitations'])
for day in sorted({r['day'] for r in rows}):
    latest=(dt.date.fromisoformat(day)-dt.timedelta(days=args.label_lag_days)).isoformat()
    train=[r for r in rows if r['day']<=latest]; test=[r for r in rows if r['day']==day]; y=np.array([int(r['outcome_gamma_yes']) for r in train])
    if len({r['day'] for r in train})<30 or sum(y)<5 or len(y)-sum(y)<5:continue
    pred={'constant':np.full(len(test),y.mean()),'midpoint':np.array([(float(r['best_bid'])+float(r['best_ask']))/2 for r in test]),'ask':np.array([float(r['best_ask']) for r in test])}
    for kind in ('W','M_price','M_book','H_book'):
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(np.array([features(r,kind) for r in train]),y); pred[kind]=model.predict_proba(np.array([features(r,kind) for r in test]))[:,1]
    for method,values in pred.items():
        for i,r in enumerate(test):w.writerow([r['city'],day,method,r['outcome_gamma_yes'],round(float(np.clip(values[i],1e-6,1-1e-6)),9),len(train),len({r['day'] for r in train}),int(sum(y)),f'exploratory; label lag {args.label_lag_days} days assumed; weather latency assumed; no execution'])
