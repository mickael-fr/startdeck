"""Reproducible monthly cash-flow engine; inputs and assumptions remain explicit."""
import json
import math
import numpy as np
try:
    from .mortality import survival, last_survivor, sample_lifetimes, summary
except ImportError:
    from mortality import survival, last_survivor, sample_lifetimes, summary

def irr(flows):
    """Unique annual IRR, or None if no sign change / ambiguous multiple roots."""
    c=np.asarray(flows,float)
    c=c[np.flatnonzero(c)[0]:] if np.any(c) else c
    nonzero=c[c!=0]
    if len(nonzero)<2 or np.sum(np.diff(np.sign(nonzero))!=0)!=1: return None
    def f(r):
        with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
            return float(np.sum(c/(1+r)**np.arange(len(c))))
    low=-.9999; high=1.
    while f(low)*f(high)>0 and high<1e8: high=2*high+1
    if not math.isfinite(f(low)) or f(low)*f(high)>0: return None
    for _ in range(100):
        mid=(low+high)/2
        if f(low)*f(mid)<=0: high=mid
        else: low=mid
    return float((low+high)/2)

def _irr_matrix(flows):
    """Vectorized bisection; detect sign ambiguity before solving."""
    signs=np.sign(flows); previous=signs[:,0].copy(); changes=np.zeros(len(flows),int)
    for i in range(1,flows.shape[1]):
        current=signs[:,i]; changes+=(current!=0)&(previous!=0)&(current!=previous)
        previous=np.where(current!=0,current,previous)
    eligible=changes>=1
    low=np.full(len(flows),max(-.99,float(np.expm1(-500/max(1,flows.shape[1]-1))))); high=np.full(len(flows),1.)
    powers=np.arange(flows.shape[1])
    coefficients=flows.T.copy()
    def value(rate):
        with np.errstate(over='ignore',divide='ignore',invalid='ignore'):
            discount=1/(1+rate)
            result=coefficients[-1].copy()
            for coefficient in coefficients[-2::-1]:
                result*=discount
                result+=coefficient
            return result
    fl=value(low); fh=value(high)
    for _ in range(25):
        need=(np.sign(fl)*np.sign(fh)>0)&eligible
        if not need.any(): break
        high=np.where(need,high*2+1,high); fh=value(high)
    # Periodic tax payments can create several sign changes without multiple IRRs.
    # Scan all such paths rather than discarding their distribution a priori.
    suspect=np.flatnonzero(changes>1)
    if len(suspect):
        matrix=flows[suspect]; duration=max(1,flows.shape[1]-1)
        floor_rate=max(-.99,float(np.expm1(-500/duration)))
        grid=np.unique(np.r_[np.geomspace(1+floor_rate,2.,81)-1,
                             (1+np.array([-.99,-.9,-.75,-.5,-.25,0,.01,.025,.05,.075,.1,.125,.15,.2,.25,.3,.5,1,2,5,10,100]))**(1/12)-1,
                             0.,.1,.2,1.])
        grid=grid[(grid>=floor_rate)&(grid<=1)]
        # All grid NPVs share scalar discount factors: one BLAS product avoids
        # a full draws-by-months broadcast allocation for each grid point.
        grid_values=matrix @ ((1+grid[None,:])**(-powers[:,None]))
        count=np.zeros(len(suspect),int); left=np.full(len(suspect),np.nan); right=left.copy()
        previous=None; previous_rate=None
        for grid_index,rate in enumerate(grid):
            current=grid_values[:,grid_index]
            zero=abs(current)<1e-8
            count+=zero; left=np.where(zero,rate,left);right=np.where(zero,rate,right)
            if previous is not None:
                cross=(np.sign(current)*np.sign(previous)<0)&(~zero)&(abs(previous)>=1e-8)
                count+=cross;left=np.where(cross,previous_rate,left);right=np.where(cross,rate,right)
            previous=current;previous_rate=rate
        unique=count==1
        eligible[suspect]=unique
        low[suspect]=np.where(unique,left,low[suspect]);high[suspect]=np.where(unique,right,high[suspect])
        fl=value(low);fh=value(high)
    eligible&=(np.sign(fl)*np.sign(fh)<=0)&np.isfinite(fl)&np.isfinite(fh)
    for _ in range(64):
        mid=(low+high)/2; fm=value(mid); left=np.sign(fl)*np.sign(fm)<=0
        high=np.where(left,mid,high); low=np.where(left,low,mid); fl=np.where(left,fl,fm)
    return np.where(eligible,(low+high)/2,np.nan),changes

