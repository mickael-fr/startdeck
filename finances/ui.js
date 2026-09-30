'use strict';
const cloud=FinanceClient.createClient(FINANCE_CLOUD);
const isLocal=['localhost','127.0.0.1'].includes(location.hostname);
const status=s=>{$('cloud-status').textContent=s};
function clearView(){data=null;$('overview').hidden=true;$('mobile-nav').hidden=true;for(const id of ['operations','checks','monthly','categories','recurrences','alerts','merchants'])$(id).replaceChildren();}
function loggedOut(){clearView();$('session-tools').hidden=true;$('email-form').hidden=false;$('code-form').hidden=true;$('code').value='';}
function showSnapshot(record){
 if(!record?.snapshot){clearView();status('Aucune donnée synchronisée. Ouvre cette page depuis l’application sur le PC pour effectuer la première synchronisation.');return;}
 data=record.snapshot; const keys=Object.keys(data.monthly); const previous=$('month').value;
 $('month').innerHTML='<option value="">Tout l’historique</option>'+keys.map(k=>`<option value="${esc(k)}">${month(k)}</option>`).join('');
 $('month').value=keys.includes(previous)?previous:keys.at(-2)||'';
 $('catfilter').innerHTML='<option value="">Toutes les catégories</option>'+data.category_options.map(c=>`<option>${esc(c)}</option>`).join('');
 render();$('overview').hidden=false;$('mobile-nav').hidden=false;
 $('cloud-freshness').textContent='Synchronisation : '+new Date(record.updated_at).toLocaleString('fr-FR')+' · dernier relevé : '+date(data.last_date);
 status('Données chargées. Les montants correspondent aux relevés importés, pas au solde bancaire en temps réel.');
}
async function refresh(){clearView();showSnapshot((await cloud.read())[0]);}
async function action(button,fn){button.disabled=true;try{await fn()}catch(e){status(e.message);if(!cloud.user())loggedOut();}finally{button.disabled=false;}}
$('email-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{await cloud.requestCode($('email').value.trim(),location.origin+location.pathname);status('Lien demandé. Ouvre le message Supabase sur cet appareil et clique sur « Sign in ».');})};
$('code-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{await cloud.verify($('email').value.trim(),$('code').value.trim());$('code').value='';$('email-form').hidden=true;$('code-form').hidden=true;$('session-tools').hidden=false;$('sync-cloud').hidden=!isLocal;await refresh();})};
$('refresh-cloud').onclick=e=>action(e.target,refresh);
$('sync-cloud').onclick=e=>action(e.target,async()=>{
 if(!isLocal)throw Error('Synchronisation disponible uniquement depuis le PC.');
 status('Préparation des dernières données du PC…');
 const r=await fetch('/api/cloud-export',{cache:'no-store'});if(!r.ok)throw Error('Lecture du PC impossible.');
 const snapshot=await r.json();if(!snapshot.statements?.length)throw Error('Aucun relevé à synchroniser.');
 await cloud.sync(snapshot);await refresh();status('Synchronisation réussie. Tu peux consulter ces données sur ton iPhone.');
});
$('logout-cloud').onclick=()=>{cloud.logout();loggedOut();$('cloud-freshness').textContent='';status('Déconnecté.');};
$('month').onchange=()=>data&&render();$('search').oninput=()=>data&&renderOps();$('catfilter').onchange=()=>data&&renderOps();
// Aucun jeton, PDF ou relevé n'est écrit dans localStorage, IndexedDB ou Cache Storage.
addEventListener('pagehide',()=>{cloud.logout();loggedOut();});
addEventListener('pageshow',e=>{if(e.persisted)loggedOut();});
if(location.hash.includes('access_token=')){
 const authHash=location.hash;history.replaceState(null,'',location.pathname+location.search);
 cloud.acceptLink(authHash).then(async()=>{
  $('email-form').hidden=true;$('session-tools').hidden=false;$('sync-cloud').hidden=!isLocal;
  await refresh();
 }).catch(e=>{loggedOut();status(e.message);});
}
