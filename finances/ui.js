'use strict';
let authStorage=null;try{authStorage=localStorage}catch{}
const cloud=FinanceClient.createClient(FINANCE_CLOUD,fetch,authStorage);
const isLocal=['localhost','127.0.0.1'].includes(location.hostname);
let cloudRecord=null,writing=false;
const status=s=>{$('cloud-status').textContent=s};
function clearView(){data=null;$('overview').hidden=true;$('mobile-nav').hidden=true;for(const id of ['operations','checks','monthly','categories','recurrences','alerts','merchants','game-chart','game-quests','rank-path'])$(id).replaceChildren();}
function loggedOut(){clearView();$('session-tools').hidden=true;$('setup-form').hidden=true;$('email-form').hidden=false;$('recover-panel').hidden=false;$('login-help').hidden=false;$('password').value='';$('new-code').value='';$('confirm-code').value='';$('cloud-account').textContent='';$('cloud-freshness').textContent='';}
function loggedIn(){ $('email-form').hidden=true;$('recover-panel').hidden=true;$('login-help').hidden=true;$('session-tools').hidden=false;$('sync-cloud').hidden=!isLocal;$('cloud-account').textContent='Compte : '+(cloud.user()?.email||'connecté');}
function showSnapshot(record){
 if(!cloud.user()){clearView();return;}
 cloudRecord=record||null;
 if(!record?.snapshot){clearView();status('Aucune donnée synchronisée pour ce compte. Sur le PC, ouvre « Synchroniser vers mon iPhone » et connecte-toi avec la même adresse. Les graphiques apparaîtront après cet envoi.');return;}
 data=record.snapshot;const keys=Object.keys(data.monthly),previous=$('month').value;
 $('month').innerHTML='<option value="">Tout l’historique</option>'+keys.map(k=>`<option value="${esc(k)}">${month(k)}${k===keys[0]||k===keys.at(-1)?' · partiel':''}</option>`).join('');
 $('month').value=keys.includes(previous)?previous:keys.at(-2)||'';
 $('catfilter').innerHTML='<option value="">Toutes les catégories</option>'+data.category_options.map(c=>`<option>${esc(c)}</option>`).join('');
 render();$('overview').hidden=false;$('mobile-nav').hidden=false;
 $('cloud-freshness').textContent='Synchronisation : '+new Date(record.updated_at).toLocaleString('fr-FR')+' · dernier relevé : '+date(data.last_date);
 status(record.snapshot.pending_edits?.length?'Corrections enregistrées · reprise des règles et recalcul des alertes à la prochaine synchronisation du PC.':'Données à jour avec la dernière synchronisation.');
}
async function refresh(){clearView();showSnapshot((await cloud.read())[0]);}
async function syncPC(){
 if(!isLocal)throw Error('Synchronisation disponible uniquement depuis le PC.');
 if(writing)throw Error('Enregistrement en cours.');writing=true;
 try{status('Reprise des corrections puis synchronisation du PC…');
 const existing=(await cloud.read())[0];
 const applied=await fetch('/api/cloud-edits',{method:'POST',headers:{'Content-Type':'application/json','X-Finance-Token':LOCAL_TOKEN},body:JSON.stringify({edits:existing?.snapshot?.pending_edits||[]})});
 const result=await applied.json();if(!applied.ok)throw Error(result.error||'Reprise des corrections impossible.');
 const r=await fetch('/api/cloud-export',{cache:'no-store'});if(!r.ok)throw Error('Lecture du PC impossible.');const snapshot=await r.json();if(!snapshot.statements?.length)throw Error('Aucun relevé à synchroniser.');
 await cloud.save(snapshot,existing?.updated_at);await refresh();status('Synchronisation réussie : corrections reprises et règles apprises sur le PC.');
 }finally{writing=false;}
}
function updateMonthly(snapshot){
 const monthly={},categories={},merchants={};
 for(const op of snapshot.operations){const m=monthly[op.date.slice(0,7)]??={expense:0,income:0,transfer:0,excluded:0,refund:0,categories:{}};
 if(op.kind==='expense'&&op.amount<0){const amount=-op.amount;m.expense+=amount;m.categories[op.category]=(m.categories[op.category]||0)+amount;categories[op.category]=(categories[op.category]||0)+amount;merchants[op.merchant]=(merchants[op.merchant]||0)+amount;}
 else if(['income','transfer','excluded','refund'].includes(op.kind))m[op.kind]+=op.amount;}
 snapshot.monthly=Object.fromEntries(Object.entries(monthly).sort());snapshot.categories=categories;snapshot.merchants=Object.fromEntries(Object.entries(merchants).sort((a,b)=>b[1]-a[1]).slice(0,10));
}
$('operations').addEventListener('change',async e=>{
 const select=e.target;if(!select.dataset.id)return;
 if(writing){renderOps();return;}writing=true;
 $('operations').querySelectorAll('select,button').forEach(el=>el.disabled=true);
 try{
 const latest=(await cloud.read())[0];if(!latest?.snapshot)throw Error('Aucune donnée synchronisée.');
 const current=data.operations.find(o=>o.id===Number(select.dataset.id)),snapshot=structuredClone(latest.snapshot),op=snapshot.operations.find(o=>o.id===current?.id);
 if(!op||['date','amount','label','category'].some(k=>op[k]!==current[k]))throw Error('Cette opération a changé sur un autre appareil. Actualise avant de la reclasser.');
 const category=select.value;if(!Object.hasOwn(CATEGORY_KINDS,category))throw Error('Catégorie inconnue.');
 const peers=category==='À classer'?[]:categoryPeers(snapshot,op),targets=[...(op.category!==category?[op]:[]),...peers];
 for(const target of targets){
 const edit={event_id:crypto.randomUUID(),id:target.id,date:target.date,amount:target.amount,label:target.label,before:target.category,category};
 snapshot.pending_edits=[...(snapshot.pending_edits||[]),edit];target.reviewed_at=null;target.category=category;target.category_manual=true;target.kind=CATEGORY_KINDS[category]==='expense'&&target.amount>0?'refund':CATEGORY_KINDS[category];
 }
 if(targets.length){updateMonthly(snapshot);await cloud.save(snapshot,latest.updated_at);}
 showSnapshot((await cloud.read())[0]);notice('Catégorie enregistrée ; '+peers.length+' autre(s) opération(s) similaire(s) classée(s). La règle sera reprise sur le PC à la prochaine synchronisation.');
 }catch(err){notice(err.message);renderOps();}finally{writing=false;}
});
$('operations').addEventListener('click',async e=>{
 const button=e.target.closest('[data-review]');if(!button||writing||!data)return;
 const current=structuredClone(data.operations.find(o=>o.id===Number(button.dataset.review)));
 writing=true;$('operations').querySelectorAll('select,button').forEach(el=>el.disabled=true);
 try{
 const latest=(await cloud.read())[0],snapshot=structuredClone(latest?.snapshot),op=snapshot?.operations.find(o=>o.id===current.id);
 if(!op||['date','amount','label','category'].some(k=>op[k]!==current[k])||(op.reviewed_at||null)!==(current.reviewed_at||null))throw Error('Cette opération a changé sur un autre appareil. Actualise avant de la valider.');
 if(op.category==='À classer')throw Error('Choisis une catégorie avant de valider.');
 const reviewed_at=op.reviewed_at?null:new Date().toISOString();
 snapshot.pending_edits=[...(snapshot.pending_edits||[]),{event_id:crypto.randomUUID(),type:'review',id:op.id,date:op.date,amount:op.amount,label:op.label,category:op.category,before_reviewed_at:op.reviewed_at||null,reviewed_at}];
 op.reviewed_at=reviewed_at;
 await cloud.save(snapshot,latest.updated_at);showSnapshot((await cloud.read())[0]);
 notice(reviewed_at?'Opération validée et enregistrée.':'Opération remise à vérifier.');
 }catch(err){notice(err.message);renderOps();}finally{writing=false;}
});
async function opened(){loggedIn();await (isLocal?syncPC():refresh());}
async function action(button,fn){if(button)button.disabled=true;try{await fn()}catch(e){status(e.message);if(!cloud.user())loggedOut();}finally{if(button)button.disabled=false;}}
$('email-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{const code=$('password').value;try{await cloud.signIn($('email').value.trim(),code)}finally{$('password').value=''}await opened();})};
let recoveryUntil=0;try{recoveryUntil=Number(authStorage?.getItem('cost-killer.recovery-until')||0)}catch{}
function recoveryButton(){const seconds=Math.max(0,Math.ceil((recoveryUntil-Date.now())/1000));$('recover-code').disabled=seconds>0;$('recover-code').textContent=seconds?'Nouvel envoi possible dans '+seconds+' s':'Recevoir la validation initiale';}
$('recover-code').onclick=e=>{if(!$('email').reportValidity())return;action(e.target,async()=>{recoveryUntil=Date.now()+60000;try{authStorage?.setItem('cost-killer.recovery-until',String(recoveryUntil))}catch{}await cloud.requestCode($('email').value.trim(),location.origin+location.pathname);status('Validation demandée. Ouvre le dernier lien reçu sur cet appareil, puis choisis ton code.');}).finally(recoveryButton)};
setInterval(recoveryButton,1000);recoveryButton();
$('setup-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{if($('new-code').value!==$('confirm-code').value)throw Error('Les deux codes sont différents.');await cloud.setCode($('new-code').value);$('new-code').value='';$('confirm-code').value='';$('setup-form').hidden=true;await opened();status('Code enregistré. Tu peux maintenant te connecter avec ce code sur tes appareils.');})};
$('change-code').onclick=()=>{$('setup-form').hidden=false;};
$('refresh-cloud').onclick=e=>action(e.target,()=>isLocal?syncPC():refresh());
$('sync-cloud').onclick=e=>action(e.target,syncPC);
$('logout-cloud').onclick=e=>action(e.target,async()=>{const done=cloud.logout();loggedOut();await done;status('Déconnecté de cet appareil.');});
$('reviewfilter').onchange=()=>data&&renderOps();$('month').onchange=()=>data&&render();$('search').oninput=()=>data&&renderOps();$('catfilter').onchange=()=>data&&renderOps();
// Session uniquement : aucun PDF, code personnel ou relevé n'est stocké hors connexion.
addEventListener('storage',e=>{if(e.key?.startsWith('cost-killer.session.')&&e.newValue===null){cloud.forget();loggedOut();}});
addEventListener('pageshow',e=>{if(e.persisted)action(null,async()=>{clearView();if(await cloud.restore())await opened();else loggedOut();});});
action(null,async()=>{if(location.hash.includes('access_token=')){const authHash=location.hash;history.replaceState(null,'',location.pathname+location.search);await cloud.acceptLink(authHash);loggedIn();$('setup-form').hidden=false;status('Choisis ton code personnel ci-dessous.');}else if(await cloud.restore()){await opened();}else loggedOut();});
