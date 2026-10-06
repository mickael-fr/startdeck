"""French fiscal comparison; all legislative rates and thresholds live in YAML.

Amounts are annual EUR. Continuous cents calculation, not a tax return.
State branches separately retain the counterfactual and operation histories.
"""
from copy import deepcopy
from math import floor, isfinite


def _number(value, label, nonnegative=True):
    result = float(value)
    if not isfinite(result) or (nonnegative and result < 0):
        raise ValueError(f'{label}: montant fini positif ou nul requis')
    return result


def _progressive(amount, brackets):
    result = 0.0
    for i, (lower, rate) in enumerate(brackets):
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else amount
        result += max(0, min(amount, upper) - lower) * rate
    return result


def income_tax(income, profile, params):
    """IR barème, quotient ordinary cap and décote, before credits/CEHR/CDHR."""
    income = max(0, _number(income, 'revenu', False))
    cfg = params['ir']
    parts = _number(profile.get('parts', 1), 'parts')
    base = _number(profile.get('parts_base', 1), 'parts_base')
    if base <= 0 or parts < base:
        raise ValueError('parts >= parts_base > 0 requis')
    raw = parts * _progressive(income / parts, cfg['tranches'])
    extra = parts - base
    halves = floor(extra * 2 + 1e-9)
    quarters = (extra * 2 - halves) * 2
    cap = halves * cfg['plafond_demi_part'] + quarters * cfg['plafond_quart_part']
    if profile.get('plafond_quotient_total') is not None:
        cap = _number(profile['plafond_quotient_total'], 'plafond quotient')
    raw = max(raw, base * _progressive(income / base, cfg['tranches']) - cap)
    commune = profile.get('situation') in ('marie', 'maries', 'pacse', 'pacs', 'couple')
    constant = cfg['decote_commune' if commune else 'decote_individuelle']
    return max(0.0, raw - max(0.0, constant - cfg['decote_taux'] * raw))


def _consume(net, records, year, duration):
    retained = []
    for record in sorted(records, key=lambda r: r['year']):
        if record['year'] > year:
            raise ValueError('Déficit futur dans état fiscal')
        if year - record['year'] > duration:
            continue
        amount = _number(record['amount'], 'déficit reporté')
        used = min(max(0, net), amount)
        net -= used
        if amount > used:
            retained.append(dict(year=record['year'], amount=amount - used))
    return net, retained


def _foncier(rent, charges, interest, regime, cfg, branch, year):
    if regime == 'micro-foncier':
        if rent > cfg['micro_seuil']:
            raise ValueError('Micro-foncier : seuil global du foyer dépassé, choisir réel')
        net = rent * (1 - cfg['micro_abattement'])
        global_deficit = 0
        new_deficit = 0
    elif regime == 'reel':
        net = rent - charges - interest
        noninterest_deficit = min(max(0, -net), charges)
        global_deficit = min(noninterest_deficit, cfg['deficit_global_plafond'])
        new_deficit = max(0, -net) - global_deficit
    else:
        raise ValueError('Régime autres fonciers : reel ou micro-foncier')
    taxable, records = _consume(max(0, net), branch.get('foncier_deficits', []), year, cfg['report_ans'])
    if new_deficit:
        records.append(dict(year=year, amount=new_deficit))
    branch['foncier_deficits'] = records
    return taxable - global_deficit, taxable, global_deficit


