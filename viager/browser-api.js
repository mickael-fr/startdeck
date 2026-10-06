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
      worker=new Worker(new URL('./worker.js',document.baseURI),{type:'module'});
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
    async bootstrap(){const response=await fetch('./bootstrap.json');if(!response.ok)throw new Error('Configuration indisponible.');return response.json();},
    register(data){if(data.source_url){try{importedCases.set(canonical(data.source_url),structuredClone(data));}catch{}}},
    async request(path,data,binary){
      if(path==='/api/listing'){
        const inputs=importedCases.get(canonical(data.url));
        if(!inputs)throw new Error('Cette URL n’a pas de fiche sur cet appareil. La lecture automatique de nouvelles annonces n’est pas connectée. Chargez une fiche exportée depuis votre outil local, ou renseignez les données dans « Affiner l’analyse ». Aucun montant n’est inventé.');
        return {result:await run('calculate',inputs),live:false,provenance:'Fiche importée sur cet appareil ; annonce non relue au moment du calcul.'};
      }
      const result=await run(path==='/api/pdf'?'pdf':'calculate',data);
      return binary?new Blob([result],{type:'application/pdf'}):result;
    }
  };
})();
