import {loadPyodide} from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';
let runtime, pdfReady=false;
let queue=Promise.resolve();
function progress(text){self.postMessage({progress:text});}
async function initialize(){
  progress('Premier calcul : chargement du moteur dans votre navigateur…');
  const py=await loadPyodide();
  await py.loadPackage(['numpy','pandas','pyyaml','tzdata']);
  const manifest=await (await fetch('./python-files.json?v=20261006-url1',{cache:'no-store'})).json();
  for(const file of manifest){
    const response=await fetch('./python/'+file+'?v=20261006-url1',{cache:'no-store'});if(!response.ok)throw new Error('Fichier du moteur indisponible : '+file);
    const target='/app/'+file, folder=target.slice(0,target.lastIndexOf('/'));py.FS.mkdirTree(folder);
    py.FS.writeFile(target,new Uint8Array(await response.arrayBuffer()));
  }
  await py.runPythonAsync("import sys\nsys.path.insert(0, '/app')\nimport json\nfrom engine import calculate\n");
  progress('Moteur prêt. Calcul de la projection et des scénarios…');
  return py;
}
self.onmessage=event=>{
  queue=queue.then(async()=>{
    const {id,type,data}=event.data;
    try{
      runtime ||= initialize().catch(error=>{runtime=null;throw error;});
      const py=await runtime;
      py.globals.set('input_json',JSON.stringify(data));
      const encoded=await py.runPythonAsync('json.dumps(calculate(json.loads(input_json)), ensure_ascii=False, allow_nan=False)');
      if(type!=='pdf'){self.postMessage({id,result:JSON.parse(encoded)});return;}
      progress('Préparation du PDF sur cet appareil…');
      if(!pdfReady){
        await py.loadPackage('pillow');
        const wheel=await fetch('./vendor/reportlab-5.0.1-py3-none-any.whl');if(!wheel.ok)throw new Error('Bibliothèque PDF indisponible.');
        py.unpackArchive(await wheel.arrayBuffer(),'zip',{extractDir:'/app/packages'});
        await py.runPythonAsync("sys.path.insert(0, '/app/packages')\nfrom pdf_report import build_pdf\n");pdfReady=true;
      }
      py.globals.set('result_json',encoded);
      const proxy=await py.runPythonAsync('build_pdf(json.loads(result_json))');
      const bytes=proxy.toJs();proxy.destroy();
      self.postMessage({id,result:bytes},[bytes.buffer]);
    }catch(error){self.postMessage({id,error:String(error.message||error)});}
  });
};
