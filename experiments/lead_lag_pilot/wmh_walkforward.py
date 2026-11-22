#!/usr/bin/env python3
"""Exploratory monthly walk-forward; W/M/H price proxy, no orderbook."""
import csv,datetime as dt
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

base=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((base/'rmax_market_compare_delay15_through_july17.csv').open()) if r['status']=='descriptive' and r['hour']=='15']
def features(r,kind):
    city=float(r['city']=='munich'); weather=[float(r['rmax'])]; market=[float(r['candidate_price']),float(r['leader_price']),float(r['candidate']==r['leader'])]
    return [city]+(weather if kind=='W' else market if kind=='M' else weather+market)
w=csv.writer(__import__('sys').stdout); w.writerow(['city','day','fold','method','y','p','train_rows','train_days','limitations'])
for start,end in [('2026-05-01','2026-05-31'),('2026-06-01','2026-06-30'),('2026-07-01','2026-07-17')]:
    train=[r for r in rows if r['day']<start]; evaluate=[r for r in rows if start<=r['day']<=end]
    y=np.array([int(r['candidate_won']=='True') for r in train])
    if len(train)<30 or len(set(y))<2 or not evaluate:continue
    predictions={'constant':np.full(len(evaluate),y.mean()),'price':np.array([float(r['candidate_price']) for r in evaluate])}
    for kind in ('W','M','H'):
        X=np.array([features(r,kind) for r in train]); Xt=np.array([features(r,kind) for r in evaluate]); model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(X,y); predictions[kind]=model.predict_proba(Xt)[:,1]
    for method,p in predictions.items():
        for i,r in enumerate(evaluate):
            w.writerow([r['city'],r['day'],start[:7],method,int(r['candidate_won']=='True'),round(float(np.clip(p[i],1e-6,1-1e-6)),9),len(train),len({x['day'] for x in train}),'exploratory previously inspected; assumed weather delay; no orderbook; no execution'])
