#!/usr/bin/env python3
"""Exploratory price/depth comparison, not independent validation."""
import argparse,csv,math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

parser=argparse.ArgumentParser(); parser.add_argument('--exclude-known-conflict',action='store_true'); parser.add_argument('--predictions',default='legacy_book_pilot_predictions.csv'); args=parser.parse_args()
base=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional']
if args.exclude_known_conflict:rows=[r for r in rows if not (r['city']=='lucknow' and r['day']=='2026-10-13')]
train=[r for r in rows if r['day']<='2026-10-25']; test=[r for r in rows if '2026-10-26'<=r['day']<='2026-11-14']
if not train or not test:raise SystemExit('Insufficient rows')
ytrain=np.array([int(r['outcome_gamma_yes']) for r in train]); ytest=np.array([int(r['outcome_gamma_yes']) for r in test])
if len(set(ytrain))<2:raise SystemExit('One training class')
def feat(r,kind):
    city=float(r['city']=='munich'); bid=float(r['best_bid']); ask=float(r['best_ask']); depth=math.log1p(float(r['ask_depth_top5_usdc'])); weather=float(r['running_max'])
    if kind=='W':return [city,weather]
    if kind=='M_price':return [city,(bid+ask)/2]
    if kind=='M_book':return [city,(bid+ask)/2,ask-bid,depth]
    return [city,weather,(bid+ask)/2,ask-bid,depth]
pred={'train_constant':np.full(len(test),ytrain.mean()),'midpoint_proxy':np.array([(float(r['best_bid'])+float(r['best_ask']))/2 for r in test]),'ask_proxy':np.array([float(r['best_ask']) for r in test])}
for kind in ('W','M_price','M_book','H_book'):
    X=np.array([feat(r,kind) for r in train]); Xt=np.array([feat(r,kind) for r in test]); model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261115)); model.fit(X,ytrain); pred[kind]=model.predict_proba(Xt)[:,1]
w=csv.writer(__import__('sys').stdout); w.writerow(['method','train_rows','train_dates','train_positive','eval_rows','eval_dates','eval_positive','brier','logloss','mean_predicted','eval_rate','limits'])
for name,p in pred.items():
    p=np.clip(p,1e-6,1-1e-6); w.writerow([name,len(train),len({r['day'] for r in train}),int(ytrain.sum()),len(test),len({r['day'] for r in test}),int(ytest.sum()),round(brier_score_loss(ytest,p),6),round(log_loss(ytest,p,labels=[0,1]),6),round(float(p.mean()),6),round(float(ytest.mean()),6),'exploratory contaminated eval; provisional gamma labels; METAR availability assumed; no execution'])
with (base/args.predictions).open('w',newline='') as f:
    out=csv.writer(f); out.writerow(['city','day','y',*pred.keys()])
    for i,r in enumerate(test):out.writerow([r['city'],r['day'],ytest[i],*[pred[k][i] for k in pred]])