def _required(mapping,keys,label):
    missing=[k for k in keys if mapping.get(k) is None]
    if missing: raise ValueError(f'{label}: champs requis manquants: '+', '.join(missing))

def simulate(listing, profile, fiscal_params, hypotheses, table_path, draws=10000, seed=42,
             libre_apres=None, inflation=None, adjustment=1):
    try:
        from .fiscal import rental_tax, capital_gains, ifi_increment
    except ImportError:
        from fiscal import rental_tax, capital_gains, ifi_increment
    _required(listing,['bouquet','rente_mensuelle','valeur_venale','surface','type','tetes',
                       'taxe_fonciere','charges_annuelles','travaux_annuels','loyer_mensuel',
                       'frais_agence','remise_etat','delai_travaux_mois'],'Annonce')
    profile=dict(profile)
    if profile.get('amortissement_annuel_valide') is None and listing.get('amortissement_annuel_valide') is not None:
        profile['amortissement_annuel_valide']=listing['amortissement_annuel_valide']
    depreciation_annual=float(profile.get('amortissement_annuel_valide') or 0)
    required_h=['reference_year','discount_rate','inflation','rent_growth','property_growth',
                'vacancy_rate','management_rate','sale_cost_rate','notary_fee_rate','exit_mode',
                'exit_years','fixed_horizon_years','voluntary_departure_hazard','rente_indexation',
                'owner_charge_share_occupied','owner_tax_share_occupied','credit_rate','credit_years',
                'credit_downpayment_fraction','credit_insurance_rate']
    _required(hypotheses,required_h,'Hypothèses')
    h=dict(hypotheses)
    rente_deductible=fiscal_params.get('rente_deductible',False)
    if not isinstance(rente_deductible,bool):
        raise ValueError('rente_deductible doit être un booléen explicite.')
    inflation_series=inflation if isinstance(inflation,(list,tuple,np.ndarray)) else None
    if inflation is not None and inflation_series is None:
        h['inflation']=float(inflation); h['rente_indexation']=float(inflation)
    if profile.get('regime')=='lmnp-reel' and profile.get('amortissement_annuel_valide') is None:
        raise ValueError('LMNP réel: amortissement_annuel_valide requis; aucune quote-part inventée.')
    if listing.get('location_interdite') and not listing.get('renovation_conforme_confirmee'):
        raise ValueError('Location interdite: rénovation conforme à confirmer avant projection des loyers.')
    if listing['type'] not in ('libre','occupe'): raise ValueError('Type libre/occupe requis.')
    if listing['type']=='occupe': _required(listing,['majoration_liberation'],'Contrat occupé')
    for key in ['bouquet','rente_mensuelle','valeur_venale','taxe_fonciere','charges_annuelles','travaux_annuels','loyer_mensuel']:
        if float(listing[key])<0: raise ValueError(f'{key} doit être positif.')
    if len(listing['tetes'])>1 and listing.get('reversion') is None:
        raise ValueError('Réversion à préciser pour plusieurs têtes.')
    if len(listing['tetes'])>2: raise ValueError('Convention contractuelle à définir au-delà de deux têtes.')
    if listing.get('reversion') and listing.get('reversion_pct') is None:
        raise ValueError('Fraction de réversion requise.')
    nonreversible_fractions=None
    if len(listing['tetes'])==2 and not listing.get('reversion'):
        if any(head.get('rente_fraction') is None for head in listing['tetes']):
            raise ValueError('Deux têtes sans réversion: ventilation rente_fraction par vendeur requise.')
        nonreversible_fractions=np.array([float(head['rente_fraction']) for head in listing['tetes']])
        if np.any(nonreversible_fractions<0) or not np.isclose(nonreversible_fractions.sum(),1):
            raise ValueError('Ventilation rente_fraction positive, somme égale à 1 requise.')
    reversion=float(listing.get('reversion_pct',1)) if listing.get('reversion') else 0.
    if not 0<=reversion<=1: raise ValueError('Fraction de réversion hors 0..1.')
    majoration=float(listing.get('majoration_liberation') or 0)
    if majoration<0: raise ValueError('Majoration de libération négative.')
    if h['discount_rate']<=-1 or any(h[k]<=-1 for k in ('inflation','rente_indexation','rent_growth','property_growth')):
        raise ValueError('Taux économiques doivent être strictement supérieurs à -100 %.')
    if not 0<=h['vacancy_rate']<=1 or not 0<=h['management_rate']<=1:
        raise ValueError('Vacance/gestion hors intervalle 0..1.')
    if listing['valeur_venale']<=0: raise ValueError('Valeur vénale strictement positive requise.')
    lives=sample_lifetimes(listing['tetes'],table_path,draws,seed,adjustment,h['reference_year'])
    last=lives.max(axis=1); first=lives.min(axis=1)
    rng=np.random.default_rng(seed+1)
    hazard=float(h['voluntary_departure_hazard'])
    departure_probability=h.get('voluntary_departure_probability')
    if departure_probability is not None:
        departure_probability=float(departure_probability)
        if not math.isfinite(departure_probability) or not 0<=departure_probability<1:
            raise ValueError('Probabilité annuelle de départ volontaire requise dans [0,1[; utiliser libre_apres=0 pour un départ immédiat explicite.')
        hazard=-math.log1p(-departure_probability)
    if hazard<0: raise ValueError('Hazard négatif.')
    if not math.isfinite(hazard): raise ValueError('Hazard annuel fini requis.')
    effective_departure_probability=-math.expm1(-hazard)
    departure=rng.exponential(1/hazard,draws) if hazard>0 else np.full(draws,np.inf)
    if libre_apres is not None:
        if libre_apres<0: raise ValueError('Libération volontaire négative.')
        departure=np.minimum(departure,float(libre_apres))
    liberation=np.zeros(draws) if listing['type']=='libre' else np.minimum(last,departure)
    if h['exit_mode']=='death_plus_years': exits=last+float(h['exit_years'])
    elif h['exit_mode']=='fixed_horizon': exits=np.full(draws,float(h['fixed_horizon_years']))
    else: raise ValueError('Mode de sortie inconnu.')
    if np.any(exits<=0): raise ValueError('Horizon de sortie positif requis.')
    exit_month=np.maximum(1,np.ceil(exits*12).astype(int)); exits=exit_month/12
    dpe_deadline=fiscal_params.get('dpe_interdiction_metropole',{}).get(str(listing.get('dpe') or '').upper())
    if dpe_deadline and not listing.get('renovation_conforme_confirmee'):
        ban_time=max(0,float(dpe_deadline)-h['reference_year'])
        if np.any(exits>np.maximum(liberation,ban_time)):
            raise ValueError(f'DPE {listing["dpe"]}: location projetée après {dpe_deadline}; rénovation conforme à confirmer.')
    # Initial notary base uses expected contractual rente, no cadastral/DUH invention.
    curves=[survival(head,table_path,adjustment,h['reference_year']) for head in listing['tetes']]
    joint=last_survivor(curves); n=len(joint)
    if len(curves)==1: payment_survival=joint
    elif nonreversible_fractions is not None:
        payment_survival=np.sum(np.stack([np.pad(c,(0,n-len(c))) for c in curves])*nonreversible_fractions[:,None],axis=0)
    else:
        both=np.prod(np.stack([np.pad(c,(0,n-len(c))) for c in curves]),axis=0)
        payment_survival=both+reversion*(joint-both)
    t=np.arange(n)/12
    def indexed(time,rate,series=None):
        completed=max(0,int(np.floor(time-1/12+1e-9)))
        if series is not None:
            if completed>len(series): raise ValueError('Série inflation trop courte pour horizon de simulation.')
            return float(np.prod(1+np.asarray(series[:completed],float)))
        return (1+rate)**completed
    expected_release=1-np.exp(-hazard*t)
    if libre_apres is not None: expected_release=np.where(t>libre_apres,1.,expected_release)
    annuity_index=np.array([indexed(float(time),h['rente_indexation'],inflation_series) for time in t])
    actuarial_capital=float(np.sum(payment_survival[1:]*float(listing['rente_mensuelle'])*
                                  annuity_index[1:]*(1+majoration*expected_release[1:])/(1+h.get('notary_actuarial_discount_rate',h['discount_rate']))**t[1:]))
    fees=float(h['notary_fee_rate'])*(float(listing['bouquet'])+actuarial_capital)
    initial=float(listing['bouquet'])+fees+float(listing.get('frais_agence',0))
    # Flows are accrued monthly, grouped at annual boundaries; sale occurs in exit year.
    years=int(np.ceil(max(last.max(),exits.max())))
    month_flows=np.zeros((draws,years*12+1)); month_flows[:,0]=-initial
    flows=np.zeros((draws,years+1)); flows[:,0]=-initial
    rents=np.zeros_like(flows); annuity=np.zeros_like(flows); costs=np.zeros_like(flows)
    taxes=np.zeros_like(flows); sales=np.zeros_like(flows); states=[None]*draws
    ifi_by_year=np.zeros_like(flows)
    depreciation_cumulative=np.zeros(draws)
    warnings=['Décès indépendants; aucune dépendance conjugale modélisée.',
              'TRI calculé sur flux mensuels puis annualisé; taxes fin d’année, provision de l’année de sortie à la vente si activée.',
              'La vente est une hypothèse économique; faisabilité juridique à confirmer.',
              'IFI occupé: hypothèse DUH réservé au vendeur, assiette acquéreur nulle; usufruit différent à qualifier.',
              'TRI à plusieurs changements de signes: recherche numérique sur grille; absence de deuxième racine détectée ne constitue pas preuve d’unicité globale.',
              'Hypothèses économiques éditables, aucune prévision garantie.']
    if rente_deductible:
        warnings.append('Scénario fiscal non standard: rente déduite uniquement pendant location sur instruction explicite rente_deductible=true; validation professionnelle requise.')
    if listing.get('prix_acquisition_acte') is None:
        warnings.append('Base de plus-value estimée bouquet+frais+capital actuariel; prix fiscal stipulé dans acte à valider par notaire.')
    for key in ('frais_agence','remise_etat','majoration_liberation'):
        if listing.get(key) is None: warnings.append(f'{key} absent: zéro utilisé uniquement comme hypothèse à confirmer.')
    npv=np.full(draws,-initial)
    before_sale_liability=np.zeros(draws)
    cache={}
    fiscal_warnings=set()
    def fiscal_batch(year,rent,charge,depreciation):
        results=np.zeros(draws)
        for i in range(draws):
            # Monthly liberation produces a small finite set of rent/expense states per year.
            key=(year,round(float(rent[i]),6),round(float(charge[i]),6),round(float(depreciation[i]),6),json.dumps(states[i],sort_keys=True,default=str))
            if key not in cache:
                cache[key]=rental_tax(float(rent[i]),float(charge[i]),profile,fiscal_params,state=states[i],depreciation=float(depreciation[i]))
                for warning in cache[key].get('warnings',[]):
                    fiscal_warnings.add(f'Année {h["reference_year"]+year-1}: {warning}')
            result=cache[key]; results[i]=float(result['total']); states[i]=result.get('state')
            depreciation_cumulative[i]+=float(result.get('amortissement_deduit',0))
        return results
    for year in range(1,years+1):
        deductible=np.zeros(draws); rental_months=np.zeros(draws)
        for month in range(1,13):
            absolute=(year-1)*12+month; time=absolute/12
            in_asset=absolute<=exit_month
            alive=last>time; before_first=first>time
            contract_factor=np.where(before_first,1.,np.where(alive,reversion,0.))
            if len(listing['tetes'])==1: contract_factor=alive.astype(float)
            elif nonreversible_fractions is not None:
                contract_factor=np.sum((lives>time)*nonreversible_fractions[None,:],axis=1)
            released=time>liberation
            rente=float(listing['rente_mensuelle'])*indexed(time,h['rente_indexation'],inflation_series)*contract_factor
            rente*=np.where((departure<last)&released&alive,1+majoration,1.)
            occupied=(~released)&in_asset
            rental=(time>liberation+float(listing.get('delai_travaux_mois',0))/12)&in_asset
            rent=float(listing['loyer_mensuel'])*(1+h['rent_growth'])**time*(1-h['vacancy_rate'])*rental
            operating=(float(listing['charges_annuelles'])*np.where(occupied,h['owner_charge_share_occupied'],1.)+
                       float(listing['taxe_fonciere'])*np.where(occupied,h['owner_tax_share_occupied'],1.)+
                       float(listing['travaux_annuels']))/12*indexed(time,h['inflation'],inflation_series)*in_asset
            renovation=(absolute==np.floor(liberation*12).astype(int)+1)&in_asset
            operating+=renovation*float(listing.get('remise_etat',0))
            management=rent*h['management_rate']; total_cost=operating+management
            rents[:,year]+=rent; annuity[:,year]+=rente; costs[:,year]+=total_cost
            deductible+=total_cost*(released&in_asset); rental_months+=rental
            if rente_deductible: deductible+=rente*rental
            net=rent-rente-total_cost
            flows[:,year]+=net; month_flows[:,absolute]+=net; npv+=net/(1+h['discount_rate'])**time
            before_sale_liability+=np.where(absolute>exit_month,rente/(1+h['discount_rate'])**(time-exits),0.)
        rental_tax_value=fiscal_batch(year,rents[:,year],deductible,depreciation_annual*rental_months/12)
        snapshot=year-1
        active=exits>snapshot
        # Occupied/free annual IFI increment: call policy layer, not a fixed tax rate.
        snapshot_value=float(listing['valeur_venale'])*(1+h['property_growth'])**snapshot
        ifi_free=float(ifi_increment(snapshot_value,False,profile,fiscal_params))
        ifi_occ=float(ifi_increment(snapshot_value,True,profile,fiscal_params))
        ifi=np.where(liberation>snapshot,ifi_occ,ifi_free)*active
        ifi_threshold=fiscal_params.get('ifi',{}).get('seuil')
        if ifi_threshold is not None and float(profile.get('patrimoine_immobilier_net') or 0)<=ifi_threshold and np.any(ifi>0):
            fiscal_warnings.add(f'IFI au 1er janvier {h["reference_year"]+snapshot}: franchissement du seuil d’assujettissement dans au moins un scénario de propriété/libération/valorisation.')
        ifi_by_year[:,year]=ifi
        taxes[:,year]=rental_tax_value+ifi
        flows[:,year]-=taxes[:,year]
        tax_month=np.full(draws,year*12)
        if h.get('tax_provision_at_sale',False):
            tax_month=np.where((exit_month>(year-1)*12)&(exit_month<=year*12),exit_month,tax_month)
        month_flows[np.arange(draws),tax_month]-=taxes[:,year]
        npv-=taxes[:,year]/(1+h['discount_rate'])**(tax_month/12)
        exiting=(np.ceil(exits).astype(int)==year)
        for time in np.unique(exits[exiting]):
            mask=exiting&(exits==time)
            sale=float(listing['valeur_venale'])*(1+h['property_growth'])**time
            # Economic purchase basis assumption is exposed; legal deed basis may differ.
            basis=float(listing['prix_acquisition_acte']) if listing.get('prix_acquisition_acte') is not None else initial+actuarial_capital
            for depreciation in np.unique(depreciation_cumulative[mask]):
                subgroup=mask&(depreciation_cumulative==depreciation)
                gain=float(capital_gains(sale,basis,time,fiscal_params,depreciation=float(depreciation)))
                net_sale=sale*(1-h['sale_cost_rate'])-gain
                sales[subgroup,year]=net_sale; flows[subgroup,year]+=net_sale
                month_flows[subgroup,int(round(time*12))]+=net_sale; npv[subgroup]+=net_sale/(1+h['discount_rate'])**time
    monthly_tris,sign_changes=_irr_matrix(month_flows)
    tris=(1+monthly_tris)**12-1
    valid=tris[np.isfinite(tris)]
    median_index=int(np.argmin(abs(last-np.median(last))))
    adverse_index=int(np.argmin(abs(last-np.percentile(last,90))))
    def finite(v): return float(v) if np.isfinite(v) else None
    def case(index):
        return {'longevity_years':float(last[index]),'liberation_years':float(liberation[index]),
                'exit_years':float(exits[index]),'irr':finite(tris[index]),'npv':float(npv[index]),
                'total_annuity':float(annuity[index].sum()),'post_sale_annuity_pv':float(before_sale_liability[index])}
    if np.any(before_sale_liability>0): warnings.append('Vente avant extinction: rente future reste payée dans les flux; sa valeur à la date de vente est explicitement exposée.')
    annual=[]
    for year in range(years+1):
        annual.append({'year':year,'net':float(flows[median_index,year]),'median_net':float(np.median(flows[:,year])),
                       'monthly_annuity_indexed':float(listing['rente_mensuelle'])*indexed(max(1,year*12-11)/12,h['rente_indexation'],inflation_series),
                       'rental_income':float(rents[median_index,year]),'annuity':float(annuity[median_index,year]),
                       'owner_costs':float(costs[median_index,year]),'taxes':float(taxes[median_index,year]),
                       'ifi':float(ifi_by_year[median_index,year]),
                       'sale':float(sales[median_index,year]),'representative_net':float(flows[median_index,year])})
    # Comparison on exactly the same median exit horizon and policy layer.
    horizon=float(exits[median_index]); conventional={}
    price=float(listing['valeur_venale']); classical_fees=price*h['notary_fee_rate']
    for name in ('cash','credit'):
        principal=price*(1-h['credit_downpayment_fraction']) if name=='credit' else 0.
        duration=int(h['credit_years']*12); mr=h['credit_rate']/12
        if duration<=0 or mr<0 or not 0<=h['credit_downpayment_fraction']<=1:
            raise ValueError('Durée crédit positive, taux positif et apport 0..1 requis.')
        payment=principal/duration if mr==0 else principal*mr/(1-(1+mr)**(-duration))
        balance=principal; cf=np.zeros(int(np.ceil(horizon))*12+1)
        cf[0]=-(price+classical_fees+float(listing.get('frais_agence',0))+float(listing.get('remise_etat',0))-principal)
        state=None; cumulative_depreciation=0.
        for year in range(1,int(np.ceil(horizon))+1):
            rent=0.; cost=0.; interest=0.; rented_months=0
            for m in range(1,13):
                absolute=(year-1)*12+m; time=absolute/12
                if time>horizon: break
                rented=absolute>float(listing.get('delai_travaux_mois',0)); rented_months+=rented
                r=listing['loyer_mensuel']*(1+h['rent_growth'])**time*(1-h['vacancy_rate'])*rented
                c=(listing['charges_annuelles']+listing['taxe_fonciere']+listing['travaux_annuels'])/12*indexed(time,h['inflation'],inflation_series)+r*h['management_rate']
                debt=0.
                if absolute<=duration and balance>0:
                    im=balance*mr; interest+=im; balance=max(0,balance-(payment-im)); debt=payment+principal*h['credit_insurance_rate']/12
                cf[absolute]+=r-c-debt; rent+=r; cost+=c
            tax=rental_tax(float(rent),float(cost),profile,fiscal_params,state=state,interest=interest,
                           depreciation=depreciation_annual*rented_months/12)
            state=tax.get('state'); cumulative_depreciation+=float(tax.get('amortissement_deduit',0))
            tax_month=min(year*12,int(round(horizon*12))) if h.get('tax_provision_at_sale',False) else year*12
            cf[tax_month]-=float(tax['total'])+float(ifi_increment(price*(1+h['property_growth'])**(year-1),False,profile,fiscal_params))
            if year==int(np.ceil(horizon)):
                sale=price*(1+h['property_growth'])**horizon
                cf[int(round(horizon*12))]+=sale*(1-h['sale_cost_rate'])-balance-float(capital_gains(sale,price+classical_fees,horizon,fiscal_params,depreciation=cumulative_depreciation))
        monthly_irr=_irr_matrix(cf[None,:])[0][0]
        annual_cf=[float(cf[0])]+[float(cf[(year-1)*12+1:year*12+1].sum()) for year in range(1,int(np.ceil(horizon))+1)]
        conventional[name]={'irr':finite((1+monthly_irr)**12-1),'npv':float(np.sum(cf/(1+h['discount_rate'])**(np.arange(len(cf))/12))),
                            'annual_flows':annual_cf,'horizon_years':horizon,'initial_loan':principal}
    hypothetical_annuity=np.cumsum([float(listing['rente_mensuelle'])*indexed(month/12,h['rente_indexation'],inflation_series)
                                    for month in range(1,years*12+1)])+initial
    crossing=np.flatnonzero(hypothetical_annuity>=price)
    break_even=float((crossing[0]+1)/12) if len(crossing) else None
    stabilized_rent=listing['loyer_mensuel']*12*(1-h['vacancy_rate'])
    stabilized_expenses=stabilized_rent*h['management_rate']+listing['charges_annuelles']+listing['taxe_fonciere']+listing['travaux_annuels']
    stabilized_tax=rental_tax(stabilized_rent,stabilized_expenses,profile,fiscal_params,
                              depreciation=depreciation_annual)
    stabilized_ifi=float(ifi_increment(price,False,profile,fiscal_params))
    # Full tax-aware paired-seed reruns; sensitivity sample size is explicitly reported.
    sensitivity={}
    sensitivity_draws=min(draws,int(h.get('sensitivity_draws',draws)))
    for key,variants in h.get('sensitivities',{}).items():
        for variant in variants:
            changed_h={**h,'sensitivities':{},'inflation_scenarios':{}}; changed_l=dict(listing); changed_adjustment=adjustment
            if key=='rent_multiplier': changed_l['loyer_mensuel']*=variant
            elif key=='works_multiplier': changed_l['travaux_annuels']*=variant
            elif key=='mortality_adjustment': changed_adjustment=variant
            elif key in ('inflation','property_growth','rent_growth','discount_rate','rente_indexation'):
                changed_h[key]=variant
                if key=='inflation': changed_h['rente_indexation']=variant
            else: raise ValueError(f'Sensibilité inconnue: {key}')
            rerun=simulate(changed_l,profile,fiscal_params,changed_h,table_path,sensitivity_draws,seed,
                           libre_apres=libre_apres,adjustment=changed_adjustment)
            sensitivity[f'{key}={variant}']={'irr_median':rerun['tri_median'],'npv_median':rerun['van_median'],
                                             'method':'full_model_paired_seed','tax_recomputed':True,
                                             'draws':sensitivity_draws}
    inflation_scenarios={}
    for name,rate in h.get('inflation_scenarios',{}).items():
        scenario_h={**h,'sensitivities':{},'inflation_scenarios':{}}
        rerun=simulate(listing,profile,fiscal_params,scenario_h,table_path,sensitivity_draws,seed,
                       libre_apres=libre_apres,inflation=rate,adjustment=adjustment)
        inflation_scenarios[name]={'inflation':rate,'irr_median':rerun['tri_median'],'npv_median':rerun['van_median'],
                                  'draws':sensitivity_draws,'annuity_median_total':rerun['metrics']['annuity_median_total']}
    return {'tri_median':float(np.median(valid)) if len(valid) else None,
            'tri_p90_longevite':finite(tris[adverse_index]),'tri_p10_distribution':float(np.percentile(valid,10)) if len(valid) else None,
            'van_median':float(np.median(npv)),'annual_flows':annual,'longevity':summary(lives),
            'scenarios':{'median_longevity':case(median_index),'p90_longevity':case(adverse_index),
                         'short_longevity':case(int(np.argmin(abs(last-np.percentile(last,10))))),
                         'classical_purchase':conventional,'inflation':inflation_scenarios},
            'sensitivities':sensitivity,'assumptions':{**h,'mortality_table':str(table_path),'mortality_adjustment':adjustment,
                                                     'seed':seed,'draws':draws,'independent_deaths':True,
                                                     'capital_gains_basis':'bouquet_plus_fees_plus_actuarial_rent',
                                                     'point_mort_definition':'bouquet_fees_plus_full_indexed_annuity_equals_initial_market_value_excluding_owner_costs',
                                                     'point_mort_age_definition':'youngest_head_age_plus_point_mort_years',
                                                     'inflation_series':list(inflation_series) if inflation_series is not None else None,
                                                     'ifi_snapshot':'1_january_start_of_each_year',
                                                     'acquisition_date_assumed':f'{h["reference_year"]}-01-01',
                                                     'rente_deductible':rente_deductible,
                                                     'voluntary_departure_effective_probability':effective_departure_probability,
                                                     'voluntary_departure_effective_hazard':hazard,
                                                     'voluntary_departure_model':'exponential_time_with_user_supplied_annual_probability_or_hazard',
                                                     'libre_apres':libre_apres},
            'metrics':{'initial_investment':initial,'actuarial_annuity_capital':actuarial_capital,'notary_fees':fees,
                       'cout_total_median':initial+float(np.median(annuity.sum(axis=1)+costs.sum(axis=1)+taxes.sum(axis=1))),
                       'decote_effective':1-(initial+float(np.median(annuity.sum(axis=1))))/price,
                       'decote_actuarielle':1-(initial+actuarial_capital)/price,
                       'rendement_net_avant_impot':float((stabilized_rent-stabilized_expenses)/price),
                       'rendement_locatif_net':float((stabilized_rent-stabilized_expenses-stabilized_tax['total'])/price),
                       'rendement_locatif_net_ifi':float((stabilized_rent-stabilized_expenses-stabilized_tax['total']-stabilized_ifi)/price),
                       'fiscalite_locative_annuelle_stabilisee':float(stabilized_tax['total']),
                       'ifi_increment_annuel_stabilise':stabilized_ifi,
                       'point_mort_years':break_even,
                       'point_mort_age':min(float(head['age']) for head in listing['tetes'])+break_even if break_even is not None else None,
                       'loss_p90_longevity':max(0.,-float(npv[adverse_index])),
                       'annuity_median_total':float(np.median(annuity.sum(axis=1))),
                       'annuity_p90_total':float(np.percentile(annuity.sum(axis=1),90)),
                       'post_sale_annuity_pv_median':float(np.median(before_sale_liability)),
                       'invalid_irr_draws':int((~np.isfinite(tris)).sum()),
                       'potential_multiple_sign_change_draws':int((sign_changes>1).sum()),
                       'ambiguous_sign_change_draws':int(((sign_changes>1)&(~np.isfinite(tris))).sum())},
            'distribution':{'irr_percentiles':{str(p):float(np.percentile(valid,p)) if len(valid) else None for p in (10,25,50,75,90)},
                            'npv_percentiles':{str(p):float(np.percentile(npv,p)) for p in (10,25,50,75,90)}},
            'warnings':warnings+sorted(fiscal_warnings)}
