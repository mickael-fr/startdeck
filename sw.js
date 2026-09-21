/* StartDeck : réseau en priorité ; dernière page valide en secours hors ligne.
   Le contenu de l'application n'est jamais stocké dans le cache du worker.
   Les changements d'index.html ne nécessitent pas de modifier ce fichier. */
const PREFIX='startdeck:'+self.registration.scope+':';
const CACHE=PREFIX+'v1';
const INDEX=new URL('index.html',self.registration.scope).href;
const ROOT=new URL('./',self.registration.scope).href;
self.addEventListener('install',event=>{
  event.waitUntil((async()=>{
    const response=await fetch(INDEX,{cache:'no-store'});
    if(!response.ok||!response.headers.get('content-type')?.includes('text/html'))throw Error('StartDeck indisponible');
    await (await caches.open(CACHE)).put(INDEX,response);
    await self.skipWaiting();
  })());
});
self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    for(const name of await caches.keys())if(name.startsWith(PREFIX)&&name!==CACHE)await caches.delete(name);
    await self.clients.claim();
  })());
});
self.addEventListener('fetch',event=>{
  const req=event.request,url=new URL(req.url);
  // Ne jamais intercepter les API privées, les cours, la météo ou les autres sites.
  if(req.method!=='GET'||req.mode!=='navigate'||![INDEX,ROOT].includes(url.origin+url.pathname))return;
  event.respondWith((async()=>{
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
    try{
      const response=await fetch(req,{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw Error('Serveur indisponible');
      if(response.headers.get('content-type')?.includes('text/html')){
        const copy=response.clone();event.waitUntil(caches.open(CACHE).then(c=>c.put(INDEX,copy)).catch(()=>{}));
      }
      return response;
    }catch{
      return await (await caches.open(CACHE)).match(INDEX)||new Response('StartDeck est hors connexion. Réessayez une fois connecté.',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}});
    }finally{clearTimeout(timeout)}
  })());
});
