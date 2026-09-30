(function(root){
 'use strict';
 function createClient(config,transport=fetch,storage=null){
  const key='cost-killer.session.'+new URL(config.url).hostname;
  let session=null,refreshing=null,epoch=0;
  function saved(){try{return JSON.parse(storage?.getItem(key)||'null')}catch{return null}}
  function clear(){epoch++;session=null;try{storage?.removeItem(key)}catch{}}
  function keep(s){if(!s?.access_token||!s.user?.id)throw Error('Connexion impossible.');session={access_token:s.access_token,refresh_token:s.refresh_token,expires_at:s.expires_at||Math.floor(Date.now()/1000)+(s.expires_in??3600),user:{id:s.user.id,email:s.user.email,user_metadata:s.user.user_metadata}};try{storage?.setItem(key,JSON.stringify(session))}catch{}return session.user;}
  async function send(path,body,token,method){
   const headers={apikey:config.key,'Content-Type':'application/json'};
   if(token)headers.Authorization='Bearer '+token;
   if(path.includes('/rest/'))headers.Prefer='resolution=merge-duplicates,return=representation';
   let r;try{r=await transport(config.url+path,{method:method||(body?'POST':'GET'),headers,cache:'no-store',body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(20000)})}catch{throw Error('Connexion réseau indisponible. Réessaie sans te déconnecter.');}
   const result=await r.json().catch(()=>null);
   if(!r.ok){const e=Error(r.status===429?'Trop de tentatives. Patiente quelques minutes.':r.status===401?'Connexion expirée. Saisis ton code personnel.':path.includes('grant_type=password')?'Adresse ou code incorrect.':path==='/auth/v1/user'?'Code refusé. Essaie un code plus long ou reconnecte-toi.':'Demande refusée. Réessaie ou reconnecte-toi.');e.status=r.status;throw e;}return result;
  }
  async function renew(){
   if(refreshing)return refreshing;
   const generation=epoch;
   const run=async()=>{const latest=saved();if(latest?.refresh_token&&latest.refresh_token!==session?.refresh_token)session=latest;
    if(!session?.refresh_token){clear();throw Error('Connexion nécessaire.');}
    try{const s=await send('/auth/v1/token?grant_type=refresh_token',{refresh_token:session.refresh_token});if(epoch!==generation)throw Error('Session fermée.');return keep(s)}catch(e){if(e.status===400||e.status===401||e.status===403)clear();throw e;}
   };
   refreshing=(typeof navigator!=='undefined'&&navigator.locks?navigator.locks.request(key,run):run()).finally(()=>{refreshing=null});return refreshing;
  }
  async function request(path,body,authenticated=false,method){
   if(authenticated&&!session)throw Error('Connexion nécessaire.');
   if(authenticated&&session.expires_at<Date.now()/1000+30)await renew();
   try{return await send(path,body,authenticated?session.access_token:null,method)}catch(e){
    if(authenticated&&e.status===401){if(session?.refresh_token){await renew();try{return await send(path,body,session.access_token,method)}catch(second){if(second.status===401)clear();throw second}}clear();}throw e;
   }
  }
  return {
   user:()=>session?.user||null,
   async signIn(email,password){clear();return keep(await send('/auth/v1/token?grant_type=password',{email,password}));},
   async restore(){const s=saved();if(!s?.refresh_token)return null;session=s;try{return await renew()}catch(e){session=null;throw e;}},
   requestCode:(email,redirect)=>send('/auth/v1/otp?redirect_to='+encodeURIComponent(redirect),{email,create_user:false}),
   async acceptLink(hash){clear();const params=new URLSearchParams(hash.replace(/^#/,'')),token=params.get('access_token');if(!token)throw Error('Lien incomplet.');const user=await send('/auth/v1/user',null,token);return keep({access_token:token,refresh_token:params.get('refresh_token'),expires_in:Number(params.get('expires_in'))||3600,user});},
   async verify(email,token){clear();return keep(await send('/auth/v1/verify',{email,token,type:'email'}));},
   async setCode(password){const user=await request('/auth/v1/user',{password,data:{personal_code:true}},true,'PUT');return keep({...session,user});},
   read:()=>request('/rest/v1/finance_snapshots?select=snapshot,updated_at',null,true),
   sync:snapshot=>request('/rest/v1/finance_snapshots?on_conflict=owner_id',{owner_id:session?.user?.id,snapshot,updated_at:new Date().toISOString()},true),
   async logout(){const token=session?.access_token;clear();if(token)try{await send('/auth/v1/logout?scope=local',null,token,'POST')}catch{}},
   forget(){clear();}
  };
 }
 if(typeof module!=='undefined')module.exports={createClient};else root.FinanceClient={createClient};
})(typeof window==='undefined'?{}:window);
