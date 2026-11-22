#!/usr/bin/env python3
"""Exploratory risk ranking, market target and upper ladder, grouped by city/day."""
import collections,csv,random
from pathlib import Path
from sklearn.metrics import roc_auc_score
base=Path(__file__).resolve().parent
targets={(r['city'],r['day']):r for r in csv.DictReader((base/'legacy_book_dataset.csv').open()) if r['status']=='provisional'}
upper={(r['city'],r['day']):r for r in csv.DictReader((base/'book_ladder_asks.csv').open()) if r['status']=='above_asks_complete'}
w=csv.writer(__import__('sys').stdout); w.writerow(['city','cases','losses','signal','auc_loss','delta_vs_negative_target_mid','bootstrap_low','bootstrap_high','valid_boot','one_class_boot','interpretation'])
for city in ('lucknow','munich'):
    samples=[]
    for key,target in sorted(targets.items()):
        if key[0]!=city or key not in upper:continue
        u=upper[key]; bid=float(target['best_bid']); ask=float(target['best_ask']); samples.append({'day':key[1],'loss':1-int(target['outcome_gamma_yes']),'negative_mid':-(bid+ask)/2,'upper_sum':float(u['above_ask_sum']),'upper_max':float(u['above_ask_max']),'target_spread':ask-bid})
    y=[x['loss'] for x in samples]; baseline=roc_auc_score(y,[x['negative_mid'] for x in samples])
    for signal in ('negative_mid','upper_sum','upper_max','target_spread'):
        auc=roc_auc_score(y,[x[signal] for x in samples]); rng=random.Random(20261115); deltas=[]; skipped=0
        for _ in range(3000):
            draw=rng.choices(samples,k=len(samples)); yy=[x['loss'] for x in draw]
            if len(set(yy))<2:skipped+=1;continue
            deltas.append(roc_auc_score(yy,[x[signal] for x in draw])-roc_auc_score(yy,[x['negative_mid'] for x in draw]))
        deltas.sort(); lo=deltas[int(.025*(len(deltas)-1))] if deltas else ''; hi=deltas[int(.975*(len(deltas)-1))] if deltas else ''
        w.writerow([city,len(samples),sum(y),signal,round(auc,5),round(auc-baseline,5),round(lo,5) if deltas else '',round(hi,5) if deltas else '',len(deltas),skipped,'exploratory same sample; label and weather availability unverified; not profit'])
