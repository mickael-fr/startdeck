(function(root){
 'use strict';
 function createClient(config,transport=fetch){
  let session=null;
  async function request(path,body,authenticated=false,method){
   if(authenticated&&!session)throw Error('Connexion nécessaire.');
   const headers={'apikey':config.key,'Content-Type':'application/json'};
   if(authenticated)headers.Authorization='Bearer '+session.access_token;
   if(path.includes('/rest/'))headers.Prefer='resolution=merge-duplicates,return=representation';
   const r=await transport(config.url+path,{method:method||(body?'POST':'GET'),headers,cache:'no-store',body:body?JSON.stringify(body):undefined});
   const result=await r.json().catch(()=>null);
   if(!r.ok){if(r.status===401)session=null;throw Error(r.status===401?'Connexion expirée. Reconnecte-toi.':r.status===429?'Trop de demandes. Réessaie dans quelques minutes.':'Demande refusée. Vérifie le code reçu et la configuration de l’accès.');}
   return result;
  }
  return {
   user:()=>session?.user||null,
   requestCode:(email,redirect)=>request('/auth/v1/otp?redirect_to='+encodeURIComponent(redirect),{email,create_user:true}),
   async acceptLink(hash){
    session=null;const token=new URLSearchParams(hash.replace(/^#/, '')).get('access_token');
    if(!token)throw Error('Lien de connexion incomplet.');
    const r=await transport(config.url+'/auth/v1/user',{headers:{apikey:config.key,Authorization:'Bearer '+token},cache:'no-store'});
    if(!r.ok)throw Error('Lien expiré. Demande un nouveau lien.');
    const user=await r.json();if(!user?.id)throw Error('Connexion impossible.');
    session={access_token:token,user};return user;
   },
   async verify(email,token){session=null;const s=await request('/auth/v1/verify',{email,token,type:'email'});if(!s?.access_token||!s.user?.id)throw Error('Connexion impossible.');session=s;return s.user;},
   read:()=>request('/rest/v1/finance_snapshots?select=snapshot,updated_at',null,true),
   sync:snapshot=>request('/rest/v1/finance_snapshots?on_conflict=owner_id',{owner_id:session?.user?.id,snapshot,updated_at:new Date().toISOString()},true),
   logout(){session=null;}
  };
 }
 if(typeof module!=='undefined')module.exports={createClient};else root.FinanceClient={createClient};
})(typeof window==='undefined'?{}:window);
