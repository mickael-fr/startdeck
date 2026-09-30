'use strict';
let authStorage=null;try{authStorage=localStorage}catch{}
const cloud=FinanceClient.createClient(FINANCE_CLOUD,fetch,authStorage);
const isLocal=['localhost','127.0.0.1'].includes(location.hostname);
const status=s=>{$('cloud-status').textContent=s};
function clearView(){data=null;$('overview').hidden=true;$('mobile-nav').hidden=true;for(const id of ['operations','checks','monthly','categories','recurrences','alerts','merchants','game-chart','game-quests','rank-path'])$(id).replaceChildren();}
function loggedOut(){clearView();$('session-tools').hidden=true;$('setup-form').hidden=true;$('email-form').hidden=false;$('recover-panel').hidden=false;$('login-help').hidden=false;$('password').value='';$('new-code').value='';$('confirm-code').value='';$('cloud-account').textContent='';$('cloud-freshness').textContent='';}
function loggedIn(){ $('email-form').hidden=true;$('recover-panel').hidden=true;$('login-help').hidden=true;$('session-tools').hidden=false;$('sync-cloud').hidden=!isLocal;$('cloud-account').textContent='Compte : '+(cloud.user()?.email||'connecté');}
function showSnapshot(record){
 if(!record?.snapshot){clearView();status('Aucune donnée synchronisée pour ce compte. Sur le PC, ouvre « Synchroniser vers mon iPhone » et connecte-toi avec la même adresse. Les graphiques apparaîtront après cet envoi.');return;}
 data=record.snapshot;const keys=Object.keys(data.monthly),previous=$('month').value;
 $('month').innerHTML='<option value="">Tout l’historique</option>'+keys.map(k=>`<option value="${esc(k)}">${month(k)}${k===keys[0]||k===keys.at(-1)?' · partiel':''}</option>`).join('');
 $('month').value=keys.includes(previous)?previous:keys.at(-2)||'';
 $('catfilter').innerHTML='<option value="">Toutes les catégories</option>'+data.category_options.map(c=>`<option>${esc(c)}</option>`).join('');
 render();$('overview').hidden=false;$('mobile-nav').hidden=false;
 $('cloud-freshness').textContent='Synchronisation : '+new Date(record.updated_at).toLocaleString('fr-FR')+' · dernier relevé : '+date(data.last_date);
 status('Données à jour avec la dernière synchronisation.');
}
async function refresh(){clearView();showSnapshot((await cloud.read())[0]);}
async function syncPC(){if(!isLocal)throw Error('Synchronisation disponible uniquement depuis le PC.');status('Synchronisation des dernières données du PC…');const r=await fetch('/api/cloud-export',{cache:'no-store'});if(!r.ok)throw Error('Lecture du PC impossible.');const snapshot=await r.json();if(!snapshot.statements?.length)throw Error('Aucun relevé à synchroniser.');await cloud.sync(snapshot);await refresh();status('Synchronisation réussie. Les courbes et les comptes sont disponibles sur ton iPhone.');}
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
$('month').onchange=()=>data&&render();$('search').oninput=()=>data&&renderOps();$('catfilter').onchange=()=>data&&renderOps();
// Session uniquement : aucun PDF, code personnel ou relevé n'est stocké hors connexion.
addEventListener('storage',e=>{if(e.key?.startsWith('cost-killer.session.')&&e.newValue===null){cloud.forget();loggedOut();}});
addEventListener('pageshow',e=>{if(e.persisted)action(null,async()=>{clearView();if(await cloud.restore())await opened();else loggedOut();});});
action(null,async()=>{if(location.hash.includes('access_token=')){const authHash=location.hash;history.replaceState(null,'',location.pathname+location.search);await cloud.acceptLink(authHash);loggedIn();$('setup-form').hidden=false;status('Choisis ton code personnel ci-dessous.');}else if(await cloud.restore()){await opened();}else loggedOut();});
