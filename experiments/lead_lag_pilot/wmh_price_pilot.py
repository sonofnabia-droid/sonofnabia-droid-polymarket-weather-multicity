#!/usr/bin/env python3
"""Tiny exploratory W/M/H proxy. No orderbooks, no production model saved."""
import argparse,csv,math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

parser=argparse.ArgumentParser(); parser.add_argument('--predictions'); args=parser.parse_args()
base=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((base/'rmax_market_compare_delay15_through_july17.csv').open()) if r['status']=='descriptive' and r['hour']=='15']
train=[r for r in rows if r['day']<='2026-06-21']; evaluate=[r for r in rows if '2026-06-22'<=r['day']<='2026-07-17']
if not train or not evaluate:raise SystemExit('Missing train or evaluation rows')
def features(r,kind):
    city=float(r['city']=='munich'); weather=[float(r['rmax'])]; market=[float(r['candidate_price']),float(r['leader_price']),float(r['candidate']==r['leader'])]
    return [city]+(weather if kind=='W' else market if kind=='M' else weather+market)
ytrain=np.array([int(r['candidate_won']=='True') for r in train]); ytest=np.array([int(r['candidate_won']=='True') for r in evaluate])
if len(set(ytrain))<2:raise SystemExit('Training needs two classes')
w=csv.writer(__import__('sys').stdout); w.writerow(['method','train_rows','train_dates','eval_rows','eval_dates','eval_positives','brier','logloss','mean_predicted','observed_rate','limitations'])
predictions={'train_constant':np.full(len(evaluate),ytrain.mean()),'historical_target_price':np.array([float(r['candidate_price']) for r in evaluate])}
for kind in ('W','M','H'):
    X=np.array([features(r,kind) for r in train]); Xt=np.array([features(r,kind) for r in evaluate]); model=make_pipeline(StandardScaler(),LogisticRegression(C=1.0,max_iter=1000,random_state=20261115)); model.fit(X,ytrain); predictions[kind]=model.predict_proba(Xt)[:,1]
for name,p in predictions.items():
    p=np.clip(p,1e-6,1-1e-6)
    w.writerow([name,len(train),len({r['day'] for r in train}),len(evaluate),len({r['day'] for r in evaluate}),int(ytest.sum()),round(brier_score_loss(ytest,p),6),round(log_loss(ytest,p,labels=[0,1]),6),round(float(p.mean()),6),round(float(ytest.mean()),6),'contaminated evaluation; observation delay assumed; historical price not ask; no orderbook'])
if args.predictions:
    with open(args.predictions,'w',newline='') as f:
        out=csv.writer(f); out.writerow(['city','day','observed_target_won','p_W','p_M','p_H'])
        for i,r in enumerate(evaluate):out.writerow([r['city'],r['day'],ytest[i],predictions['W'][i],predictions['M'][i],predictions['H'][i]])
