"""Offline monthly investment projections, with explicit valuation assumptions.

Fiscal rates and mortality are reused read-only from viager-advisor. Nothing is
downloaded, persisted or inferred about a seller's identity by this module.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import math
import sys

import numpy as np
import yaml

SKILL_ROOT = Path(__file__).resolve().parent / 'model'
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
from scripts.fiscal import rental_tax, ifi_increment
from scripts.mortality import sample_lifetimes, summary as mortality_summary
from scripts.simulate import _irr_matrix

FISCAL_PARAMS = yaml.safe_load((SKILL_ROOT/'config/parametres_fiscaux.yaml').read_text(encoding='utf-8'))
FISCAL_YEAR = FISCAL_PARAMS['millésime']
SOURCES = [{'label': key.replace('_', ' ').capitalize(), 'url': url}
           for key, url in FISCAL_PARAMS['sources'].items()]
DEFAULTS = {'mode': 'viager', 'name': 'Démonstration fictive - à remplacer', 'source_url': '', 'notes': 'Démonstration entièrement fictive. Tous les montants sont des hypothèses à remplacer. Aucun revenu personnel supposé.', 'type': 'occupe', 'usage': 'habitation', 'bouquet': 50000, 'occupied_value': 140000, 'property_value': 240000, 'monthly_annuity': 700, 'rent_monthly': 950, 'notary_basis': 'occupied', 'notary_rate': 0.08, 'notary_amount': None, 'other_fees': 0, 'annuity_growth': 0.02, 'departure_increase': 0, 'libre_after': None, 'death_after': 15, 'years': 30, 'property_growth': 0, 'rent_growth': 0.01, 'charges_growth': 0.02, 'discount_rate': 0.04, 'property_tax': 1200, 'other_charges': 600, 'annual_works': 1000, 'insurance': 180, 'management_rate': 0.06, 'vacancy_rate': 0.05, 'renovation': 10000, 'regime': 'micro-foncier', 'tax_method': 'tmi', 'taxable_income': None, 'tmi': 0.11, 'parts': 1, 'parts_base': 1, 'quotient_cap': None, 'situation': 'celibataire', 'other_rent': 0, 'other_rent_charges': 0, 'ifi_assets': 0, 'amortization': 0, 'heads': [], 'mortality_table': 'insee', 'mortality_adjustment': 1, 'mc_enabled': False, 'reversal': 1, 'loan_amount': 0, 'loan_years': 20, 'loan_rate': 0.04, 'loan_insurance_rate': 0, 'loan_payment_override': None, 'loan_exit_fee': 0, 'share_investment': 50000, 'project_cost': 200000, 'exit_project_value': 240000, 'holding_years': 4, 'annual_yield': 0.085, 'downpayment': 50000, 'contract_kind': 'viager', 'payment_term_years': None, 'released_other_charges': None}


def _number(value, key, low=0., high=1e9, nullable=False):
    if value is None and nullable:
        return None
    if value is None or isinstance(value, bool):
        raise ValueError(f'{key} : valeur numérique requise (absence distincte de zéro).')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{key} : nombre requis.') from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{key} : nombre fini entre {low:g} et {high:g} requis.')
    return number


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Une saisie JSON objet est requise.')
    d = deepcopy(DEFAULTS)
    d.update({key: value for key, value in data.items() if key in d})
    choices = dict(mode=('viager', 'portage'), type=('occupe', 'libre'), contract_kind=('viager','vente-terme'),
        usage=('habitation', 'professionnel'), notary_basis=('occupied', 'full', 'custom'),
        regime=('micro-foncier', 'reel', 'lmnp-micro', 'lmnp-reel'), tax_method=('income', 'tmi'),
        situation=('celibataire', 'couple'), mortality_table=('insee', 'tgh05'))
    for key, values in choices.items():
        if d[key] not in values:
            raise ValueError(f'{key} : choisir parmi {", ".join(values)}.')
    text_keys = ('name', 'source_url', 'notes')
    for key in text_keys:
        if not isinstance(d[key], str) or len(d[key]) > 5000:
            raise ValueError(f'{key} : texte de 5 000 caractères maximum requis.')
    rates = ('notary_rate', 'departure_increase', 'management_rate', 'vacancy_rate', 'tmi',
             'reversal', 'loan_rate', 'loan_insurance_rate', 'annual_yield')
    growth = ('annuity_growth', 'property_growth', 'rent_growth', 'charges_growth', 'discount_rate')
    nullable = ('notary_amount', 'libre_after', 'taxable_income', 'quotient_cap', 'payment_term_years',
                'loan_payment_override', 'exit_project_value', 'downpayment', 'released_other_charges')
    skip = set(choices) | set(text_keys) | {'heads', 'mc_enabled'}
    for key in set(d) - skip:
        high = 1 if key in rates else (120 if key in ('death_after', 'libre_after') else 1e9)
        if key in growth:
            d[key] = _number(d[key], key, -.5, 1)
        else:
            d[key] = _number(d[key], key, 0, high, key in nullable)
    for key in ('years',):
        if d[key] != int(d[key]) or not 1 <= d[key] <= 60:
            raise ValueError('years : entier de 1 à 60 requis.')
        d[key] = int(d[key])
    for key in ('loan_years', 'holding_years'):
        if not 1/12 <= d[key] <= 60:
            raise ValueError(f'{key} : durée entre un mois et 60 ans requise.')
    if d['mortality_adjustment'] <= 0 or d['mortality_adjustment'] > 10:
        raise ValueError('Ajustement de mortalité strictement positif, maximum 10.')
    if d['property_value'] <= 0 or d['parts_base'] <= 0 or d['parts'] < d['parts_base']:
        raise ValueError('Valeur du bien positive et parts >= parts_base > 0 requises.')
    if d['mode'] == 'viager' and d['notary_basis'] == 'custom' and d['notary_amount'] is None:
        raise ValueError('Montant notarié requis pour la base personnalisée.')
    if d['mode'] == 'viager' and d['tax_method'] == 'income' and d['taxable_income'] is None:
        raise ValueError('Revenu imposable hors revenus fonciers requis pour le calcul réel.')
    if not isinstance(d['mc_enabled'], bool):
        raise ValueError('mc_enabled : booléen requis.')
    if not isinstance(d['heads'], list) or len(d['heads']) > 2:
        raise ValueError('Zéro, une ou deux têtes requises.')
    if d['contract_kind']=='vente-terme':
        if d['payment_term_years'] is None or not 1/12 <= d['payment_term_years'] <= 60:
            raise ValueError('Vente à terme : durée contractuelle de paiement entre un mois et 60 ans requise.')
        if d['type']=='occupe' and d['libre_after'] is None:
            raise ValueError('Vente à terme occupée : durée d’occupation contractuelle requise.')
        d['heads']=[];d['mc_enabled']=False
    heads = []
    for head in d['heads']:
        if not isinstance(head, dict) or head.get('sex') not in ('F', 'M'):
            raise ValueError('Chaque tête doit préciser sexe F/M et âge.')
        age = _number(head.get('age'), 'âge', 0, 110)
        birth = _number(head.get('birth_year'), 'année de naissance', 1900, 2026, True)
        if birth is not None and birth != int(birth):
            raise ValueError('Année de naissance entière requise.')
        if d['mortality_table'] == 'tgh05' and birth is None:
            raise ValueError('TGH05/TGF05 : année de naissance exacte requise, sans déduction depuis l’âge.')
        heads.append(dict(sex=head['sex'], age=age, birth_year=int(birth) if birth else None))
    d['heads'] = heads
    if d['mode'] == 'portage' and (d['project_cost'] <= 0 or d['share_investment'] <= 0):
        raise ValueError('Portage : quote-part et coût total strictement positifs requis.')
    if d['mode'] == 'portage' and d['share_investment'] > d['project_cost']:
        raise ValueError('La quote-part ne peut pas dépasser le coût du projet.')
    return d


def monthly_irr(flows):
    """Return annualized monthly IRR; absent/ambiguous root is None."""
    monthly = _irr_matrix(np.asarray(flows, dtype=float)[None, :])[0][0]
    if not np.isfinite(monthly):
        return None
    annual = float(np.expm1(12 * np.log1p(monthly)))
    return annual if math.isfinite(annual) else None


def _loan(d, months):
    amount, balance = d['loan_amount'], d['loan_amount']
    duration = int(round(d['loan_years']*12))
    rate = d['loan_rate']/12
    payment = d['loan_payment_override']
    if payment is None:
        payment = amount/duration if rate == 0 else amount*rate/(1-(1+rate)**-duration)
    loan, interest, balances = np.zeros(months), np.zeros(months), np.zeros(months)
    insurance = np.zeros(months)
    if amount and payment <= amount*rate:
        raise ValueError('Mensualité insuffisante : elle doit dépasser les intérêts mensuels.')
    for m in range(months):
        if balance > 1e-8 and m < duration:
            interest[m] = balance*rate
            paid = min(payment, balance+interest[m])
            insurance[m] = amount*d['loan_insurance_rate']/12
            loan[m] = paid+insurance[m]
            balance = max(0., balance-(paid-interest[m]))
        balances[m] = balance
    return loan, interest+insurance, balances


def _profile(d):
    return dict(regime=d['regime'], revenu_imposable=d['taxable_income'] if d['tax_method']=='income' else None,
        tmi=d['tmi'], parts=d['parts'], parts_base=d['parts_base'],
        plafond_quotient_total=d['quotient_cap'], situation=d['situation'],
        autres_revenus_fonciers=d['other_rent'], autres_charges_foncieres=d['other_rent_charges'],
        patrimoine_immobilier_net=d['ifi_assets'], droit_occupation='duh')


def _viager_path(d, death=None, first=None, warnings=None, compute_irr=True):
    death = d['death_after'] if death is None else float(death)
    first = death if first is None else float(first)
    months = d['years']*12
    start = np.arange(months)/12
    year_index = np.arange(months)//12
    departure = d['libre_after'] if d['libre_after'] is not None and d['type']=='occupe' else math.inf
    release = 0. if d['type']=='libre' else min(death, departure)
    if d['contract_kind']=='vente-terme':
        death=first=d['payment_term_years']
        release=0. if d['type']=='libre' else d['libre_after']
    # Integrate fractional months exactly. A death at 1.5 years pays 18 months.
    alive = np.clip((death-start)*12, 0, 1)
    before_first = np.clip((first-start)*12, 0, 1)
    factor = before_first + d['reversal']*(alive-before_first)
    if d['contract_kind']=='vente-terme':factor=alive
    rented = 1-np.clip((release-start)*12, 0, 1)
    departure_alive = np.maximum(0, alive-np.clip((departure-start)*12, 0, 1)) if departure < death else np.zeros(months)
    if d['contract_kind']=='vente-terme':departure_alive=np.zeros(months)
    annuity = d['monthly_annuity']*(1+d['annuity_growth'])**year_index
    annuity = annuity*(factor+d['departure_increase']*departure_alive*
                       np.where(alive>0, factor/np.maximum(alive, 1e-10), 0))
    rent = d['rent_monthly']*(1+d['rent_growth'])**year_index*(1-d['vacancy_rate'])*rented
    other_charge = np.full(months, d['other_charges'])
    if d['released_other_charges'] is not None:
        other_charge += (d['released_other_charges']-d['other_charges'])*rented
    base_charge = (d['property_tax']+other_charge+d['annual_works']+d['insurance'])/12
    charges = base_charge*(1+d['charges_growth'])**year_index + rent*d['management_rate']
    deductible = base_charge*(1+d['charges_growth'])**year_index*rented+rent*d['management_rate']
    if release < d['years']:
        at = int(math.floor(release*12+1e-8))
        charges[at] += d['renovation']
        deductible[at] += d['renovation']
    loan, interest, balances = _loan(d, months)
    taxes = np.zeros(months)
    state = None
    profile = _profile(d)
    for year in range(d['years']):
        span = slice(year*12, (year+1)*12)
        rental = rental_tax(float(rent[span].sum()), float(deductible[span].sum()),
            profile, FISCAL_PARAMS, state=state,
            interest=float((interest[span]*rented[span]).sum()),
            depreciation=d['amortization']*float(rented[span].sum())/12)
        state = rental['state']
        occupied = release > year
        value = d['property_value']*(1+d['property_growth'])**year
        ifi = ifi_increment(value, occupied, profile, FISCAL_PARAMS)
        taxes[(year+1)*12-1] = rental['total']+ifi
        if warnings is not None:
            warnings.update(rental.get('warnings', []))
            if ifi > 0:
                warnings.add('IFI supplémentaire inclus : hypothèse DUH réservé pendant occupation ; assiette à qualifier dans l’acte.')
    basis = d['occupied_value'] if d['notary_basis']=='occupied' and d['type']=='occupe' else d['property_value']
    fees = d['notary_amount'] if d['notary_amount'] is not None else basis*d['notary_rate']
    initial = d['bouquet']+fees+d['other_fees']-d['loan_amount']
    if initial < 0:
        raise ValueError('Le prêt ne peut pas dépasser le décaissement initial du viager.')
    operating = rent-annuity-charges-taxes-loan
    flows = np.r_[-initial, operating]
    value = d['property_value']*(1+d['property_growth'])**d['years']
    terminal_cost = balances[-1]+(d['loan_exit_fee'] if balances[-1] else 0)
    flows[-1] += value-terminal_cost
    valid_exit = death <= d['years'] or d['monthly_annuity']==0
    return dict(annuity=annuity, rent=rent, charges=charges, taxes=taxes, loan=loan,
        balances=balances, operating=operating, flows=flows, fees=fees, initial=initial,
        terminal_cost=terminal_cost, value=value, release=release,
        irr=monthly_irr(flows) if valid_exit and compute_irr else None,
        npv=float(np.sum(flows/(1+d['discount_rate'])**(np.arange(months+1)/12))) if valid_exit else None)


def _viager(d, warnings):
    p = _viager_path(d, warnings=warnings)
    annual, cumulative = [], p['initial']
    total = p['initial']-float(p['operating'].sum())+p['terminal_cost']
    for year in range(1, d['years']+1):
        span = slice((year-1)*12, year*12)
        net = float(p['operating'][span].sum())
        cumulative -= net
        if year == d['years']:
            cumulative += p['terminal_cost']
        value = d['property_value']*(1+d['property_growth'])**year
        annual.append(dict(year=year, annuity_monthly=float(p['annuity'][span].sum())/12,
            annuity=float(p['annuity'][span].sum()), rent=float(p['rent'][span].sum()),
            charges=float(p['charges'][span].sum()), tax=float(p['taxes'][span].sum()),
            loan=float(p['loan'][span].sum()), net_flow=net, cumulative_cost=cumulative,
            property_value=value, nominal_margin=value-cumulative-p['balances'][year*12-1] if year<d['years'] else value-cumulative,
            loan_remaining=float(p['balances'][year*12-1])))
    stabilization = _viager_path(dict(d, type='libre', contract_kind='viager', payment_term_years=None, years=1, death_after=0, loan_amount=0,
        renovation=0, annual_works=d['annual_works']), compute_irr=False)
    hypothetical = d['bouquet']+p['fees']+d['other_fees']+np.cumsum(d['monthly_annuity']*(1+d['annuity_growth'])**(np.arange(d['years']*12)//12))
    crossing = np.flatnonzero(hypothetical >= d['property_value'])
    if d['contract_kind']=='vente-terme':
        hypothetical=d['bouquet']+p['fees']+d['other_fees']+np.cumsum(p['annuity'])
        crossing=np.flatnonzero(hypothetical>=d['property_value'])
    summary = dict(initial_cash=p['initial'], notary_fees=p['fees'],
        year1_monthly_effort=-annual[0]['net_flow']/12, total_annuity=float(p['annuity'].sum()),
        total_rent=float(p['rent'].sum()), total_tax=float(p['taxes'].sum()), total_net_cost=total,
        projected_value=p['value'], nominal_margin=p['value']-total, irr=p['irr'], npv=p['npv'],
        break_even_year=float((crossing[0]+1)/12) if len(crossing) else None,
        average_monthly_effort=float(-p['operating'].sum()/(d['years']*12)),
        net_yield_after_release=float(stabilization['operating'].sum()/d['property_value']),
        loan_remaining=float(p['balances'][-1]))
    if (d['payment_term_years'] if d['contract_kind']=='vente-terme' else d['death_after']) > d['years'] and d['monthly_annuity'] > 0:
        warnings.add('Rente encore active à la cession projetée : valeur de cession avec charge de rente inconnue ; TRI et VAN non validés (null).')
    return summary, annual


def _portage(d, warnings):
    months = int(round(d['holding_years']*12))
    duration = months/12
    loan, interest, balances = _loan(d, months)
    initial = d['downpayment'] if d['downpayment'] is not None else d['share_investment']-d['loan_amount']
    if initial < 0:
        raise ValueError('Apport de portage négatif : financement supérieur à la quote-part.')
    initial += d['other_fees']
    coupons = np.full(months, d['share_investment']*d['annual_yield']/12)
    operating = coupons-loan
    ratio = d['share_investment']/d['project_cost']
    value = None if d['exit_project_value'] is None else d['exit_project_value']*ratio
    receipt = None if value is None else value-balances[-1]-d['loan_exit_fee']
    flows = np.r_[-initial, operating]
    if receipt is not None:
        flows[-1] += receipt
    total = initial-float(operating.sum())+float(balances[-1])+d['loan_exit_fee']
    annual = []
    cumulative = initial
    for year in range(1, math.ceil(duration)+1):
        span = slice((year-1)*12, min(year*12, months))
        net = float(operating[span].sum())
        final = year == math.ceil(duration)
        cumulative -= net
        if final and receipt is not None:
            net += receipt
        balance = float(balances[min(year*12, months)-1])
        annual.append(dict(year=year, annuity_monthly=0., annuity=0., rent=float(coupons[span].sum()),
            charges=0., tax=None, loan=float(loan[span].sum()), net_flow=net,
            cumulative_cost=cumulative, property_value=value, nominal_margin=None if value is None else value-cumulative-balance-d['loan_exit_fee'],
            loan_remaining=balance, exit_receipt=receipt if final else 0.,
            loan_interest_and_insurance=float(interest[span].sum())))
    warnings.add('Portage BRUT : rendement contractuel, nature juridique et qualification fiscale non validés ; aucun impôt supposé nul.')
    if value is None:
        warnings.add('Valeur de sortie du projet absente : marge, TRI et VAN non calculables.')
    if d['downpayment'] is not None and abs(d['downpayment']+d['loan_amount']-d['share_investment']) > 1:
        warnings.add('Apport + prêt différents de la quote-part : origine du solde de financement à vérifier.')
    summary = dict(initial_cash=initial, notary_fees=0., year1_monthly_effort=float(-operating[:min(12,months)].mean()),
        total_annuity=0., total_rent=float(coupons.sum()), total_tax=None, total_net_cost=total,
        projected_value=value, nominal_margin=None if value is None else value-total,
        irr=monthly_irr(flows) if value is not None else None,
        npv=float(np.sum(flows/(1+d['discount_rate'])**(np.arange(months+1)/12))) if value is not None else None,
        break_even_year=None, average_monthly_effort=float(-operating.mean()),
        net_yield_after_release=None, loan_remaining=float(balances[-1]))
    return summary, annual


def _scenario(d, name, death, overrides=None):
    changed = dict(d, death_after=float(death), **(overrides or {}))
    summary, _ = _viager(changed, set())
    release = 0 if d['type']=='libre' else min(float(death), d['libre_after'] if d['libre_after'] is not None else math.inf)
    if d['contract_kind']=='vente-terme':release=0 if d['type']=='libre' else d['libre_after']
    return dict(name=name, death_after=float(death), libre_after=release,
        irr=summary['irr'], npv=summary['npv'], total_net_cost=summary['total_net_cost'],
        nominal_margin=summary['nominal_margin'], monthly_effort=summary['average_monthly_effort'])


def _demography(d, warnings):
    if not d['heads']:
        if d['mc_enabled']:
            warnings.add('Âges/sexe absents : longévité et Monte Carlo non calculés, aucune donnée personnelle inventée.')
        return None, None, None
    heads = [dict(sexe=h['sex'], age=h['age'], annee_naissance=h['birth_year']) for h in d['heads']]
    path = SKILL_ROOT/'data/mortalite'/f'{d["mortality_table"]}.csv'
    if not path.is_file():
        raise ValueError('Table de mortalité locale absente ; aucune substitution ni import automatique.')
    lives = sample_lifetimes(heads, path, draws=10000, seed=42, adjustment=d['mortality_adjustment'])
    longevity = mortality_summary(lives)
    warnings.add('Mortalité : table statistique, décès des deux têtes supposés indépendants ; aucune prévision individuelle.')
    if d['mortality_table']=='insee':
        warnings.add('INSEE période 2022 : âges officiels 0–100 ; queue logistique extrapolée 101–120 et fermeture terminale explicites.')
    else:
        warnings.add('TGH05/TGF05 : table générationnelle et fermeture artificielle à 121 ans ; année de naissance saisie utilisée.')
    if not d['mc_enabled']:
        return longevity, None, lives
    last, first = lives.max(axis=1), lives.min(axis=1)
    # Fiscal histories depend on release, not annuity (never deductible). Build
    # each unique monthly release once, then vectorize all annuity/payment paths.
    months = d['years']*12
    start = np.arange(months)/12
    end = np.minimum(last, d['libre_after'] if d['libre_after'] is not None else math.inf)
    if d['type']=='libre':
        end = np.zeros(len(last))
    end = np.minimum(end, d['years'])
    releases, indices = np.unique(np.round(end*12, 8), return_inverse=True)
    template = dict(d, monthly_annuity=0., departure_increase=0.)
    paths = [_viager_path(template, death=r/12, compute_irr=False) for r in releases]
    matrix = np.stack([p['flows'] for p in paths])[indices]
    death_fraction = np.clip((last[:,None]-start)*12, 0, 1)
    first_fraction = np.clip((first[:,None]-start)*12, 0, 1)
    factor = first_fraction+d['reversal']*(death_fraction-first_fraction)
    if len(heads)==1:
        factor = death_fraction
    if d['libre_after'] is not None and d['type']=='occupe':
        departed_alive = np.maximum(0, death_fraction-np.clip((d['libre_after']-start)*12,0,1))
        factor += factor/np.maximum(death_fraction,1e-10)*departed_alive*d['departure_increase']
    annuity = factor*d['monthly_annuity']*(1+d['annuity_growth'])**(np.arange(months)//12)
    matrix[:,1:] -= annuity
    valid = (last <= d['years']) | (d['monthly_annuity']==0)
    monthly, _ = _irr_matrix(matrix[valid]) if valid.any() else (np.array([]), None)
    annual = np.expm1(12*np.log1p(monthly))
    finite = annual[np.isfinite(annual)]
    npvs = matrix[valid] @ ((1+d['discount_rate'])**(-np.arange(months+1)/12))
    pct = lambda a, p: float(np.percentile(a,p)) if len(a) else None
    mc = dict(draws=10000, irr_median=pct(finite,50), irr_p10=pct(finite,10), irr_p90=pct(finite,90),
        npv_median=pct(npvs,50), adverse_longevity_years=longevity['p90'],
        valid_irr_draws=int(len(finite)), active_annuity_at_exit_draws=int((~valid).sum()), seed=42)
    if not valid.all():
        warnings.add('Monte Carlo : TRI/VAN calculés seulement pour les tirages avec rente éteinte à la sortie ; distribution conditionnelle et nombre de tirages exclus affichés.')
    return longevity, mc, lives


def calculate(data):
    d = validate(data)
    warnings = set()
    known_tmi = [rate for _,rate in FISCAL_PARAMS['ir']['tranches']]
    if not any(abs(d['tmi']-rate)<1e-9 for rate in known_tmi):
        warnings.add(f'TMI saisi {d["tmi"]*100:g} % hors des taux du barème fiscal courant ; taux historique ou hypothèse personnalisée à vérifier.')
    assumptions = [
        'Projection mensuelle, agrégée par année ; indexation annuelle à chaque anniversaire (année 2 = taux appliqué une fois).',
        'Impôts provisionnés à la fin de chaque année ; barème fiscal du millésime maintenu constant, fiscalité future non validée.',
        'Marge nominale = valorisation projetée moins coût net ; elle ne représente pas un gain encaissé.',
        'TRI/VAN de valorisation hypothétique avant frais et impôt de cession : acte, base fiscale et prix de revente non validés.',
    ]
    if d['usage']=='professionnel':
        warnings.add('Usage professionnel : régime fiscal saisi seulement simulé ; compatibilité juridique et fiscalité à valider.')
    if d['mode']=='viager' and d['rent_monthly']==0:
        warnings.add('Scénario sans revenus locatifs : loyer saisi nul. Ce calcul ne valide aucun rendement locatif ni impôt futur sur des loyers.')
    if d['released_other_charges'] is not None:
        assumptions.append(f'Autres charges annuelles : {d["other_charges"]:.2f} € pendant occupation, {d["released_other_charges"]:.2f} € après libération, avant revalorisation.')
    missing_costs = [key for key in ('other_fees','other_charges','annual_works','insurance','management_rate','vacancy_rate','renovation') if key not in data]
    if missing_costs:
        assumptions.append('Hypothèses non renseignées utilisées à zéro : '+', '.join(missing_costs)+'. À confirmer, absence distincte de coût nul vérifié.')
    if d['mode']=='portage':
        summary, annual = _portage(d, warnings)
        longevity = mc = None
        scenarios = []
        assumptions.extend(['Portage : rendement annuel versé mensuellement sur la quote-part, sans capitalisation.',
            'Sortie = valeur totale × quote-part/coût projet, moins capital restant dû et frais de sortie.',
            'Apport cash initial ; intérêts et assurance inclus dans les mensualités. Durée de détention arrondie au mois le plus proche.'])
    else:
        summary, annual = _viager(d, warnings)
        longevity, mc, lives = _demography(d, warnings)
        points = [('Court', longevity['p10'] if longevity else d['death_after']*.5),
                  ('Central', d['death_after']),
                  ('Long', longevity['p75'] if longevity else min(120,d['death_after']*1.5))]
        if longevity:
            points.append(('Longévité P90', longevity['p90']))
        scenarios = [_scenario(d, name, death) for name,death in points]
        if d['contract_kind']=='vente-terme':
            longevity=mc=None
            duration=d['payment_term_years']
            scenarios=[_scenario(d,'Central · durée contractuelle',duration),
                _scenario(d,'Défavorable · indexation et loyers',duration,
                    {'annuity_growth':min(1,d['annuity_growth']+0.01),'rent_monthly':d['rent_monthly']*0.8,'property_growth':min(d['property_growth'],0)})]
            assumptions.append('Vente à terme : mensualités dues pendant la durée contractuelle, indépendamment du décès ; aucune longévité du vendeur utilisée. Scénario défavorable : indexation +1 point et loyers -20 %, valeur sans hausse.')
        assumptions.extend(['Bouquet et rente constituent un prix d’acquisition, jamais une charge fiscale déductible.',
            'Charges payées chaque mois ; déduction au réel uniquement pendant les périodes louées, dépenses éligibles saisies supposées justifiées.',
            'Libération = premier événement entre décès du dernier survivant et départ saisi ; majoration seulement après départ et avant extinction.',
            'Deux têtes : rente intégrale avant premier décès, fraction de réversion saisie ensuite ; DUH jusqu’au dernier décès.',
            'Scénarios à durée fixe : décès à la durée saisie pour les deux têtes ; la distinction premier/dernier décès est calculée dans Monte Carlo.',
            'Statistiques de longévité issues de 10 000 tirages reproductibles, graine 42 ; P90 de longévité distinct du TRI P10.',
            'IFI : DUH réservé au vendeur pendant occupation, assiette acquéreur nulle ; pleine valeur dès libération au 1er janvier.',
            'Point mort = bouquet/frais d’acquisition + rente sans extinction atteint valeur libre initiale, hors financement, autres charges et loyers.',
            'Rente mensuelle du tableau = annuité effectivement versée dans l’année / 12, y compris départ, réversion et extinction.',
            'Coût net final inclut le remboursement du capital restant et les frais de sortie, avant impôt/frais de cession.'])
        if d['notary_amount'] is None:
            warnings.add('Frais notariés estimés par taux et base saisis ; prix/base de l’acte et devis notarial à confirmer.')
    if d['contract_kind']=='vente-terme':
        assumptions=[a for a in assumptions if not a.startswith(('Libération =','Deux têtes :','Scénarios à durée fixe','Statistiques de longévité'))]
    return dict(mode=d['mode'], name=d['name'], inputs=d, summary=summary,
        annual_flows=annual, scenarios=scenarios, longevity=longevity, mc=mc,
        warnings=sorted(warnings), assumptions=assumptions, sources=deepcopy(SOURCES),
        fiscal_year=FISCAL_YEAR, generated_at=datetime.now(timezone.utc).isoformat())
