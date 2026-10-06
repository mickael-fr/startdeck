'use strict';
(() => {
  let worker, sequence=0;
  const pending=new Map();
  const importedCases=new Map();
  const canonical=value=>{
    const url=new URL(value);
    if(url.protocol!=='https:' || url.username || url.password)throw new Error('Une URL HTTPS sans identifiants est requise.');
    if(url.hostname==='costes-viager.com')url.hostname='www.costes-viager.com';
    url.search='';url.hash='';url.pathname=url.pathname.replace(/\/$/,'');return url.href;
  };
  function run(type, data) {
    if(!worker){
      worker=new Worker(new URL('./worker.js?v=20261006-url1',document.baseURI),{type:'module'});
      worker.onmessage=event=>{
        const message=event.data;
        if(message.progress){document.getElementById('status').textContent=message.progress;return;}
        const item=pending.get(message.id);if(!item)return;pending.delete(message.id);
        if(message.error)item.reject(new Error(message.error));else item.resolve(message.result);
      };
      worker.onerror=event=>{for(const item of pending.values())item.reject(new Error('Le moteur navigateur n’a pas pu démarrer : '+(event.message||'chargement impossible')+'. Vérifiez votre connexion et réessayez.'));pending.clear();worker.terminate();worker=null;};
    }
    return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});worker.postMessage({id,type,data});});
  }
  window.ViagerBackend={
    async bootstrap(){const response=await fetch('./bootstrap.json?v=20261006-url1',{cache:'no-store'});if(!response.ok)throw new Error('Configuration indisponible.');return response.json();},
    register(data){if(data.source_url){try{importedCases.set(canonical(data.source_url),structuredClone(data));}catch{}}},
    async request(path,data,binary){
      if(path==='/api/listing'){
        const url=canonical(data.url);
        const target=new URL('http://127.0.0.1:8768/');target.searchParams.set('annonce',url);
        const profile={};
        for(const key of ['tax_method','taxable_income','tmi','parts','parts_base','quotient_cap','situation','other_rent','other_rent_charges','ifi_assets','amortization'])if(data.profile&&key in data.profile)profile[key]=data.profile[key];
        // Fragment is never transmitted to an HTTP server; local UI clears it.
        target.hash='profil='+encodeURIComponent(JSON.stringify(profile));
        document.getElementById('status').textContent='Ouverture de l’analyse sur ce PC…';
        location.assign(target.href);
        return new Promise(()=>{}); // Page navigation replaces this pending UI.
      }
      const result=await run(path==='/api/pdf'?'pdf':'calculate',data);
      return binary?new Blob([result],{type:'application/pdf'}):result;
    }
  };
})();