def rental_tax(rent, charges, profile, params, state=None, interest=0, depreciation=0):
    """Marginal tax from with/without acquisition, without mutating input state.

    Returned state is passed into the next annual call. Rente/bouquet are purchase
    price, never charges. depreciation = annual legally deductible allocation.
    """
    rent = _number(rent, 'loyer')
    charges = _number(charges, 'charges')
    interest = _number(interest, 'intérêts')
    depreciation = _number(depreciation, 'amortissement')
    regime = profile.get('regime', 'reel')
    if regime not in ('reel', 'micro-foncier', 'lmnp-reel', 'lmnp-micro'):
        raise ValueError('Régime fiscal inconnu')
    state = deepcopy(state or {})
    year = int(state.get('year', params['annee_revenus']))
    baseline = state.setdefault('baseline', {})
    operation = state.setdefault('operation', {})
    other_rent = _number(profile.get('autres_revenus_fonciers', 0), 'autres loyers')
    other_charges = _number(profile.get('autres_charges_foncieres', 0), 'autres charges')
    other_interest = _number(profile.get('autres_interets_fonciers', 0), 'autres intérêts')
    other_regime = profile.get('regime_autres_fonciers', regime if not regime.startswith('lmnp') else 'reel')
    b_income, b_ps, _ = _foncier(other_rent, other_charges, other_interest, other_regime,
                                params['foncier'], baseline, year)
    used_amort = 0.0
    if not regime.startswith('lmnp'):
        op_income, op_ps, global_deficit = _foncier(other_rent + rent, other_charges + charges,
                    other_interest + interest, regime, params['foncier'], operation, year)
        social = (op_ps - b_ps) * params['foncier']['ps']
        taxable_operation = op_ps
    else:
        op_other, op_other_ps, global_deficit = _foncier(other_rent, other_charges, other_interest,
                    other_regime, params['foncier'], operation, year)
        cfg = params['lmnp']
        if regime == 'lmnp-micro':
            if rent > cfg['micro_seuil']:
                raise ValueError('LMNP micro : seuil prudent dépassé; vérifier N-1/N-2 et régime')
            net = max(0, rent - max(cfg['micro_minimum'], rent * cfg['micro_abattement']))
        else:
            net = rent - charges - interest
        # Current accounting depreciation determines the year's BIC result.
        current_amort = min(max(0, net), depreciation) if regime == 'lmnp-reel' else 0
        taxable, records = _consume(max(0, net) - current_amort,
                    operation.get('lmnp_deficits', []), year, cfg['report_ans'])
        if net < 0:
            records.append(dict(year=year, amount=-net))
        operation['lmnp_deficits'] = records
        if regime == 'lmnp-reel':
            pool = _number(operation.get('amortissements', 0), 'amortissements reportés')
            deferred_used = min(taxable, pool)
            taxable -= deferred_used
            used_amort = current_amort + deferred_used
            operation['amortissements'] = pool - deferred_used + depreciation - current_amort
        taxable_operation = taxable
        op_income = op_other + taxable
        social = (op_other_ps - b_ps) * params['foncier']['ps'] + taxable * cfg['ps']
    delta_income = op_income - b_income
    income = profile.get('revenu_imposable')
    approximation = income is None
    warnings = []
    thresholds = []
    if approximation:
        if profile.get('tmi') is None:
            raise ValueError('Revenu imposable ou TMI requis pour calculer la fiscalité locative')
        tmi = _number(profile['tmi'], 'TMI')
        if tmi > 1:
            raise ValueError('TMI attendu sous forme de fraction (ex. 0.30)')
        ir = delta_income * tmi
        before = after = None
        warnings.append('Approximation TMI : revenu imposable inconnu, franchissements de tranches inconnus.')
    else:
        before = income_tax(float(income) + b_income, profile, params)
        after = income_tax(float(income) + op_income, profile, params)
        ir = after - before
        parts = float(profile.get('parts', 1))
        quotient_before = max(0, float(income) + b_income) / parts
        quotient_after = max(0, float(income) + op_income) / parts
        for boundary, rate in params['ir']['tranches'][1:]:
            upward = quotient_before <= boundary < quotient_after
            downward = quotient_after <= boundary < quotient_before
            if upward or downward:
                direction = 'hausse' if upward else 'baisse'
                thresholds.append(dict(type='ir', seuil_par_part=boundary,
                                       taux=rate, direction=direction))
                warnings.append(f'Franchissement de tranche IR en {direction} : seuil '
                                f'{boundary:,.0f} € par part, tranche à {rate * 100:g} % '
                                '(taux appliqué à la seule fraction concernée).')
    state['year'] = year + 1
    return dict(total=ir + social, ir=ir, ps=social, ir_sans=before, ir_avec=after,
                approximation=approximation, taxable_operation=taxable_operation,
                revenu_incremental=delta_income, deficit_global=global_deficit,
                amortissement_deduit=used_amort, state=state, annee=year,
                warnings=warnings, thresholds=thresholds)


def capital_gains(sale, basis, years, params, depreciation=0):
    """Ordinary property PV; basis already includes validated acquisition costs.

    depreciation = cumulative LMNP amortizations actually deducted and subject
    to reintegration, not merely accounting amortizations.
    """
    sale = _number(sale, 'cession')
    basis = _number(basis, 'prix de revient')
    years = floor(_number(years, 'années révolues'))
    depreciation = _number(depreciation, 'amortissement réintégré')
    cfg = params['plus_value']
    gain = max(0, sale - basis + depreciation)
    def abatement(schedule):
        return min(1, sum(max(0, min(years, end) - start + 1) * rate for start,end,rate in schedule))
    ir_base = gain * (1 - abatement(cfg['abattement_ir']))
    ps_base = gain * (1 - abatement(cfg['abattement_ps']))
    surtax = 0.0
    if ir_base > cfg['surtaxe_seuil']:
        for ceiling, rate, smooth in cfg['surtaxe']:
            if ceiling is None or ir_base <= ceiling:
                surtax = ir_base * rate - ((ceiling or ir_base) - ir_base) * smooth
                break
    return ir_base * cfg['ir'] + ps_base * cfg['ps'] + surtax


def ifi_tax(asset, params):
    """IFI before donation deductions, income cap or foreign tax credits."""
    asset = _number(asset, 'patrimoine IFI')
    cfg = params['ifi']
    if asset <= cfg['seuil']:
        return 0.0
    tax = _progressive(asset, cfg['tranches'])
    if asset < cfg['decote_limite']:
        tax -= cfg['decote_constante'] - cfg['decote_taux'] * asset
    return max(0.0, tax)


def ifi_increment(value, occupied, profile, params):
    """Acquirer's increment; occupied defaults to genuine seller-retained DUH.

    Occupation alone cannot establish an IFI exemption. Non-DUH requires an
    explicit validated taxable value; no actuarial occupancy discount applied.
    """
    value = _number(value, 'valeur bien')
    existing = _number(profile.get('patrimoine_immobilier_net', 0), 'patrimoine net')
    if occupied:
        explicit = profile.get('valeur_ifi_occuppee')
        if explicit is not None:
            addition = _number(explicit, 'assiette IFI validée')
        elif profile.get('droit_occupation', 'duh') == 'duh':
            addition = 0
        else:
            raise ValueError('Occupation sans DUH : assiette IFI à faire valider')
    else:
        addition = value
    return ifi_tax(existing + addition, params) - ifi_tax(existing, params)


def ifi_threshold_crossed(value, occupied, profile, params):
    """True when acquisition triggers IFI liability under the same DUH rules.

    The ordinary IFI increment stays a float. This signal addresses the liability
    threshold, not every band of the progressive IFI tariff.
    """
    existing = _number(profile.get('patrimoine_immobilier_net', 0), 'patrimoine net')
    increment = ifi_increment(value, occupied, profile, params)
    return existing <= params['ifi']['seuil'] and increment > 0
