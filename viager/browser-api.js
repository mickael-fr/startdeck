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
        let imported;
        try{
          const response=await fetch('http://127.0.0.1:8768/api/import-listing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url}),signal:AbortSignal.timeout(45000)});
          imported=await response.json();
          if(!response.ok)throw new Error(imported.error||'Lecture de l’annonce impossible.');
        }catch(error){
          if(error instanceof TypeError || error.name==='TimeoutError'){
            const saved=importedCases.get(url);
            if(saved)return {result:await run('calculate',saved),live:false,provenance:'Service local indisponible ; fiche personnelle déjà importée, annonce non relue.'};
            throw new Error('Le service de lecture sur ce PC est inaccessible. Lancez « Ouvrir Viager Studio » sur le PC, puis réessayez. Si le navigateur demande l’accès au réseau local, cet accès est nécessaire pour joindre votre propre service.');
          }
          throw error;
        }
        const inputs=imported.inputs;
        for(const key of ['tax_method','taxable_income','tmi','parts','parts_base','quotient_cap','situation','other_rent','other_rent_charges','ifi_assets','amortization'])if(data.profile&&key in data.profile)inputs[key]=data.profile[key];
        return {result:await run('calculate',inputs),live:imported.live,provenance:imported.provenance};
      }
      const result=await run(path==='/api/pdf'?'pdf':'calculate',data);
      return binary?new Blob([result],{type:'application/pdf'}):result;
    }
  };
})();
