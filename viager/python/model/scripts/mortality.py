"""Conditional monthly survival, no invented or extrapolated demographic tail."""
import numpy as np
import pandas as pd

def survival(head, table_path, adjustment=1, reference_year=2026):
    if head.get('sexe') not in ('M','F') or head.get('age') is None:
        raise ValueError('Âge et sexe M/F requis pour chaque tête.')
    age=float(head['age'])
    if age<0 or adjustment<=0: raise ValueError('Âge positif et ajustement strictement positif requis.')
    table=pd.read_csv(table_path)
    if not {'sexe','age','qx','generation'}.issubset(table.columns): raise ValueError('Colonnes table incomplètes.')
    rows=table[table.sexe==head['sexe']].copy()
    if rows.generation.notna().any():
        generation=head.get('annee_naissance')
        if generation is None: raise ValueError('Année de naissance exacte requise pour une table générationnelle.')
        rows=rows[rows.generation==int(generation)]
    rows=rows.sort_values('age')
    start=int(np.floor(age)); rows=rows[rows.age>=start]
    if rows.empty or rows.age.duplicated().any(): raise ValueError('Génération/sexe absent ou âges dupliqués.')
    ages=rows.age.to_numpy(int); q=rows.qx.to_numpy(float)
    if ages[0]!=start or not np.all(np.diff(ages)==1) or not np.all(np.isfinite(q)) or np.any((q<0)|(q>1)) or q[-1]!=1:
        raise ValueError('Table requise contiguë depuis âge actuel avec qx terminal égal à 1; aucune extrapolation.')
    # Multiplicative force of mortality preserves probabilities and terminal extinction.
    annual=(1-q)**adjustment
    annual_s=np.r_[1.,np.cumprod(annual)]
    fractional=age-start
    denominator=annual[0]**fractional if annual[0]>0 else 1-fractional
    max_month=int(np.ceil((len(q)-fractional)*12))
    offsets=np.arange(max_month+1)/12+fractional
    year=np.floor(offsets).astype(int); frac=offsets-year
    values=np.zeros(len(offsets)); valid=year<len(q)
    idx=year[valid]; f=frac[valid]
    # qx=1 is interpolated linearly over final year to avoid a false immediate death.
    within=np.where(annual[idx]>0,annual[idx]**f,1-f)
    values[valid]=annual_s[idx]*within/denominator
    values[0]=1; values[-1]=0
    return np.clip(values,0,1)

def last_survivor(curves, independent=True):
    if not independent: raise ValueError('La dépendance des décès nécessite un modèle joint explicite.')
    if not curves: raise ValueError('Au moins une courbe requise.')
    n=max(len(c) for c in curves)
    padded=np.stack([np.pad(c,(0,n-len(c))) for c in curves])
    return 1-np.prod(1-padded,axis=0)

def sample_lifetimes(heads, table_path, draws=10000, seed=42, adjustment=1, reference_year=2026):
    if not heads or draws<1: raise ValueError('Têtes et tirages positifs requis.')
    rng=np.random.default_rng(seed)
    result=[]
    for head in heads:
        s=survival(head,table_path,adjustment,reference_year)
        result.append(np.searchsorted(1-s,rng.random(draws),side='left')/12)
    return np.stack(result,axis=1)

def summary(lifetimes):
    a=np.asarray(lifetimes,float)
    if a.ndim==2: a=np.max(a,axis=1)
    return {'mean':float(np.mean(a)),'median':float(np.median(a)),
            **{f'p{p}':float(np.percentile(a,p)) for p in (10,25,75,90)},
            **{f'prob_survival_{y}':float(np.mean(a>y)) for y in (5,10,15,20)}}
