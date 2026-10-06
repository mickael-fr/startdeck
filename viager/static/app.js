'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('simulation-form');
  const money = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0});
  const number = new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2});
  const STORAGE = 'viager-studio-inputs-v1';
  let bootstrap, mode = 'viager', revision = 0, calculatedRevision = -1, currentResult = null, busy = false;
  const rateFields = new Set();
  const fields = [];
  let rentHome;
  // name, label, kind, options. All rates cross the API boundary as fractions.
  const groups = [
    ['Offre', false, [
      ['name', 'Nom de l’étude', 'text', {full: true}],
      ['contract_kind','Nature du contrat','select',{values:[['viager','Viager'],['vente-terme','Vente à terme']],mode:'viager'}],
      ['payment_term_years','Durée contractuelle des versements (années)','number',{min:0.0833333,max:60,nullable:true,mode:'viager',hint:'Vente à terme uniquement : durée fixe indépendante du décès.'}],
      ['type', 'Type de viager', 'select', {values: [['occupe','Occupé'],['libre','Libre']], mode: 'viager'}],
      ['usage', 'Usage du bien', 'select', {values: [['habitation','Habitation'],['professionnel','Professionnel']], mode: 'viager'}],
      ['property_value', 'Valeur libre du bien (€)', 'number', {min: 0, mode: 'viager'}],
      ['occupied_value', 'Valeur occupée (€)', 'number', {min: 0, mode: 'viager'}],
      ['bouquet', 'Bouquet (€)', 'number', {min: 0, mode: 'viager'}],
      ['monthly_annuity', 'Rente / mensualité (€)', 'number', {min: 0, mode: 'viager'}],
      ['share_investment', 'Votre investissement (€)', 'number', {min: 0, mode: 'portage'}],
      ['project_cost', 'Coût total du projet (€)', 'number', {min: 0, mode: 'portage'}],
      ['exit_project_value', 'Valeur totale à la sortie (€)', 'number', {min: 0, nullable: true, mode: 'portage', hint: 'Laisser vide si la valeur de sortie est inconnue.'}],
      ['annual_yield', 'Rendement annuel annoncé (%)', 'rate', {mode: 'portage', hint: 'Rendement brut : le taux ne définit pas son traitement fiscal.'}],
      ['holding_years', 'Durée de portage (années)', 'number', {min: 0.25, step: 0.25, mode: 'portage'}],
      ['downpayment', 'Apport (€)', 'number', {min: 0, mode: 'portage'}],
      ['source_url', 'Lien de l’annonce / source', 'url', {full: true}],
      ['notes', 'Notes de l’étude', 'textarea', {full: true}]
    ]],
    ['Charges et frais', false, [
      ['notary_basis', 'Base des frais de notaire', 'select', {values: [['occupied','Valeur occupée'],['full','Valeur libre'],['custom','Montant personnalisé']], mode: 'viager'}],
      ['notary_rate', 'Frais de notaire estimés (%)', 'rate', {min: 0, hint: 'Hypothèse de simulation, à confirmer avec le notaire.'}],
      ['notary_amount', 'Frais de notaire personnalisés (€)', 'number', {min: 0, nullable: true, hint: 'Montant total requis en mode personnalisé. Pour une base occupée ou libre, vide = estimation avec le taux.'}],
      ['other_fees', 'Autres frais initiaux (€)', 'number', {min: 0}],
      ['property_tax', 'Taxe foncière annuelle (€)', 'number', {min: 0, mode: 'viager'}],
      ['other_charges', 'Autres charges annuelles (€)', 'number', {min: 0, mode: 'viager'}],
      ['released_other_charges', 'Autres charges après libération (€ / an)', 'number', {min: 0, nullable: true, mode: 'viager', hint: 'Vide = même montant ; indiquer la totalité des charges si la quote-part augmente après occupation.'}],
      ['annual_works', 'Travaux annuels (€)', 'number', {min: 0, mode: 'viager'}],
      ['insurance', 'Assurance annuelle (€)', 'number', {min: 0, mode: 'viager'}],
      ['renovation', 'Travaux à la libération (€)', 'number', {min: 0, mode: 'viager'}],
      ['charges_growth', 'Hausse des charges / an (%)', 'rate', {mode: 'viager'}]
    ]],
    ['Loyers', false, [
      ['rent_monthly', 'Loyer mensuel à la libération (€)', 'number', {min: 0}],
      ['rent_growth', 'Hausse des loyers / an (%)', 'rate'],
      ['vacancy_rate', 'Vacance locative (%)', 'rate', {min: 0, max: 100}],
      ['management_rate', 'Gestion locative (%)', 'rate', {min: 0, max: 100}]
    ], 'viager'],
    ['Fiscalité', false, [
      ['regime', 'Régime locatif', 'select', {values: [['micro-foncier','Location nue · micro-foncier'],['reel','Location nue · réel'],['lmnp-micro','Meublé · micro-BIC'],['lmnp-reel','Meublé · réel']]}],
      ['tax_method', 'Méthode pour l’impôt', 'select', {values: [['income','Revenu imposable du foyer'],['tmi','TMI · approximation']]}],
      ['taxable_income', 'Revenu imposable annuel (€)', 'number', {min: 0, nullable: true, full: true, hint: 'Revenu net imposable, distinct du revenu fiscal de référence (RFR). Aucun RFR n’est converti.'}],
      ['tmi', 'Taux marginal d’imposition (%)', 'rate', {min: 0, max: 100, hint: 'Utilisé uniquement par la méthode TMI.'}],
      ['situation', 'Situation du foyer', 'select', {values: [['celibataire','Personne seule'],['couple','Couple']]}],
      ['parts', 'Nombre de parts fiscales', 'number', {min: 0.5, step: 0.5, hint: 'L’origine des parts supplémentaires peut modifier leur plafonnement.'}],
      ['parts_base', 'Parts de base du foyer', 'number', {min: 0.5, step: 0.5, hint: 'Avant les parts supplémentaires.'}],
      ['quotient_cap', 'Plafond total du quotient (€)', 'number', {min: 0, nullable: true, hint: 'Vide = plafonnement ordinaire ; total particulier à renseigner selon l’origine des parts.'}],
      ['other_rent', 'Autres loyers annuels (€)', 'number', {min: 0}],
      ['other_rent_charges', 'Charges des autres loyers (€)', 'number', {min: 0}],
      ['ifi_assets', 'Autre patrimoine taxable IFI (€)', 'number', {min: 0}],
      ['amortization', 'Amortissement annuel au réel (€)', 'number', {min: 0}]
    ], 'viager'],
    ['Hypothèses de projection', false, [
      ['years', 'Horizon d’étude (années)', 'number', {min: 1, max: 60, step: 1}],
      ['property_growth', 'Hausse de valeur / an (%)', 'rate', {mode: 'viager'}],
      ['discount_rate', 'Taux d’actualisation annuel (%)', 'rate'],
      ['death_after', 'Décès après (années)', 'number', {min: 0, step: 'any', mode: 'viager', hint: 'Hypothèse explicite, pas une prévision personnelle.'}],
      ['libre_after', 'Libération après (années)', 'number', {min: 0, nullable: true, step: 0.25, mode: 'viager', hint: 'Ex. EHPAD : 6 mois = 0,5 an ; vide = libération au décès.'}],
      ['departure_increase', 'Majoration à la libération (%)', 'rate', {min: 0, mode: 'viager'}],
      ['annuity_growth', 'Indexation de la rente / an (%)', 'rate', {mode: 'viager'}],
      ['reversal', 'Réversion de la rente (%)', 'rate', {min: 0, max: 100, mode: 'viager'}]
    ]],
    ['Démographie · facultatif', true, [
      ['mortality_table', 'Table de mortalité', 'select', {values: [['insee','INSEE · population générale'],['tgh05','TGH05 · table actuarielle']]}],
      ['mortality_adjustment', 'Coefficient de mortalité', 'number', {min: 0.01, step: 0.01, hint: '1 = table sans ajustement ; hypothèse personnelle.'}],
      ['mc_enabled', 'Activer la simulation probabiliste', 'checkbox']
    ], 'viager'],
    ['Financement · facultatif', true, [
      ['loan_amount', 'Montant emprunté (€)', 'number', {min: 0}],
      ['loan_years', 'Durée du prêt (années)', 'number', {min: 0, max: 60, step: 1}],
      ['loan_rate', 'Taux annuel du crédit (%)', 'rate', {min: 0}],
      ['loan_insurance_rate', 'Assurance du crédit / an (%)', 'rate', {min: 0}],
      ['loan_payment_override', 'Mensualité personnalisée (€)', 'number', {min: 0, nullable: true, hint: 'Vide = mensualité calculée selon les taux.'}],
      ['loan_exit_fee', 'Frais de sortie du prêt (€)', 'number', {min: 0}]
    ]]
  ];
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function status(message, kind = '') { $('status').textContent = message; $('status').className = `status ${kind}`; }
  function disableCalculation(disabled) { $('calculate').disabled=disabled; $('analyse-url').disabled=disabled; $('calculate-rent').disabled=disabled; }
  function dirty() {
    revision++; calculatedRevision = -1; $('pdf').disabled = true; clearPDF();
    if (currentResult) status('Saisie modifiée : les résultats affichés correspondent au calcul précédent. Recalculez avant le PDF.');
  }
  function buildFields() {
    groups.forEach(([title, optional, definitions, onlyMode], index) => {
      const section = el(optional ? 'details' : 'section', null, optional ? 'optional-section' : 'form-section');
      if (onlyMode) section.dataset.mode = onlyMode;
      const heading = el(optional ? 'summary' : 'h3', title);
      if (!optional) heading.prepend(el('span', String(index + 1).padStart(2,'0'), 'section-number'));
      section.append(heading);
      const grid = el('div', null, 'fields-grid');
      definitions.forEach(([name, label, kind, options = {}]) => {
        const wrap = el('div', null, `field${options.full ? ' full' : ''}${kind === 'checkbox' ? ' checkbox' : ''}`);
        if (options.mode) wrap.dataset.mode = options.mode;
        const labelNode = el('label', label); labelNode.htmlFor = `input-${name}`;
        let input;
        if (kind === 'select') {
          input = el('select');
          options.values.forEach(([value, label]) => { const option = el('option', label); option.value = value; input.append(option); });
        } else if (kind === 'textarea') input = el('textarea');
        else {
          input = el('input'); input.type = kind === 'rate' ? 'number' : kind;
          if (kind === 'number' || kind === 'rate') {
            input.step = options.step || 'any'; input.inputMode = 'decimal';
            if (options.min != null) input.min = options.min;
            if (options.max != null) input.max = options.max;
          }
        }
        input.id = `input-${name}`; input.name = name;
        if (kind === 'rate') rateFields.add(name);
        fields.push({name, kind, input, nullable: !!options.nullable});
        wrap.append(labelNode, input);
        if (options.hint) { const hint = el('small', options.hint); hint.id = `hint-${name}`; input.setAttribute('aria-describedby', hint.id); wrap.append(hint); }
        grid.append(wrap);
      });
      section.append(grid);
      if (title.startsWith('Démographie')) {
        const heads = el('div', null, 'heads-wrap');
        heads.append(el('p', 'Ajoutez au maximum deux personnes, uniquement avec des âges connus. Une année de naissance peut rester vide. Sans âge, aucune longévité n’est inventée.'));
        const rows = el('div'); rows.id = 'head-rows'; heads.append(rows);
        const add = el('button', 'Ajouter une personne'); add.id = 'add-head'; add.type = 'button';
        add.addEventListener('click', () => { addHead({sex:'F',age:null,birth_year:null}); dirty(); });
        heads.append(add); section.append(heads);
      }
      $('fields').append(section);
      if (title === 'Fiscalité') {
        const portageTax=el('section',null,'form-section'); portageTax.dataset.mode='portage';
        portageTax.append(el('h3','Fiscalité'),el('p','Portage calculé avant fiscalité : régime du contrat à confirmer.','muted'));
        $('fields').append(portageTax);
      }
    });
  }
  function addHead(head) {
    if ($('head-rows').children.length >= 2) return;
    const row = el('div', null, 'head-row');
    [['sex','Sexe','select'],['age','Âge connu','number'],['birth_year','Année naissance','number']].forEach(([name,label,kind]) => {
      const wrap = el('div', null, 'field'); const input = el(kind === 'select' ? 'select' : 'input');
      const id = `head-${Date.now()}-${$('head-rows').children.length}-${name}`;
      input.id = id; input.dataset.head = name;
      if (kind === 'select') [['F','Femme'],['M','Homme']].forEach(([value,text]) => { const option = el('option',text); option.value=value; input.append(option); });
      else { input.type='number'; input.step='1'; input.min=name === 'age' ? '0' : '1900'; input.max=name === 'age' ? '120' : String(new Date().getFullYear()); }
      input.value = head[name] ?? ''; const labelNode = el('label', label); labelNode.htmlFor = id; wrap.append(labelNode,input); row.append(wrap);
    });
    const remove = el('button','Retirer'); remove.type='button'; remove.setAttribute('aria-label','Retirer cette personne');
    remove.addEventListener('click', () => { row.remove(); $('add-head').disabled=false; dirty(); }); row.append(remove);
    $('head-rows').append(row); $('add-head').disabled = $('head-rows').children.length >= 2;
  }
  function changeMode(nextMode, invalidate = true) {
    mode = nextMode === 'portage' ? 'portage' : 'viager';
    document.querySelectorAll('[data-mode]').forEach(node => {
      if (node.tagName === 'BUTTON') node.setAttribute('aria-pressed', String(node.dataset.mode === mode));
      else node.hidden = node.dataset.mode !== mode;
    });
    if (invalidate) dirty();
    contractVisibility();
    rentalVisibility();
  }
  function rentalVisibility(){
    const input=$('input-rent_monthly'),wrap=input.closest('.field');
    const free=mode==='viager'&&$('input-type').value==='libre';
    if(!rentHome)rentHome=wrap.parentElement;
    $('rental-entry').hidden=!free;
    if(free){$('rental-field').append(wrap);input.setAttribute('form','simulation-form');}
    else {rentHome.insertBefore(wrap,rentHome.firstChild);input.removeAttribute('form');}
    wrap.querySelector('label').textContent=free?'Loyer mensuel hors charges retenu (€)':'Loyer mensuel à la libération (€)';
    input.required=free;input.min=free?'0.01':'0';
    if(free&&Number(input.value)<=0)input.value='';
  }
  function contractVisibility(){
    const term=$('input-contract_kind')?.value==='vente-terme';
    for(const name of ['death_after','departure_increase','reversal','mc_enabled','mortality_table','mortality_adjustment']){
      const input=$('input-'+name);if(input)input.closest('.field').hidden=term||mode!=='viager';
    }
    $('input-payment_term_years').closest('.field').hidden=!term||mode!=='viager';
    $('add-head').hidden=term; $('head-rows').hidden=term;
  }
  function fill(data, message) {
    const values = {...bootstrap.defaults, ...data};
    fields.forEach(({name,kind,input}) => {
      const value = values[name];
      if (kind === 'checkbox') input.checked = value === true;
      else input.value = value == null ? '' : rateFields.has(name) ? String(Math.round(Number(value)*100*1e8)/1e8) : String(value);
    });
    $('head-rows').replaceChildren(); (Array.isArray(values.heads) ? values.heads : []).slice(0,2).forEach(addHead);
    $('add-head').disabled = $('head-rows').children.length >= 2;
    changeMode(values.mode, false); dirty(); clearResults(); if (message) status(message);
  }
  function collect() {
    const data = {mode};
    fields.forEach(({name,kind,input}) => {
      if (kind === 'checkbox') data[name] = input.checked;
      else if (kind === 'number' || kind === 'rate') data[name] = input.value.trim() === '' ? null : Number(input.value)/(rateFields.has(name) ? 100 : 1);
      else data[name] = input.value;
    });
    data.heads = Array.from($('head-rows').children).map(row => Object.fromEntries(Array.from(row.querySelectorAll('[data-head]')).map(input => [input.dataset.head,input.dataset.head === 'sex' ? input.value : input.value === '' ? null : Number(input.value)])));
    return data;
  }
  function clearResults() { currentResult=null; calculatedRevision=-1; $('results').hidden=true; $('empty-results').hidden=false; $('pdf').disabled=true; $('result-name').textContent='En attente de calcul'; }
  function fmt(value, type = 'money') {
    if (value == null || !Number.isFinite(Number(value))) return 'À confirmer';
    return type === 'percent' ? `${number.format(value*100)} %` : type === 'number' ? number.format(value) : money.format(value);
  }
  function renderTable(target, headers, rows, caption) {
    const table=el('table'); const cap=el('caption',caption); cap.className='muted'; table.append(cap);
    const head=el('thead'); const headRow=el('tr'); headers.forEach(label => { const th=el('th',label); th.scope='col'; headRow.append(th); }); head.append(headRow); table.append(head);
    const body=el('tbody'); rows.forEach(({values,adverse}) => { const tr=el('tr',null,adverse ? 'adverse' : ''); values.forEach(value => tr.append(el('td',value))); body.append(tr); }); table.append(body); target.replaceChildren(table);
  }
  function render(result) {
    currentResult=result; $('empty-results').hidden=true; $('results').hidden=false; $('result-name').textContent=result.name || 'Votre étude';
    const s=result.summary || {}; $('cards').replaceChildren();
    $('npv-reading').textContent=s.npv == null ? 'VAN non calculable avec les données disponibles.' : s.npv < 0 ? 'VAN négative : ce scénario reste sous le rendement demandé. Ce chiffre n’est pas une perte de trésorerie du même montant.' : 'VAN positive ou nulle : ce scénario atteint le rendement demandé, sous réserve des hypothèses et coûts inclus.';
    const effort=s.year1_monthly_effort;
    [['Budget initial',s.initial_cash,'money','Apport de trésorerie initial','primary-card'],
      ['Effort mensuel · an 1',effort,'money',effort < 0 ? 'Excédent de trésorerie mensuel' : 'Décaissement mensuel moyen',''],
      ['Coût net cumulé',s.total_net_cost,'money',`Marge projetée : ${fmt(s.nominal_margin)}`,''],
      ['TRI annuel',s.irr,'percent',`TRI de valorisation avant cession · VAN : ${fmt(s.npv)}`,'']].forEach(([label,value,type,note,cls]) => {
      const card=el('div',null,`card ${cls}`); card.append(el('span',label,'card-label'),el('strong',fmt(value,type),`card-value${value == null ? ' unknown' : ''}`),el('span',note,'card-note')); $('cards').append(card);
    });
    $('warnings').replaceChildren(); (result.warnings || []).forEach(message => $('warnings').append(el('div',message,'warning')));
    chart($('value-chart'),result.annual_flows || [],false); chart($('flow-chart'),result.annual_flows || [],true);
    const scenarios=result.scenarios || [];
    $('scenarios-section').hidden=scenarios.length === 0;
    $('longevity-section').hidden=result.mode === 'portage';
    renderTable($('scenarios'),['Scénario',result.inputs.contract_kind==='vente-terme'?'Versements (ans)':'Décès (ans)','Libération (ans)','Effort / mois','Coût net','Marge','TRI','VAN'],scenarios.map(row => ({adverse:/défavor|advers|long|stress/i.test(row.name || ''),values:[row.name,fmt(row.death_after,'number'),fmt(row.libre_after,'number'),fmt(row.monthly_effort),fmt(row.total_net_cost),fmt(row.nominal_margin),fmt(row.irr,'percent'),fmt(row.npv)]})),scenarios.length ? 'Projection selon les hypothèses de scénario' : 'Aucun scénario disponible');
    $('longevity').replaceChildren();
    if (result.mode === 'portage') $('longevity').append(el('p','La démographie ne s’applique pas à cette simulation de portage.'));
    else if (result.inputs.contract_kind==='vente-terme') $('longevity').append(el('p',`Vente à terme : ${fmt(result.inputs.payment_term_years,'number')} ans de versements contractuels indépendants du décès. La longévité du vendeur n’intervient pas dans ce calcul.`));
    else if (!result.longevity) $('longevity').append(el('p','Démographie à confirmer : aucun résultat de longévité sans âges connus. Les durées de décès et de libération saisies restent des hypothèses.'));
    else {
      const list=el('div',null,'metric-list');
      [['mean','Durée moyenne (ans)'],['median','Durée médiane (ans)'],['p10','Durée · percentile 10'],['p90','Durée · percentile 90'],['prob_survival_10','Probabilité de survie à 10 ans'],['prob_survival_20','Probabilité de survie à 20 ans']].forEach(([key,label]) => { const item=el('div'); item.append(el('span',label),el('strong',fmt(result.longevity[key],key.startsWith('prob') ? 'percent' : 'number'))); list.append(item); }); $('longevity').append(list);
    }
    if (result.mc) {
      $('longevity').append(el('p',`Simulation probabiliste : ${fmt(result.mc.draws,'number')} tirages ; TRI médian ${fmt(result.mc.irr_median,'percent')} ; percentiles 10 / 90 : ${fmt(result.mc.irr_p10,'percent')} / ${fmt(result.mc.irr_p90,'percent')}.`));
      $('longevity').append(el('p',`Tirages utilisés pour le TRI : ${fmt(result.mc.valid_irr_draws,'number')}. Tirages exclus avec une rente encore active à la sortie : ${fmt(result.mc.active_annuity_at_exit_draws,'number')}.`));
      if (result.mc.active_annuity_at_exit_draws > 0) $('longevity').append(el('p','La distribution du TRI est conditionnelle aux tirages retenus. Les tirages avec une rente encore active à la sortie sont exclus faute de valeur de cession avec cette charge confirmée.'));
    }
    else $('longevity').append(el('p','Simulation probabiliste non calculée.'));
    renderTable($('annual'),['Année','Rente / mois','Rente','Loyers','Charges','Fiscalité','Crédit','Effort net','Coût cumulé','Valeur','Marge','Capital restant'],(result.annual_flows || []).map(row => ({values:[row.year,...['annuity_monthly','annuity','rent','charges','tax','loan','net_flow','cumulative_cost','property_value','nominal_margin','loan_remaining'].map(key=>fmt(key === 'net_flow' && row[key] != null ? -row[key] : row[key]))]})),'Flux annuels en euros ; effort positif = décaissement');
    const list=el('ul'); (result.assumptions || []).forEach(message => list.append(el('li',message))); $('assumptions').replaceChildren(list);
    const sourceList=el('ul'); (result.sources || []).forEach(source => {
      const item=el('li'); let url; try { url=new URL(source.url); } catch { url=null; }
      if (url && ['http:','https:'].includes(url.protocol)) { const link=el('a',source.label || source.url); link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer'; item.append(link); }
      else item.textContent=source.label || 'Source locale'; sourceList.append(item);
    }); $('sources').replaceChildren(sourceList);
    const date=new Date(result.generated_at); $('generated').textContent=`Millésime fiscal ${result.fiscal_year ?? 'à confirmer'}${Number.isNaN(date.getTime()) ? '' : ` · calcul du ${date.toLocaleString('fr-FR',{timeZone:'Europe/Paris'})} (Paris)`}`;
  }
  function chart(target, rows, flow) {
    if (!rows.length) { target.replaceChildren(el('p','Aucun flux disponible.','muted')); return; }
    const ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg'); svg.setAttribute('viewBox','0 0 640 220'); svg.setAttribute('role','img');
    const title=document.createElementNS(ns,'title'); title.textContent=flow ? 'Effort annuel : positif pour un décaissement, négatif pour un excédent.' : 'Évolution du coût net cumulé et de la valeur projetée ; données détaillées dans le tableau des flux annuels.'; svg.append(title);
    if (flow) rows=rows.map(row=>({...row,net_flow:row.net_flow == null ? null : -row.net_flow}));
    const keys=flow ? ['net_flow'] : ['cumulative_cost','property_value'];
    const finite=rows.flatMap(row=>keys.map(key=>row[key])).filter(value=>value != null && Number.isFinite(Number(value))).map(Number);
    if (!finite.length) { target.replaceChildren(el('p','Valeurs à confirmer.','muted')); return; }
    let min=Math.min(0,...finite),max=Math.max(0,...finite); if(max===min) max=min+1;
    const x=i=>64+i/(Math.max(1,rows.length-1))*562, y=v=>180-(Number(v)-min)/(max-min)*158;
    function draw(tag,attrs,text) { const node=document.createElementNS(ns,tag); Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value))); if(text != null)node.textContent=text; svg.append(node); return node; }
    [min,(min+max)/2,max].forEach(value=> { draw('line',{x1:64,x2:626,y1:y(value),y2:y(value),stroke:'#e1e8ed'}); draw('text',{x:57,y:y(value)+4,'text-anchor':'end',fill:'#526575','font-size':11},Math.abs(value)>=1000 ? `${number.format(value/1000)} k€` : `${number.format(value)} €`); });
    draw('line',{x1:64,x2:626,y1:y(0),y2:y(0),stroke:'#a3b7c4'});
    if(flow) {
      rows.forEach((row,i)=> { if(row.net_flow == null)return; const width=Math.max(3,Math.min(24,500/rows.length)); const v=Number(row.net_flow); const bar=draw('rect',{x:x(i)-width/2,y:Math.min(y(v),y(0)),width,height:Math.max(1,Math.abs(y(v)-y(0))),rx:2,fill:v<0 ? '#087f79' : '#34546c'}); const t=document.createElementNS(ns,'title');t.textContent=`Année ${row.year} : ${fmt(v)} ${v<0 ? 'd’excédent' : 'de décaissement'}`;bar.append(t); });
    } else keys.forEach((key,index)=> {
      let d='',previous=false; rows.forEach((row,i)=> { if(row[key] == null || !Number.isFinite(Number(row[key]))) {previous=false;return;} d+=`${previous ? ' L' : ' M'}${x(i)} ${y(row[key])}`;previous=true; }); draw('path',{d,fill:'none',stroke:index ? '#087f79' : '#34546c','stroke-width':3,'stroke-linejoin':'round'});
    });
    const indexes=Array.from(new Set([0,Math.floor((rows.length-1)/2),rows.length-1])); indexes.forEach(i=>draw('text',{x:x(i),y:207,'text-anchor':'middle',fill:'#526575','font-size':11},`An ${rows[i].year}`)); target.replaceChildren(svg);
  }
  async function request(path,data,binary=false) {
    if(window.ViagerBackend) return window.ViagerBackend.request(path,data,binary);
    let response;
    try {response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}
    catch {throw new Error('Le lecteur local Viager Studio ne répond pas. Relancez « Ouvrir Viager Studio.cmd », puis cliquez à nouveau sur Analyser.');}
    if(!response.ok) { let message=`Erreur ${response.status}`; try {message=(await response.json()).error || message;}catch{} throw new Error(message); }
    return binary ? response.blob() : response.json();
  }
  async function calculate(event) {
    event.preventDefault(); if(busy || !form.reportValidity())return;
    const data=collect(), atRevision=revision;
    if(data.mode==='viager'&&data.type==='libre'){
      data.notes=data.notes.split('\n').filter(line=>!line.startsWith('Loyer hors charges inconnu :')&&!line.startsWith('Loyer annoncé ')&&!line.startsWith('Loyer de marché saisi :')).join('\n');
      data.notes+='\nLoyer de marché saisi : '+data.rent_monthly+' €/mois hors charges, hypothèse utilisateur. Location simulée dès l’achat.';
      $('input-notes').value=data.notes;
    }
    busy=true; disableCalculation(true); $('pdf').disabled=true; status('Calcul de la projection et des scénarios…');
    try {
      const result=await request('/api/calculate',data);
      if(revision !== atRevision) {status('La saisie a changé pendant le calcul. Relancez la simulation.');return;}
      render(result); calculatedRevision=revision; $('pdf').disabled=false;
      if(window.ViagerBackend) window.ViagerBackend.register(result.inputs);
      status('Simulation calculée. Le rapport PDF correspond à cette saisie.','success');
    } catch(error) {status(error.message,'error'); $('status').tabIndex=-1; $('status').focus();}
    finally {busy=false; disableCalculation(false);}
  }
  async function analyseURL(event) {
    event.preventDefault(); if(busy || !$('url-form').reportValidity())return;
    const url=$('listing-url').value.trim(), atRevision=revision;
    clearResults(); $('listing-provenance').hidden=true; busy=true; disableCalculation(true);
    status('Recherche de la fiche et calcul des scénarios…');
    try {
      const listing=await request('/api/listing',{url,profile:collect()});
      if(revision !== atRevision){status('Lien modifié pendant le calcul. Cliquez à nouveau sur Analyser.');return;}
      if(listing.requires_rent){
        fill(listing.inputs);
        $('listing-url').value=listing.inputs.source_url||url;
        $('listing-provenance').textContent=listing.provenance;$('listing-provenance').hidden=false;
        $('result-name').textContent='Viager libre · loyer à renseigner';
        status('Annonce importée : renseignez un loyer de marché hors charges, puis cliquez sur « Calculer avec ce loyer ». Aucun rendement locatif calculé avec un loyer inconnu.');
        $('input-rent_monthly').focus();return;
      }
      fill(listing.result.inputs);
      $('listing-url').value=listing.result.inputs.source_url;
      $('listing-provenance').textContent=listing.provenance; $('listing-provenance').hidden=false;
      render(listing.result);calculatedRevision=revision;$('pdf').disabled=false;
      status('Annonce importée. Analyse et scénario défavorable calculés ; hypothèses signalées dans le rapport.','success');
    }catch(error){clearResults();status(error.message,'error');}
    finally{busy=false;disableCalculation(false);}
  }
  function download(blob,name) { const url=URL.createObjectURL(blob); const link=el('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000); }
  function safeName(name) {return String(name || 'simulation').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-zA-Z0-9_-]+/g,'-').replace(/^-|-$/g,'').slice(0,70) || 'simulation';}
  function clearPDF(){const link=$('pdf-download');if(link){URL.revokeObjectURL(link.href);link.remove();}}
  function offerPDF(blob,name){clearPDF();const link=el('a','Télécharger le PDF prêt');link.id='pdf-download';link.href=URL.createObjectURL(blob);link.download=name;link.className='pdf-download';$('pdf').parentElement.append(link);link.click();}
  async function pdf() {
    if(busy || calculatedRevision !== revision || !currentResult)return;
    const atRevision=revision,data=currentResult.inputs; busy=true; $('pdf').disabled=true; status('Préparation du rapport PDF local…');
    try {const blob=await request('/api/pdf',data,true); if(revision !== atRevision){status('Saisie modifiée : recalculez avant de télécharger le rapport.');return;} offerPDF(blob,`${safeName(data.name)}-rapport.pdf`);status('Rapport PDF prêt pour la saisie calculée. Le lien permet de le télécharger à nouveau.','success');}
    catch(error){status(error.message,'error');}
    finally{busy=false;$('pdf').disabled=calculatedRevision !== revision;}
  }
  async function init() {
    buildFields(); form.addEventListener('submit',calculate); form.addEventListener('input',dirty); form.addEventListener('change',dirty);
    $('url-form').addEventListener('submit',analyseURL);
    $('listing-url').addEventListener('input',()=>{dirty();clearResults();$('listing-provenance').hidden=true;status('Lien modifié : cliquez sur Analyser pour préparer le rapport.');});
    document.querySelectorAll('button[data-mode]').forEach(button=>button.addEventListener('click',()=>changeMode(button.dataset.mode)));
    $('pdf').addEventListener('click',pdf);
    $('input-contract_kind').addEventListener('change',contractVisibility);
    $('input-type').addEventListener('change',rentalVisibility);
    $('input-rent_monthly').addEventListener('input',()=>{if(!$('rental-entry').hidden){dirty();clearResults();clearPDF();status('Loyer modifié : cliquez sur « Calculer avec ce loyer » pour actualiser le rapport.');}});
    $('show-glossary').addEventListener('click',()=>{$('glossary-panel').open=true;$('glossary-panel').scrollIntoView({behavior:'auto',block:'start'});});
    $('save').addEventListener('click',()=>{try{localStorage.setItem(STORAGE,JSON.stringify(collect()));status('Saisie enregistrée uniquement sur ce navigateur.','success');}catch{status('Le navigateur refuse l’enregistrement local. Vous pouvez exporter la saisie.','error');}});
    $('export').addEventListener('click',()=>{const data=collect();download(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),`${safeName(data.name)}-saisie.json`);status('Saisie exportée en fichier JSON local.');});
    $('import').addEventListener('click',()=>$('import-file').click());
    if($('import-top'))$('import-top').addEventListener('click',()=>$('import-file').click());
    $('import-file').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>1000000)throw new Error('Le fichier JSON est trop volumineux.');const data=JSON.parse(await file.text());if(!data || Array.isArray(data) || typeof data !== 'object' || !['viager','portage'].includes(data.mode))throw new Error('Fichier de saisie invalide : mode viager ou portage attendu.');fill(data,'Saisie chargée. Vérifiez les champs puis calculez.');if(window.ViagerBackend)window.ViagerBackend.register(data);if(data.source_url)$('listing-url').value=data.source_url;}catch(error){status(error.message,'error');}finally{event.target.value='';}});
    try {
      if(window.ViagerBackend) bootstrap=await window.ViagerBackend.bootstrap();
      else {const response=await fetch('/api/bootstrap');if(!response.ok)throw new Error('Impossible de charger les hypothèses du serveur local.');bootstrap=await response.json();}
      disableCalculation(false);
      $('fiscal-year').textContent=`Fiscalité ${bootstrap.fiscal_year ?? 'à confirmer'}`;
      (bootstrap.glossary || []).forEach(entry=>{const item=el('section',null,'glossary-item');item.append(el('h3',`${entry.term} · ${entry.name}`),el('p',entry.definition),el('p',entry.reading,'muted'));$('glossary').append(item);});
      (bootstrap.examples || []).forEach(example=>{const button=el('button',example.label || example.name);button.type='button';button.addEventListener('click',()=>fill(example.data,`Exemple « ${example.label || example.name} » chargé. Les résultats précédents ont été effacés.`));$('examples').append(button);});
      let saved;try{const raw=localStorage.getItem(STORAGE);if(raw)saved=JSON.parse(raw);}catch{}
      fill(saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : bootstrap.defaults,'Collez l’URL d’une annonce pour commencer. Les réglages restent accessibles dans « Affiner l’analyse ».');
      if(saved && window.ViagerBackend)window.ViagerBackend.register(saved);
      if(!window.ViagerBackend){
        const incoming=new URLSearchParams(location.search).get('annonce');
        const encoded=new URLSearchParams(location.hash.slice(1)).get('profil');
        if(encoded){
          history.replaceState(null,'',location.pathname+location.search);
          try{
            const profile=JSON.parse(encoded),values=collect();
            for(const key of ['tax_method','taxable_income','tmi','parts','parts_base','quotient_cap','situation','other_rent','other_rent_charges','ifi_assets','amortization'])if(profile&&key in profile)values[key]=profile[key];
            fill(values);
          }catch{status('Profil transmis invalide : paramètres locaux conservés.');}
        }
        if(incoming){$('listing-url').value=incoming;await analyseURL({preventDefault(){}});}
      }
    } catch(error){status(error.message,'error');disableCalculation(true);$('save').disabled=true;$('export').disabled=true;$('import').disabled=true;}
  }
  init();
})();
