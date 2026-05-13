const $=id=>document.getElementById(id);
const PRESETS=__PRESETS_JSON__;
const TASKS=__TASKS_JSON__;
const CATALOG=__CATALOG_JSON__;

// Goobi metadata types (common)
const GOOBI_TYPES=[
  "CatalogIDDigital","TitleDocMain","Description","PublicationYear",
  "DocLanguage","singleDigCollection","Author","SubjectTopic",
  "PlaceOfPublication","Publisher","Format","Source",
  "Creator","Rights","Technique","MaterialDescription","Dimensions",
  "InventoryNumber","DateCreated","DateIssued","SubjectGeographic",
  "SubjectPerson","SubjectCorporation","Custom",
];

// Minimaldatensatz 1.1 fields (minimaldatensatz.de)
const MDS_FIELDS=[
  {mds:"Identifikator",goobi:"CatalogIDDigital",pflicht:true,note:"Eindeutige ID (UUID, Signatur …)"},
  {mds:"Titel",goobi:"TitleDocMain",pflicht:true,note:"Haupttitel des Objekts"},
  {mds:"Objekttyp",goobi:"DocStruct",pflicht:true,note:"Art des Objekts (Gemälde, Brief …)"},
  {mds:"Aufbewahrungsort",goobi:"PlaceOfPublication",pflicht:true,note:"Institution / Standort"},
  {mds:"Rechtliche Informationen",goobi:"Rights",pflicht:true,note:"Lizenz oder Rechtehinweis"},
  {mds:"Beschreibung",goobi:"Description",pflicht:false,note:"Inhaltliche Beschreibung"},
  {mds:"Datierung",goobi:"DateCreated",pflicht:false,note:"Entstehungsdatum (EDTF-Format empfohlen)"},
  {mds:"Abmessungen/Umfang",goobi:"Dimensions",pflicht:false,note:"Maße oder Seitenumfang"},
  {mds:"Material/Technik",goobi:"MaterialDescription",pflicht:false,note:"Material und Herstellungstechnik"},
  {mds:"Hersteller/Urheber",goobi:"Creator",pflicht:false,note:"Person oder Körperschaft"},
  {mds:"Abbildungsnachweis",goobi:"Source",pflicht:false,note:"Bildquelle oder Fotograf"},
  {mds:"Schlagwörter",goobi:"SubjectTopic",pflicht:false,note:"Thematische Schlagwörter"},
  {mds:"Herstellungsort",goobi:"SubjectGeographic",pflicht:false,note:"Entstehungsort des Objekts"},
  {mds:"Sammlung",goobi:"singleDigCollection",pflicht:false,note:"Sammlung oder Bestand"},
];

let ufiles={},curRep=null,gpuM=[],nerData=[],edtfData=[];
let recordOffset=0,recordLimit=50,recordTotal=0;
let nerStatusFilter='all', nerTypeFilter='all';
let fmMapping={}; // current field mapping state
let latestImageResults=[];
let filteredImageResults=[];
let termsData=[]; // problematic terms dictionary
let termsScanResults=[]; // last scan results
let termsCatFilter='all';
let colSortKey='name',colSortDir=1; // for combined columns table
let _abortCtrl=null;
let _opCancelled=false;

// === MODEL HINTS ===
const MODEL_HINTS={
  'qwen3-coder':{type:'text',hint:'Code-Generierung, Reasoning, allgemeine Text-Aufgaben'},
  'qwen3-vl':{type:'vision',hint:'Bildbeschreibung, OCR, Dokumentenanalyse (Vision-Language)'},
  'internvl3':{type:'vision',hint:'Bilderkennung, Multi-Sprache, visuelle Fragen (Vision)'},
  'internvl':{type:'vision',hint:'Vision-Language Modell'},
  'faster-whisper':{type:'audio',hint:'Spracherkennung / Transkription (Whisper ASR)'},
  'jina-reranker':{type:'rerank',hint:'Reranking von Suchergebnissen (nicht für Textgenerierung)'},
  'granite-embedding':{type:'embed',hint:'Embedding-Generierung für Similarity Search'},
  'deepseek-r1':{type:'text',hint:'Reasoning-Modell, Chain-of-Thought, komplexe Analysen'},
  'gpt-oss':{type:'text',hint:'Grosses Text-Modell, NER, Datierung, Analyse'},
  'qwen3-embedding':{type:'embed',hint:'Kompaktes Embedding-Modell (Mehrsprachig)'},
  'llama':{type:'text',hint:'Allgemeines Text-Modell (Meta)'},
  'mistral':{type:'text',hint:'Schnelles Text-Modell (Mistral AI)'},
  'llava':{type:'vision',hint:'Vision-Language Modell'},
  'phi':{type:'text',hint:'Kompaktes Text-Modell (Microsoft)'},
  'bakllava':{type:'vision',hint:'Vision-Language Modell'},
};
function getModelHint(name){
  const n=name.toLowerCase();
  for(const[k,v]of Object.entries(MODEL_HINTS)){if(n.includes(k))return v;}
  return{type:'unknown',hint:'Modelltyp unbekannt'};
}

// === SECURITY ===
function esc(s){return s==null?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function safeOpt(val,label){return '<option value="'+esc(val)+'">'+esc(label)+'</option>'}
function dl(name,content,type){const b=new Blob([content],{type});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click()}
function encPath(v){return encodeURIComponent(String(v==null?'':v))}

// === NAV (Phase Navigator — 6 non-blocking phases) ===
let currentStep=1;
// Phases 2-5 start as 'no-data' (unlocked once data is loaded); Phase 6 always accessible
let stepStates={1:'active',2:'no-data',3:'no-data',4:'no-data',5:'no-data',6:'pending'};

function goStep(n){
  if(stepStates[n]==='no-data'){return;}
  currentStep=n;
  // Update step indicators
  document.querySelectorAll('.stepper .step').forEach(el=>{
    const s=parseInt(el.dataset.step);
    if(s===n)el.className='step active';
    else if(stepStates[s]==='completed')el.className='step completed';
    else if(stepStates[s]==='no-data')el.className='step no-data';
    else el.className='step';
  });
  // Update connectors
  document.querySelectorAll('.step-conn').forEach((conn,i)=>{
    conn.classList.toggle('done',stepStates[i+1]==='completed');
  });
  // Show panel
  document.querySelectorAll('.step-panel').forEach(p=>{
    p.classList.toggle('active',parseInt(p.dataset.step)===n);
  });
  // Load data for specific phases
  try{
    if(n===2){loadRevSummary();loadWorkPackages();}
    if(n===4){loadAuthorityCandidates();}
    if(n===5){loadDictEntries();loadDictTypes();}
    if(n===6){loadFMCols();}
  }catch(e){console.error('[goStep:'+n+']',e)}
}

function unlockStep(n){
  if(stepStates[n]==='no-data')stepStates[n]='pending';
  updateStepperUI();
}

/** Unlock all phases (2-5) once data is loaded. Phase 6 is always accessible. */
function unlockAllPhases(){
  for(let i=2;i<=5;i++){if(stepStates[i]==='no-data')stepStates[i]='pending';}
  updateStepperUI();
}

function completeStep(n){
  stepStates[n]='completed';
  // Suggest next phase
  if(n<6)unlockStep(n+1);
  updateStepperUI();
  // Notify backend
  fetch('/api/pipeline/step/'+n+'/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});
  // Auto-advance
  if(n<6)goStep(n+1);
}

function updateStepperUI(){
  document.querySelectorAll('.stepper .step').forEach(el=>{
    const s=parseInt(el.dataset.step);
    const state=stepStates[s];
    el.className='step'+(s===currentStep?' active':'')+(state==='completed'?' completed':'')+(state==='no-data'?' no-data':'');
  });
  document.querySelectorAll('.step-conn').forEach((conn,i)=>{
    conn.classList.toggle('done',stepStates[i+1]==='completed');
  });
}

// Settings overlay
function openSettings(){
  $('settings-overlay').classList.add('a');
  loadGPUConfig();chkGPU();
}
function closeSettings(){$('settings-overlay').classList.remove('a')}

// Boolean analysis params
function addBoolParam(){
  const inp=$('new-bool-param');if(!inp)return;
  const q=inp.value.trim();if(!q)return;
  const container=$('bool-params');
  const div=document.createElement('div');div.className='bool-param';
  div.innerHTML='<input type="text" value="'+esc(q)+'" readonly><button class="btn sm s" onclick="removeBoolParam(this)" style="margin-top:0">&#10005;</button>';
  container.appendChild(div);
  inp.value='';
}
function removeBoolParam(btn){btn.parentElement.remove();}

function getBoolParams(){
  return [...document.querySelectorAll('#bool-params .bool-param input')].map(i=>i.value).filter(Boolean);
}

// Pilot run for images (2% test)
async function runPilotImages(){
  if(!uploadedImages.length){alert('Erst Bilder hochladen.');return}
  const ids=uploadedImages.slice(0,Math.max(1,Math.ceil(uploadedImages.length*0.02))).map(i=>i.id);
  const mod=($('img-model-sidebar')&&$('img-model-sidebar').value)||($('img-model')&&$('img-model').value)||'';
  const task=($('img-task-sidebar')&&$('img-task-sidebar').value)||($('img-task')&&$('img-task').value)||'image_description';
  const boolParams=getBoolParams();
  sp('Bild-Testlauf …',ids.length+' Bild(er)');
  const body={image_ids:ids,model:mod,prompt_task:task,boolean_params:boolParams};
  try{
    await fetchSSE('/api/images/analyze/stream',body,
      evt=>{spUp(evt.current,evt.total,esc(evt.filename||''));},
      result=>{renderImgResults(result.results||[]);},
      msg=>{const el=$('img-full-status');if(el)el.textContent='Fehler: '+msg;}
    );
  }catch(e){if(e.name!=='AbortError')alert(e.message);}finally{hp();}
}

// Quality gateway: mark test as reviewed (Phase 3 sub-tab)
function markTestReviewed(){
  completeStep(3);
}

// GeoNames lookup
async function runGeoNamesLookup(){
  sp('GeoNames-Suche …','api.geonames.org');
  try{
    const r=await(await fetch('/api/geonames/batch',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({limit:20})})).json();
    if(r.error){alert('GeoNames-Fehler: '+r.error);hp();return;}
    renderGeoNamesResults(r);
    updWS();
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}

function renderGeoNamesResults(r){
  if($('geonames-r'))$('geonames-r').style.display='block';
  const results=r.results||[];
  $('geonames-body').innerHTML=results.map(gr=>{
    const tm=gr.top_match;
    let coords='';
    if(tm&&(tm.lat||tm.lng)){
      const lat=Number(tm.lat).toFixed(4),lng=Number(tm.lng).toFixed(4);
      coords='<a href="https://www.openstreetmap.org/?mlat='+lat+'&mlon='+lng+'#map=10/'+lat+'/'+lng+'" target="_blank" rel="noopener" style="font-size:.68rem">'+lat+', '+lng+'</a>';
    }
    return '<tr>'+
      '<td style="font-weight:600">'+esc(gr.text||'')+'</td>'+
      '<td><span class="etype etype-'+esc(gr.type||'LOC')+'">'+esc(gr.type||'')+'</span></td>'+
      '<td>'+(tm?'<a class="gnd-match" href="'+esc(tm.uri||'')+'" target="_blank" rel="noopener">'+esc(tm.geonames_id)+'</a>':'<span class="gnd-none">—</span>')+'</td>'+
      '<td>'+(tm?esc(tm.name||''):'')+'</td>'+
      '<td style="font-size:.68rem">'+(tm?esc(tm.country||''):'')+'</td>'+
      '<td>'+coords+'</td>'+
    '</tr>';
  }).join('');
}

// Dictionary JSON rendering
async function renderDictionaryJSON(){
  sp('JSON-Dictionary generieren …','');
  try{
    const t=($('dict-type-filter')&&$('dict-type-filter').value)||'';
    const r=await fetch('/api/dictionary/export-target'+(t?'?entity_type='+encodeURIComponent(t):''));
    const text=await r.text();
    $('dict-json-preview').style.display='block';
    $('dict-json-output').value=text;
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}

// Apply dictionary to metadata
async function applyDictionaryToMetadata(){
  const ds=($('enrich-ds')&&$('enrich-ds').value)||'';
  if(!ds){alert('Datensatz wählen');return;}
  sp('Wörterbuch auf Metadaten anwenden …','');
  try{
    const r=await(await fetch('/api/dictionary/apply',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({dataset:ds})})).json();
    const st=$('enrich-status');
    if(r.error){if(st)st.textContent='Fehler: '+r.error;hp();return;}
    if(st)st.textContent='Angereichert: '+(r.enriched||0)+' Felder in '+(r.records||0)+' Datensätzen.';
  }catch(e){$('enrich-status').textContent='Fehler: '+e.message;}finally{hp();}
}

// Load pipeline step states from backend
async function loadStepStates(){
  try{
    const r=await(await fetch('/api/pipeline/steps')).json();
    const steps=r.steps||[];
    steps.forEach(s=>{
      if(s.completed)stepStates[s.number]='completed';
      else if(s.active||s.number===1)stepStates[s.number]='active';
      // Unlock if previous is completed
      if(s.number>1&&stepStates[s.number-1]==='completed'&&stepStates[s.number]==='no-data')stepStates[s.number]='pending';
    });
    updateStepperUI();
  }catch(e){
    // Default: phase 1 active, 2-5 no-data, 6 accessible
    stepStates={1:'active',2:'no-data',3:'no-data',4:'no-data',5:'no-data',6:'pending'};
  }
}

function bindNav(){/* replaced by stepper */}
// === UPLOAD ===
function bindUpload(){
  const uz=$('uz'),fi=$('fi');
  if(!uz||!fi)return;
  fi.onchange=e=>hf(e.target.files,fi);
  uz.ondragover=e=>{e.preventDefault();uz.classList.add('dr')};
  uz.ondragleave=()=>uz.classList.remove('dr');
  uz.ondrop=e=>{e.preventDefault();uz.classList.remove('dr');hf(e.dataTransfer.files,fi)};
}
function _splitExt(name){const i=name.lastIndexOf('.');if(i<=0)return[name,''];return[name.slice(0,i),name.slice(i)]}
function _uniqueUploadName(name){
  const existing=new Set(Object.values(ufiles).map(x=>x.uploadName));
  if(!existing.has(name))return name;
  const parts=_splitExt(name),base=parts[0],ext=parts[1];
  let n=2,cand='';
  do{cand=base+' ('+n+')'+ext;n++;}while(existing.has(cand));
  return cand;
}
function hf(files,fiEl){
  for(const f of files||[]){
    const uploadName=_uniqueUploadName(f.name);
    const id=uploadName+'__'+f.size+'__'+f.lastModified;
    ufiles[id]={file:f,displayName:f.name,uploadName,size:f.size};
  }
  if(fiEl)fiEl.value='';
  rfl();
}
function bindTabs(el){
  const ps=[];let s=el.nextElementSibling;
  while(s&&s.classList.contains('tp')){ps.push(s);s=s.nextElementSibling}
  el.onclick=e=>{
    const tab=e.target.closest('.tab');
    if(!tab||!el.contains(tab))return;
    const t=tab.dataset.t;
    el.querySelectorAll('.tab').forEach(x=>x.classList.toggle('a',x.dataset.t===t));
    ps.forEach(x=>x.classList.toggle('a',x.dataset.t===t));
  };
}
function initNav(){
  try{
    // Initialize stepper: step 1 active by default
    goStep(1);
    // Close settings overlay on background click
    const overlay=$('settings-overlay');
    if(overlay)overlay.onclick=e=>{if(e.target===overlay)closeSettings();};
    // Load step states from backend
    loadStepStates();
  }catch(err){console.error('[initNav/stepper]',err)}
}
function initTabs(){try{document.querySelectorAll('.tabs').forEach(bindTabs)}catch(err){console.error('[initTabs]',err)}}

// === UPLOAD ===
function initUpload(){bindUpload();bindPDFUpload();}
function rfl(){
  const n=Object.keys(ufiles);$('fc').style.display=n.length?'block':'none';
  $('fcl').innerHTML=n.map(id=>{
    const f=ufiles[id];
    const lbl=f.displayName===f.uploadName?esc(f.displayName):esc(f.displayName)+' <span class="m" title="Uploadname">→ '+esc(f.uploadName)+'</span>';
    return '<div class="ci"><input type="checkbox" checked value="'+esc(id)+'" class="fcb"><span>'+lbl+'</span><span class="m">'+(f.size/1024).toFixed(0)+'KB</span></div>';
  }).join('');
}
function populateDS(){
  const names=Object.values(ufiles).map(f=>f.uploadName);
  for(const id of['ner-ds','ner-full-ds','scan-ds','edtf-ds','exp-ds','exp-csv-ds','exp-ld-ds','fm-ds','terms-ds','dict-build-ds','mds-ds','enrich-ds','llmq-ds']){
    const s=$(id);if(!s)continue;
    s.innerHTML=names.map((x,i)=>'<option value="'+esc(x)+'"'+(i===0?' selected':'')+'>'+esc(x)+'</option>').join('')}
  if(names.length>0){
    loadCols('ner-ds','ner-cols');loadCols('dict-build-ds','dict-build-cols');loadDateCols();loadRecords();loadFMCols();
    if($('llmq-ds')&&$('llmq-ds').value)loadCols('llmq-ds','llmq-cols');
    ['ner-hint','edtf-hint','exp-hint'].forEach(id=>{const el=$(id);if(el)el.style.display='none'})
  }
}

// === COLUMNS ===
async function loadCols(dsId,targetId){
  const ds=$(dsId).value;const t=$(targetId);
  if(!ds){t.textContent='Datensatz wählen';return}
  try{const d=await(await fetch('/api/dataset/'+encodeURIComponent(ds)+'/columns')).json();
    if(d.error){t.textContent=d.error;return}
    t.innerHTML=d.columns.map(c=>'<div class="ci"><input type="checkbox" value="'+esc(c.name)+'"'+(c.fill_rate>.1?' checked':'')+'><span>'+esc(c.name)+'</span><span class="m">'+Math.round(c.fill_rate*100)+'%</span></div>').join('')
  }catch(e){t.textContent='Fehler: '+e.message}
}
async function loadDateCols(){
  const ds=$('edtf-ds').value;const s=$('edtf-col');
  if(!ds){s.innerHTML='<option value="">—</option>';return}
  try{const d=await(await fetch('/api/dataset/'+encodeURIComponent(ds)+'/columns')).json();
    if(d.error)return;s.innerHTML=d.columns.map(c=>safeOpt(c.name,c.name+' ('+Math.round(c.fill_rate*100)+'%)')).join('')
  }catch(e){}
}
async function loadRecords(reset=false){
  const ds=$('exp-ds').value;const s=$('exp-rec');
  if(reset)recordOffset=0;
  if(!ds){s.innerHTML='<option value="">—</option>';return}
  const q=encodeURIComponent(($('exp-rec-q')?.value||'').trim());
  try{const d=await(await fetch('/api/dataset/'+encodeURIComponent(ds)+'/records?offset='+recordOffset+'&limit='+recordLimit+'&q='+q)).json();
    if(d.record_ids){
      s.innerHTML=d.record_ids.map(r=>safeOpt(r,r)).join('')||'<option value="">—</option>';
      recordTotal=d.total||0;
      if($('exp-rec-info'))$('exp-rec-info').textContent=(recordTotal?((recordOffset+1)+'–'+Math.min(recordOffset+recordLimit,recordTotal)+' / '+recordTotal):'0 / 0');
      if($('exp-rec-prev'))$('exp-rec-prev').disabled=recordOffset<=0;
      if($('exp-rec-next'))$('exp-rec-next').disabled=!d.has_more;
    }
  }catch(e){}
}
function pageRecords(dir){recordOffset=Math.max(0,recordOffset+(dir*recordLimit));loadRecords(false)}
const expDsEl=$('exp-ds');if(expDsEl)expDsEl.onchange=()=>loadRecords(true);
function initPanels(){const expDs=$('exp-ds');if(expDs)expDs.onchange=()=>loadRecords(true)}

// === FIELD MAPPING ===
let fmCols=[];
let fmMeta={}; // full backend objects per col: {col_name: {csv_column,goobi_type,label,repeatable,...}}
async function loadFMCols(){
  const ds=$('fm-ds').value;
  if(!ds){$('fm-table-wrap').style.display='none';return}
  try{
    const d=await(await fetch('/api/dataset/'+encodeURIComponent(ds)+'/columns')).json();
    if(d.error)return;
    fmCols=d.columns;
    // API payload (GET): {mappings: [{csv_column, goobi_type, label, repeatable, authority, ...}]}
    // fmMeta keeps the full objects so saveFM() can preserve metadata not shown in the UI
    // fmMapping holds the UI state: {col_name: [label, goobi_type]}
    const ex=await(await fetch('/api/workspace/field-mapping')).json();
    fmMapping=((ex.mappings||[]).reduce((acc,m)=>{acc[m.csv_column]=[m.label||m.goobi_type||'',m.goobi_type||''];return acc;},{}));
    fmMeta={};fmMapping={};
    (ex.mappings||[]).forEach(m=>{
      fmMeta[m.csv_column]=m;
      fmMapping[m.csv_column]=[m.label||m.goobi_type,m.goobi_type];
    });
    renderFMTable();
    $('fm-table-wrap').style.display='block';
  }catch(e){}
}

// Build type options: Minimaldatensatz 1.1 group + Goobi group
function _fmTypeOpts(selectedType){
  const mdsOpts=MDS_FIELDS.map(f=>'<option value="'+esc(f.goobi)+'"'+(f.goobi===selectedType?' selected':'')+(f.pflicht?' required':'')+'>'+esc(f.mds+(f.pflicht?' ★':''))+' ('+esc(f.goobi)+')</option>').join('');
  const goobiOpts=GOOBI_TYPES.filter(t=>!MDS_FIELDS.find(f=>f.goobi===t)).map(t=>'<option value="'+esc(t)+'"'+(t===selectedType?' selected':'')+'>'+esc(t)+'</option>').join('');
  return '<option value="">— kein Export —</option>'+
    '<optgroup label="Minimaldatensatz 1.1 (★ = Pflichtfeld)">'+mdsOpts+'</optgroup>'+
    '<optgroup label="Goobi (weitere Typen)">'+goobiOpts+'</optgroup>';
}

function renderFMTable(){
  $('fm-body').innerHTML=fmCols.map(c=>{
    const mapped=fmMapping[c.name];
    const label=mapped?(Array.isArray(mapped)?mapped[0]:mapped):'';
    const type=mapped?(Array.isArray(mapped)?mapped[1]:''):'';
    return '<tr>'+
      '<td><strong>'+esc(c.name)+'</strong></td>'+
      '<td style="font-size:.68rem;color:#888">'+Math.round(c.fill_rate*100)+'%</td>'+
      '<td><input type="text" id="fm-lbl-'+esc(c.name)+'" value="'+esc(label)+'" placeholder="Label (optional)" style="width:130px"></td>'+
      '<td><select id="fm-typ-'+esc(c.name)+'" style="width:220px">'+_fmTypeOpts(type)+'</select></td>'+
      '<td><button class="btn sm" onclick="clearFMRow(\''+esc(c.name)+'\')">✕</button></td>'+
    '</tr>';
  }).join('');
}

// Apply Minimaldatensatz 1.1 template — auto-map columns by heuristic
function applyMDSTemplate(){
  if(!fmCols.length){alert('Erst Datensatz im Mapping-Tab wählen.');return;}
  const colNames=fmCols.map(c=>c.name.toLowerCase());
  MDS_FIELDS.forEach(f=>{
    // Try to find a matching column
    const candidates=[
      f.mds.toLowerCase(), f.goobi.toLowerCase(),
      ...f.mds.toLowerCase().split('/'),
    ];
    let bestCol=null;
    for(const cand of candidates){
      const idx=colNames.findIndex(n=>n.includes(cand)||cand.includes(n));
      if(idx>=0){bestCol=fmCols[idx].name;break;}
    }
    if(bestCol){
      const lbl=$('fm-lbl-'+bestCol);
      const typ=$('fm-typ-'+bestCol);
      if(lbl&&!lbl.value)lbl.value=f.mds;
      if(typ)typ.value=f.goobi;
    }
  });
}

function applyGoobiTemplate(){
  if(!fmCols.length){alert('Erst Datensatz im Mapping-Tab wählen.');return;}
  // Reset and auto-match Goobi types by column name
  const colNames=fmCols.map(c=>c.name.toLowerCase());
  GOOBI_TYPES.forEach(t=>{
    const tl=t.toLowerCase();
    const idx=colNames.findIndex(n=>n.includes(tl)||tl.includes(n));
    if(idx>=0){
      const col=fmCols[idx].name;
      const typ=$('fm-typ-'+col);
      if(typ&&!typ.value)typ.value=t;
    }
  });
}
function clearFMRow(col){
  const lbl=$('fm-lbl-'+col);const typ=$('fm-typ-'+col);
  if(lbl)lbl.value='';if(typ)typ.value='';
}
async function saveFM(){
  // API payload (POST): {mappings: [{csv_column, goobi_type, label, repeatable, authority, ...}]}
  // Spread fmMeta to preserve fields not editable in the UI (repeatable, authority_uri, enabled, note)
  const mappings=[];
  fmCols.forEach(c=>{
    const lbl=$('fm-lbl-'+c.name);const typ=$('fm-typ-'+c.name);
    if(lbl&&typ&&typ.value){
      mappings.push({...(fmMeta[c.name]||{}),csv_column:c.name,goobi_type:typ.value,label:lbl.value||typ.value});
    }
  });
  try{
    await fetch('/api/workspace/field-mapping',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mappings})});
    // Update internal state from saved list
    fmMeta={};fmMapping={};
    mappings.forEach(m=>{fmMeta[m.csv_column]=m;fmMapping[m.csv_column]=[m.label,m.goobi_type];});
    $('fm-saved').style.display='inline';
    setTimeout(()=>{$('fm-saved').style.display='none'},2000);
  }catch(e){alert('Fehler: '+e.message)}
}

// === STRUCTURAL ANALYSIS ===
const _IMAGE_EXTS = new Set(['.jpg','.jpeg','.png','.tif','.tiff','.webp','.img']);
function _fileExt(name){const i=(name||'').lastIndexOf('.');return i>=0?name.slice(i).toLowerCase():'';}

// === INGEST PREVIEW (issue #177) ===
async function previewIngest(){
  const sel=[...document.querySelectorAll('.fcb:checked')].map(c=>c.value);
  if(!sel.length){alert('Mindestens eine Datei auswählen.');return}
  const docFiles=[];
  for(const id of sel){const it=ufiles[id];if(!it)continue;if(!_IMAGE_EXTS.has(_fileExt(it.uploadName)))docFiles.push(it);}
  if(!docFiles.length){alert('Keine Metadaten-Dateien ausgewählt (Bilder benötigen keine Vorschau).');return}
  const fd=new FormData();for(const it of docFiles)fd.append('files',it.file,it.uploadName);
  sp('Vorschau wird geladen …',docFiles.length+' Datei(en)');
  try{
    const r=await(await fetch('/api/ingest/preview',{method:'POST',body:fd})).json();
    if(r.error)throw Error(r.error);
    renderPreview(r.previews||[]);
  }catch(e){alert('Vorschau-Fehler: '+e.message);}finally{hp();}
}

function renderPreview(previews){
  const panel=$('preview-panel'),body=$('preview-body');
  if(!panel||!body)return;
  body.innerHTML=previews.map(p=>_renderPreviewCard(p)).join('');
  panel.style.display='block';
  panel.scrollIntoView({behavior:'smooth',block:'nearest'});
}

function _renderPreviewCard(p){
  let html='<div style="border:1px solid #ddd;border-radius:4px;padding:.6rem;margin-bottom:.5rem;background:#fafafa">';
  html+='<div style="font-weight:600;margin-bottom:.3rem">&#128196; '+esc(p.filename||'?')+' <span style="color:#888;font-weight:400;font-size:.78rem">('+esc(p.format||'')+')</span></div>';
  if(p.error){
    html+='<div style="background:var(--crit,#c33);color:white;padding:.4rem .6rem;border-radius:3px;font-size:.8rem">Fehler: '+esc(p.error)+'</div></div>';
    return html;
  }
  // Encoding
  if(p.encoding){
    const conf=p.encoding.confidence;
    const confStr=conf==null?'—':(Math.round(conf*100)+'%');
    const bom=p.encoding.has_bom?' (BOM)':'';
    const cdAvail=p.encoding.chardet_available;
    const confColor=conf==null?'#666':(conf>=0.9?'var(--ok,#080)':conf>=0.7?'var(--warn,#a60)':'var(--crit,#c33)');
    html+='<div style="font-size:.78rem;margin-bottom:.2rem">Encoding: <strong>'+esc(p.encoding.detected||'?')+'</strong>'+bom+' &middot; Konfidenz: <span style="color:'+confColor+'">'+confStr+'</span>';
    if(!cdAvail)html+=' <span style="color:var(--warn,#a60)" title="chardet nicht installiert">⚠</span>';
    html+='</div>';
  }
  if(p.delimiter!==undefined){
    html+='<div style="font-size:.78rem;margin-bottom:.2rem">Trennzeichen: <code>'+esc(JSON.stringify(p.delimiter))+'</code></div>';
  }
  if(p.xml_format){
    html+='<div style="font-size:.78rem;margin-bottom:.2rem">XML-Format: <strong>'+esc(p.xml_format)+'</strong></div>';
  }
  if(p.sheets&&p.sheets.length){
    html+='<div style="font-size:.78rem;margin-bottom:.2rem">Sheets: '+p.sheets.map(s=>'<code>'+esc(s)+'</code>').join(', ')+(p.active_sheet?' &middot; aktiv: <strong>'+esc(p.active_sheet)+'</strong>':'')+'</div>';
  }
  if(p.row_count!==undefined){
    html+='<div style="font-size:.78rem;margin-bottom:.2rem">'+(p.row_count||0)+' Zeilen &times; '+(p.column_count||0)+' Spalten</div>';
  }
  // ID column
  if(p.id_column){
    const idc=p.id_column;
    html+='<div style="font-size:.78rem;margin-bottom:.2rem">ID-Spalte: <strong>'+(idc.proposed?esc(idc.proposed):'<em style="color:var(--warn,#a60)">keine gefunden</em>')+'</strong>';
    if(idc.candidates&&idc.candidates.length>1){
      html+=' <span style="color:#666">(Alternativen: '+idc.candidates.filter(c=>c!==idc.proposed).slice(0,5).map(c=>'<code>'+esc(c)+'</code>').join(', ')+')</span>';
    }
    html+='</div>';
  }
  // Warnings
  if(p.warnings&&p.warnings.length){
    html+='<div style="background:#fff7e0;border-left:3px solid var(--warn,#a60);padding:.3rem .5rem;margin:.3rem 0;font-size:.76rem">'+p.warnings.map(w=>'⚠ '+esc(w)).join('<br>')+'</div>';
  }
  // Head preview
  if(p.head&&p.head.length){
    const cols=Object.keys(p.head[0]).slice(0,8);
    html+='<details style="margin-top:.3rem"><summary style="cursor:pointer;font-size:.78rem">Vorschau erste '+p.head.length+' Zeilen</summary>';
    html+='<div style="overflow-x:auto;max-height:240px;margin-top:.3rem"><table style="font-size:.72rem;border-collapse:collapse"><thead><tr>'+cols.map(c=>'<th style="border:1px solid #ddd;padding:.2rem .4rem;background:#eee">'+esc(c)+'</th>').join('')+'</tr></thead><tbody>';
    for(const row of p.head){
      html+='<tr>'+cols.map(c=>'<td style="border:1px solid #ddd;padding:.2rem .4rem">'+esc(String(row[c]||'')).slice(0,80)+'</td>').join('')+'</tr>';
    }
    html+='</tbody></table></div></details>';
  }
  html+='</div>';
  return html;
}

function confirmIngest(){
  cancelPreview();
  runStruct();
}

function cancelPreview(){
  const panel=$('preview-panel'),body=$('preview-body');
  if(body)body.innerHTML='';
  if(panel)panel.style.display='none';
}

async function runStruct(){
  const sel=[...document.querySelectorAll('.fcb:checked')].map(c=>c.value);
  if(!sel.length){alert('Mindestens eine Datei auswählen.');return}
  sp('Strukturelle Analyse …',sel.length+' Datei(en)');
  _abortCtrl=new AbortController();

  const imgFiles=[], docFiles=[];
  for(const id of sel){const it=ufiles[id];if(!it)continue;(_IMAGE_EXTS.has(_fileExt(it.uploadName))?imgFiles:docFiles).push(it);}

  // Route image files to the image upload endpoint
  if(imgFiles.length){
    const fd=new FormData();for(const it of imgFiles)fd.append('files',it.file,it.uploadName);
    try{
      const r=await(await fetch('/api/images/upload',{method:'POST',body:fd,signal:_abortCtrl.signal})).json();
      if(r.error)throw Error(r.error);
      uploadedImages=(uploadedImages||[]).concat(r.images||[]);
      renderImgGrid&&renderImgGrid();
      if($('img-upload-status'))$('img-upload-status').textContent=(r.uploaded||imgFiles.length)+' Bild(er) hochgeladen.';
    }catch(e){if(e.name!=='AbortError'){hp();alert(e.message);return;}}
  }

  if(!docFiles.length){hp();return;}

  const fd=new FormData();for(const it of docFiles)fd.append('files',it.file,it.uploadName);
  try{const r=await(await fetch('/api/analyze',{method:'POST',body:fd,signal:_abortCtrl.signal})).json();
    if(r.error)throw Error(r.error);curRep=r;rrep(r);populateDS();updWS();
    // Show ID column bar for step 1c
    if($('id-col-bar'))$('id-col-bar').style.display='block';
  }catch(e){if(e.name!=='AbortError')alert(e.message);}finally{hp()}
}

// === NER ===
async function runNER(isPilot=false){
  const ds=$('ner-ds').value;if(!ds){alert('Datensatz wählen');return}
  const cols=[...document.querySelectorAll('#ner-cols .ci input:checked')].map(c=>c.value);
  if(!cols.length){alert('Mindestens eine Spalte wählen');return}
  const method=$('ner-method').value;
  const baseN=parseInt($('ner-n').value)||10000;
  const n=isPilot?Math.max(1,Math.round(baseN*0.02)):baseN;
  sp(isPilot?'NER Pilotlauf …':'NER läuft …',method+', '+n+' Samples');
  const entityTypes=[...document.querySelectorAll('.ner-type-cb:checked')].map(c=>c.value);
  const body={dataset:ds,columns:cols,method,sample_size:n,
    sample_mode:isPilot?'stratified':'random',sample_percent:isPilot?2:null,
    stratified:isPilot,chunk_size:parseInt($('ner-chunk').value)||200,
    model:$('cfg-mt').value||'',
    entity_types:entityTypes.length<10?entityTypes:[],
    system_prompt:($('ner-sp')?.value||$('cfg-sys').value)};
  try{
    await fetchSSE('/api/ner/stream',body,
      evt=>spUp(evt.chunk,evt.total_chunks,'Chunk '+evt.chunk+' — '+evt.entities_so_far+' Entities'),
      result=>{nerData=result.entities||[];renderNER(result);renderRunMetrics('ner-metrics',result.run_metrics);updWS();},
      msg=>{throw Error(msg);}
    );
  }catch(e){if(e.name!=='AbortError')alert(e.message);}finally{hp();}
}

function renderNER(r){
  if($('ner-e'))$('ner-e').style.display='none';
  if($('ner-r'))$('ner-r').style.display='block';
  if($('ner-count'))$('ner-count').textContent='('+nerData.length+' gefunden, Modell: '+(r.model||'?')+')';
  else if($('ner-metrics'))$('ner-metrics').textContent=nerData.length+' Entities gefunden (Modell: '+(r.model||'?')+')';
  const types=[...new Set(nerData.map(e=>e.type))].sort();
  $('ner-filter').innerHTML='<div class="fb2 a" onclick="setNerType(\'all\',this)">Alle Typen</div>'+
    types.map(t=>'<div class="fb2" onclick="setNerType(\''+esc(t)+'\',this)"><span class="etype etype-'+esc(t)+'">'+esc(t)+'</span> '+nerData.filter(e=>e.type===t).length+'</div>').join('');

  // EXT-BUG-01: Display completion summary
  renderCompletionSummary(r.completion_summary, r.parse_failures);

  // #150: Show which system prompt actually went to the model
  renderSystemPromptUsed('ner-prompt-used', r.system_prompt_used);

  applyNERFilters();
}

// === SYSTEM-PROMPT FINGERPRINT (issue #150) ===
function renderSystemPromptUsed(targetId, fp){
  const el=$(targetId);
  if(!el)return;
  if(!fp){el.innerHTML='';return;}
  const isOverride=!!fp.is_override;
  const color=isOverride?'var(--info,#06c)':'#666';
  const label=isOverride?'&#9998; Override aktiv':'Default-Prompt';
  let html='<div style="background:#f4f7fa;border-left:3px solid '+color+';padding:.4rem .6rem;margin:.4rem 0;font-size:.74rem">';
  html+='<div style="display:flex;justify-content:space-between;align-items:center">';
  html+='<span><strong style="color:'+color+'">'+label+'</strong> &middot; task: <code>'+esc(fp.task||'?')+'</code> &middot; '+(fp.length||0)+' Zeichen</span>';
  html+='<span style="color:#888;font-family:monospace;font-size:.7rem" title="sha256 des gesendeten Prompts">'+esc((fp.sha256||'').slice(0,12))+'&hellip;</span>';
  html+='</div>';
  html+='<details style="margin-top:.25rem"><summary style="cursor:pointer;color:#444">Prompt-Preview anzeigen</summary>';
  html+='<pre style="margin:.25rem 0 0;padding:.4rem;background:#fff;border:1px solid #ddd;white-space:pre-wrap;word-break:break-word;font-size:.7rem">'+esc(fp.preview||'')+'</pre></details>';
  html+='</div>';
  el.innerHTML=html;
}

async function dryRunSystemPrompt(){
  const task=$('cfg-dryrun-task')?.value||'ner';
  const override=$('cfg-sys')?.value||'';
  const out=$('cfg-dryrun-out');
  if(out){out.style.display='block';out.textContent='Wird geprüft …';}
  try{
    const r=await(await fetch('/api/prompts/dry-run',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({task,system_prompt:override}),
    })).json();
    if(out){
      if(r.status==='ok'){
        const fp=r.fingerprint||{};
        const isOverride=!!fp.is_override;
        out.innerHTML='<div style="font-size:.78rem;margin-bottom:.3rem"><strong style="color:'+(isOverride?'var(--info,#06c)':'#666')+'">'+(isOverride?'&#9998; Override würde verwendet':'Default-Prompt würde verwendet')+'</strong> &middot; task: <code>'+esc(task)+'</code> &middot; '+(fp.length||0)+' Zeichen &middot; sha256: <code>'+esc((fp.sha256||'').slice(0,16))+'</code></div>'+
          '<pre style="margin:0;padding:.5rem;background:#fff;border:1px solid #ccc;white-space:pre-wrap;font-size:.72rem;max-height:240px;overflow:auto">'+esc(r.resolved||'')+'</pre>';
      }else{
        out.textContent='Fehler: '+(r.message||'unbekannt');
      }
    }
  }catch(e){
    if(out)out.textContent='Fehler: '+(e.message||String(e));
  }
}

function renderCompletionSummary(summary, parseFailures){
  const banners=['ner-completion-banner','ner-full-completion-banner'];
  for(const bannerId of banners){
    const el=$(bannerId);
    if(!el)continue;
    // Clear any stale banner from a previous run when summary is absent
    // (e.g., when switching from LLM/hybrid mode to SpaCy-only).
    if(!summary){el.innerHTML='';continue;}
    const pct=summary.completion_percentage||0;
    const color=pct>=95?'var(--ok)':pct>=80?'var(--warn)':'var(--crit)';
    let html='<div style="background:'+color+';padding:12px;border-radius:4px;margin-bottom:12px;color:white;font-weight:600">';
    html+='✓ '+pct+'% Abschlussrate ('+summary.succeeded+'/'+summary.total_records+' erfolgreich)';
    if(summary.llm_failed>0)html+=' | ❌ '+summary.llm_failed+' LLM-Fehler';
    if(summary.parse_failed>0)html+=' | ⚠️ '+summary.parse_failed+' Parse-Fehler';
    if(summary.empty_result>0)html+=' | — '+summary.empty_result+' leere Ergebnisse';
    html+='</div>';
    if(parseFailures && parseFailures.length>0){
      html+='<details style="margin-bottom:12px"><summary style="cursor:pointer;font-weight:600">Parse-Fehler-Details ('+parseFailures.length+')</summary>';
      html+='<div style="background:#f5f5f5;padding:8px;border-radius:4px;max-height:200px;overflow-y:auto">';
      html+=parseFailures.map(pf=>'<div style="padding:4px;border-bottom:1px solid #ddd;font-size:.85rem"><strong>'+esc(pf.record_id)+'</strong>: '+esc(pf.error_message)+'<br><code style="color:#666;font-size:.75rem">'+esc(pf.raw_response_preview)+'</code></div>').join('');
      html+='</div></details>';
    }
    el.innerHTML=html;
  }
}

function setNerType(t,b){
  nerTypeFilter=t;
  document.querySelectorAll('#ner-filter .fb2').forEach(x=>x.classList.remove('a'));
  if(b)b.classList.add('a');
  applyNERFilters();
}
function filterStatus(s,b){
  nerStatusFilter=s;
  document.querySelectorAll('#ner-status-bar .fb2').forEach(x=>x.classList.remove('a'));
  if(b)b.classList.add('a');
  applyNERFilters();
}
function applyNERFilters(){
  let ents=nerData;
  if(nerTypeFilter!=='all')ents=ents.filter(e=>e.type===nerTypeFilter);
  if(nerStatusFilter!=='all')ents=ents.filter(e=>(e.status||'pending')===nerStatusFilter);
  fillNERTable(ents);
}

function fillNERTable(ents){
  $('ner-body').innerHTML=ents.map((e)=>{
    const status=e.status||'pending';
    const realIdx=nerData.indexOf(e);
    return '<tr>'+
      '<td style="font-weight:600">'+esc(e.text)+(e.gnd_preferred?'<br><span style="font-size:.65rem;color:var(--ok)">GND: '+esc(e.gnd_preferred)+'</span>':'')+'</td>'+
      '<td><span class="etype etype-'+esc(e.type)+'">'+esc(e.type)+'</span></td>'+
      '<td><span class="conf-bar" style="width:'+Math.round((e.confidence||0)*40)+'px;background:'+((e.confidence||0)>.7?'var(--ok)':(e.confidence||0)>.4?'var(--warn)':'var(--crit)')+'"></span>'+((e.confidence||0)*100).toFixed(0)+'%</td>'+
      '<td style="font-size:.7rem">'+esc(e.reasoning||'')+'</td>'+
      '<td style="font-size:.68rem">'+esc(e.record_id||'')+'</td>'+
      '<td style="font-size:.62rem">'+esc(e.source||'')+'</td>'+
      '<td><span class="est est-'+esc(status)+'">'+esc(status)+'</span></td>'+
      '<td><button class="btn sm" onclick="setEntity('+realIdx+',\'accepted\')">✓</button> <button class="btn sm s" onclick="setEntity('+realIdx+',\'rejected\')">✗</button></td>'+
    '</tr>';
  }).join('');
}

async function setEntity(idx,status){
  try{await fetch('/api/workspace/entity/'+idx,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
    nerData[idx].status=status;applyNERFilters();updWS()
  }catch(e){}
}
async function batchEntities(status){if(!nerData.length)return;
  // Only apply to currently visible (filtered) entities
  let ents=nerData;
  if(nerTypeFilter!=='all')ents=ents.filter(e=>e.type===nerTypeFilter);
  const indices=ents.map((_,i)=>nerData.indexOf(ents[i])).filter(i=>i>=0);
  try{
    await fetch('/api/workspace/entity/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({indices:nerData.map((_,i)=>i),updates:{status}})});
    nerData.forEach(e=>e.status=status);applyNERFilters();updWS();
  }catch(e){alert(e.message)}
}

async function runGNDLookup(){if(!nerData.length){alert('Erst NER ausführen');return}
  sp('GND-Lookup …','lobid.org');
  try{const r=await(await fetch('/api/gnd/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:50})})).json();
    if(r.error)throw Error(r.error);renderGNDResults(r);updWS()
  }catch(e){alert(e.message)}finally{hp()}}

function renderGNDResults(r){
  if($('gnd-r'))$('gnd-r').style.display='block';
  const results=r.results||[];
  $('gnd-body').innerHTML=results.map(gr=>{
    const tm=gr.top_match;
    return '<tr>'+
      '<td style="font-weight:600">'+esc(gr.text||'')+'</td>'+
      '<td><span class="etype etype-'+esc(gr.type||'CON')+'">'+esc(gr.type||'')+'</span></td>'+
      '<td>'+(tm?'<code class="gnd-match">'+esc(tm.gnd_id)+'</code>':'<span class="gnd-none">—</span>')+'</td>'+
      '<td>'+(tm?esc(tm.preferred_name):'')+'</td>'+
      '<td style="font-size:.68rem">'+(tm?esc(tm.type||''):'')+'</td>'+
      '<td style="font-size:.68rem">'+(tm?(tm.alternative_names||[]).slice(0,2).map(n=>esc(n)).join(', '):'')+'</td>'+
    '</tr>';
  }).join('');
  // Update nerData with GND info
  results.forEach(gr=>{
    if(gr.top_match){
      nerData.filter(e=>e.text===gr.text&&e.type===gr.type).forEach(e=>{
        e.gnd_id=gr.top_match.gnd_id;e.gnd_preferred=gr.top_match.preferred_name;
      });
    }
  });
  applyNERFilters();
}

function exportNER(){if(!nerData.length)return;
  const hdr='text,type,confidence,reasoning,record_id,source,status,gnd_id,gnd_preferred\n';
  const rows=nerData.map(e=>[e.text,e.type,e.confidence,e.reasoning,e.record_id,e.source,e.status||'',e.gnd_id||'',e.gnd_preferred||''].map(v=>'"'+(v||'').toString().replace(/"/g,'""')+'"').join(',')).join('\n');
  dl('debussy_ner.csv',hdr+rows,'text/csv')}

// === SCAN ===
async function runScan(isPilot=false){const ds=$('scan-ds').value;if(!ds){alert('Datensatz wählen');return}
  const baseN=parseInt($('scan-n').value)||10000;
  const n=isPilot?Math.max(1,Math.round(baseN*0.02)):baseN;
  sp(isPilot?'Scan Pilotlauf …':'Scan …','');
  const body={dataset:ds,sample_size:n,
    sample_mode:isPilot?'stratified':'random',sample_percent:isPilot?2:null,
    stratified:isPilot,chunk_size:parseInt($('scan-chunk').value)||200,
    model:$('cfg-mt').value||'',
    system_prompt:($('scan-sp')?.value||$('cfg-sys').value)};
  try{
    await fetchSSE('/api/scan/stream',body,
      evt=>spUp(evt.chunk,evt.total_chunks,'Chunk '+evt.chunk+' — '+evt.issues_so_far+' Begriffe'),
      result=>{renderScan(result);renderRunMetrics('scan-metrics',result.run_metrics);},
      msg=>{throw Error(msg);}
    );
  }catch(e){if(e.name!=='AbortError')alert(e.message);}finally{hp();}}


function renderScan(r){if($('scan-r'))$('scan-r').style.display='block';const issues=r.issues||[];
  if(!$('scan-body'))return;
  if(!issues.length){$('scan-body').innerHTML='<p style="color:var(--ok)">Keine problematischen Begriffe gefunden.</p>';return}
  $('scan-body').innerHTML=issues.map(i=>'<div class="fd '+(i.severity==='high'?'critical':'warning')+'">'+
    '<strong>'+esc(i.term||'?')+'</strong> <span style="font-size:.7rem;color:#888">'+esc(i.record_id||'')+'</span>'+
    '<div style="font-size:.75rem">'+esc(i.reason||'')+'</div>'+
    (i.suggestion?'<div style="font-style:italic;color:var(--ac);font-size:.73rem">→ '+esc(i.suggestion)+'</div>':'')+
  '</div>').join('')}

// === PROBLEMATISCHE BEGRIFFE (Dictionary-based) ===
async function loadTermsDict(){
  try{const r=await(await fetch('/api/problematic-terms')).json();
    termsData=r.terms||[];renderTermsDict();}catch(e){}
}
function renderTermsDict(){
  const listEl=$('terms-dict-list');const emptyEl=$('terms-list-empty');const countEl=$('terms-count');
  if(!listEl)return;
  if(countEl)countEl.textContent='('+termsData.length+' Einträge)';
  if(!termsData.length){if(emptyEl)emptyEl.style.display='block';listEl.innerHTML='';return;}
  if(emptyEl)emptyEl.style.display='none';
  listEl.innerHTML=termsData.map((t,i)=>'<div class="terms-entry">'+
    '<div class="terms-term">'+esc(t.term)+''+
      (t.replacement?'<span class="terms-repl"> → '+esc(t.replacement)+'</span>':'')+
    '</div>'+
    (t.category?'<span class="terms-cat">'+esc(t.category)+'</span>':'')+
    '<button class="btn sm s" style="padding:.1rem .35rem;margin:0" onclick="deleteTerm('+i+')">✕</button>'+
  '</div>').join('');
}
async function addTermManual(){
  const term=($('terms-new-term')?.value||'').trim();
  if(!term){alert('Bitte Begriff eingeben.');return;}
  const msg=$('terms-add-msg');
  try{
    const r=await fetch('/api/problematic-terms',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        term,
        replacement:$('terms-new-repl')?.value||'',
        category:$('terms-new-cat')?.value||'',
        note:$('terms-new-note')?.value||'',
      })});
    const d=await r.json();
    if(d.error){if(msg){msg.style.color='var(--crit)';msg.textContent=d.error;msg.style.display='block';}return;}
    termsData=d.terms||[];renderTermsDict();
    if($('terms-new-term'))$('terms-new-term').value='';
    if($('terms-new-repl'))$('terms-new-repl').value='';
    if($('terms-new-note'))$('terms-new-note').value='';
    if(msg){msg.style.color='var(--ok)';msg.textContent='✓ Begriff hinzugefügt';msg.style.display='block';setTimeout(()=>{msg.style.display='none';},2000);}
  }catch(e){if(msg){msg.style.color='var(--crit)';msg.textContent='Fehler: '+e.message;msg.style.display='block';}}
}
async function deleteTerm(idx){
  try{
    const r=await fetch('/api/problematic-terms/'+idx,{method:'DELETE'});
    const d=await r.json();
    if(d.error){alert(d.error);return;}
    termsData.splice(idx,1);renderTermsDict();
  }catch(e){alert('Fehler: '+e.message);}
}
async function clearAllTerms(){
  if(!confirm('Alle Begriffe aus dem Wörterbuch löschen?'))return;
  for(let i=termsData.length-1;i>=0;i--){
    try{await fetch('/api/problematic-terms/'+i,{method:'DELETE'});}catch(e){}
  }
  termsData=[];renderTermsDict();
}
async function uploadTermsDict(){
  const file=$('terms-file')?.files?.[0];
  if(!file){alert('Bitte Datei auswählen.');return;}
  const fd=new FormData();fd.append('file',file);
  sp('Wörterbuch wird geladen…','');
  try{
    const r=await fetch('/api/dict-upload',{method:'POST',body:fd});
    const d=await r.json();
    if(d.error){alert('Fehler: '+d.error);hp();return;}
    termsData=d.terms||[];renderTermsDict();
    alert(d.added+' Begriffe hinzugefügt. Gesamt: '+d.total);
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}
async function runDictScan(){
  const ds=$('terms-ds')?.value;
  if(!ds){alert('Datensatz wählen.');return;}
  if(!termsData.length){alert('Wörterbuch ist leer. Bitte erst Begriffe hinzufügen.');return;}
  sp('Dictionary-Scan läuft…',termsData.length+' Begriffe');
  _abortCtrl=new AbortController();
  try{
    const r=await fetch('/api/dict-scan',{method:'POST',headers:{'Content-Type':'application/json'},
      signal:_abortCtrl.signal,
      body:JSON.stringify({
        dataset:ds,
        whole_word:$('terms-whole-word')?.checked!==false,
        case_sensitive:$('terms-case-sensitive')?.checked||false,
        scan_ocr:$('terms-scan-ocr')?.checked||false,
      })});
    const d=await r.json();
    if(d.error){alert('Fehler: '+d.error);hp();return;}
    termsScanResults=d.matches||[];
    termsCatFilter='all';
    renderDictScanResults(d);
  }catch(e){if(e.name!=='AbortError')alert('Fehler: '+e.message);}finally{hp();}
}
function renderDictScanResults(d){
  const resEl=$('terms-results');const emptyEl=$('terms-results-empty');
  const countEl=$('terms-match-count');const metricsEl=$('terms-metrics');const bodyEl=$('terms-body');
  const catBarEl=$('terms-cat-bar');
  if(!resEl)return;
  if(countEl)countEl.textContent='('+d.total_matches+' Treffer in '+(d.records_scanned||0)+' Datensätzen, '+d.terms_checked+' Begriffe geprüft)';
  if(metricsEl)metricsEl.textContent='Datensatz: '+esc(d.dataset||'')+'  ·  Treffer: '+d.total_matches;
  if(!d.total_matches){
    resEl.style.display='none';if(emptyEl){emptyEl.style.display='block';emptyEl.innerHTML='<h3>Keine Treffer</h3><p style="font-size:.75rem;color:var(--ok)">Keine Begriffe aus dem Wörterbuch im Datensatz gefunden.</p>';}return;
  }
  resEl.style.display='block';if(emptyEl)emptyEl.style.display='none';
  // Category filter
  const cats=[...new Set((d.matches||[]).map(m=>m.category||''))].filter(Boolean);
  if(catBarEl)catBarEl.innerHTML='<div class="fb2 a" onclick="setTermsCat(\'all\',this)">Alle ('+d.total_matches+')</div>'+cats.map(c=>'<div class="fb2" onclick="setTermsCat(\''+esc(c)+'\',this)">'+esc(c)+' ('+(d.matches||[]).filter(m=>m.category===c).length+')</div>').join('');
  renderDictScanTable(d.matches||[]);
}
function setTermsCat(cat,btn){
  termsCatFilter=cat;
  document.querySelectorAll('#terms-cat-bar .fb2').forEach(x=>x.classList.remove('a'));
  if(btn)btn.classList.add('a');
  const filtered=cat==='all'?termsScanResults:termsScanResults.filter(m=>m.category===cat);
  renderDictScanTable(filtered);
}
function renderDictScanTable(matches){
  const bodyEl=$('terms-body');if(!bodyEl)return;
  bodyEl.innerHTML=matches.map(m=>'<tr>'+
    '<td><strong>'+esc(m.term)+'</strong></td>'+
    '<td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem" title="'+esc(m.cell_value)+'">'+esc((m.cell_value||'').substring(0,80))+'</td>'+
    '<td style="font-size:.7rem">'+esc(m.column)+'</td>'+
    '<td style="font-size:.7rem">'+esc(m.record_id)+'</td>'+
    '<td style="font-size:.7rem;color:var(--ok);font-style:italic">'+esc(m.replacement||'—')+'</td>'+
    '<td>'+(m.category?'<span class="terms-cat">'+esc(m.category)+'</span>':'—')+'</td>'+
  '</tr>').join('');
}
function exportTermsResults(){
  if(!termsScanResults.length){alert('Keine Ergebnisse zum Exportieren.');return;}
  const hdr='term,cell_value,column,record_id,replacement,category,note\n';
  const rows=termsScanResults.map(m=>[m.term,m.cell_value,m.column,m.record_id,m.replacement,m.category,m.note].map(v=>'"'+(v||'').toString().replace(/"/g,'""')+'"').join(',')).join('\n');
  dl('debussy_begriffe_scan.csv',hdr+rows,'text/csv;charset=utf-8-sig');
}
function exportTermsDict(){
  if(!termsData.length){alert('Wörterbuch ist leer.');return;}
  const hdr='term,replacement,category,note\n';
  const rows=termsData.map(t=>[t.term,t.replacement,t.category,t.note].map(v=>'"'+(v||'').toString().replace(/"/g,'""')+'"').join(',')).join('\n');
  dl('debussy_woerterbuch.csv',hdr+rows,'text/csv;charset=utf-8-sig');
}

// === EDTF ===
async function runEDTF(isPilot=false){const ds=$('edtf-ds').value,col=$('edtf-col').value;
  if(!ds||!col){alert('Datensatz und Spalte wählen');return}
  const baseN=parseInt($('edtf-n').value)||0;
  const n=isPilot?Math.max(1,Math.round((baseN||10000)*0.02)):baseN;
  sp(isPilot?'EDTF Pilotlauf …':'EDTF …',esc(col));
  const body={dataset:ds,column:col,sample_size:n,
    sample_mode:isPilot?'stratified':'random',sample_percent:isPilot?2:null,
    stratified:isPilot,chunk_size:parseInt($('edtf-chunk').value)||200,
    use_llm:$('edtf-llm').value==='1',
    model:$('cfg-mt').value||'',
    system_prompt:$('edtf-sp').value||$('cfg-sys').value};
  try{
    await fetchSSE('/api/edtf/stream',body,
      evt=>spUp(evt.chunk,evt.total_chunks,'Chunk '+evt.chunk+' — '+evt.results_so_far+' konvertiert'),
      result=>{edtfData=result.results||[];renderEDTF(result);renderRunMetrics('edtf-metrics',result.run_metrics);updWS();},
      msg=>{throw Error(msg);}
    );
  }catch(e){if(e.name!=='AbortError')alert(e.message);}finally{hp();}}


function renderEDTF(r){
  if($('edtf-e'))$('edtf-e').style.display='none';
  if($('edtf-r'))$('edtf-r').style.display='block';
  if(!$('edtf-sg'))return;
  $('edtf-sg').innerHTML='<div class="mt su"><div class="v">'+(r.total||0)+'</div><div class="l">Total</div></div><div class="mt su"><div class="v">'+(r.converted||0)+'</div><div class="l">Konvertiert</div></div><div class="mt wr"><div class="v">'+(r.failed||0)+'</div><div class="l">Fehlgeschlagen</div></div><div class="mt in"><div class="v">'+(r.undated||0)+'</div><div class="l">Undatiert</div></div>';
  $('edtf-body').innerHTML=(r.results||[]).map(e=>'<tr><td>'+esc(e.original||'—')+'</td><td><strong>'+esc(e.edtf||'—')+'</strong></td><td><span class="conf-bar" style="width:'+Math.round((e.confidence||0)*40)+'px;background:'+((e.confidence||0)>.7?'var(--ok)':'var(--warn)')+'"></span>'+((e.confidence||0)*100).toFixed(0)+'%</td><td style="font-size:.65rem">'+esc(e.method||'')+'</td><td style="font-size:.7rem">'+esc(e.note||'')+'</td></tr>').join('')}

// === EXPORT ===
async function previewXML(){const ds=$('exp-ds').value;if(!ds){alert('Datensatz wählen');return}
  sp('XML …','');
  try{const r=await(await fetch('/api/export/goobi-preview',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds,record_id:$('exp-rec').value})})).json();
    if(r.error)throw Error(r.error);$('exp-xml').style.display='block';$('exp-xml').textContent=r.xml||'(leer)'
  }catch(e){alert(e.message&&e.message.includes('field mapping')?'Export fehlgeschlagen: Bitte erst im Tab \u2554 Mapping die CSV-Spalten den Goobi-Feldern zuordnen.':e.message)}finally{hp()}}

async function batchXML(){const ds=$('exp-ds').value;if(!ds){alert('Datensatz wählen');return}
  sp('Batch-Export …','');
  try{const r=await(await fetch('/api/export/goobi-batch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds})})).json();
    if(r.error)throw Error(r.error);dl('debussy_goobi.xml',r.xml||'','application/xml');
    $('exp-xml').style.display='block';$('exp-xml').textContent='Exportiert: '+r.record_count+' Records'
  }catch(e){alert(e.message&&e.message.includes('field mapping')?'Export fehlgeschlagen: Bitte erst im Tab \u2554 Mapping die CSV-Spalten den Goobi-Feldern zuordnen.':e.message)}finally{hp()}}


async function goobiStatus(){
  sp('Goobi Status …','');
  try{const r=await(await fetch('/api/goobi/status')).json();
    $('exp-goobi-status').style.display='block';
    $('exp-goobi-status').textContent=JSON.stringify(r,null,2);
  }catch(e){alert(e.message)}finally{hp()}}

async function goobiPushRecord(){const ds=$('exp-ds').value;if(!ds){alert('Datensatz wählen');return}
  sp('Goobi Record Push …','');
  try{const r=await(await fetch('/api/goobi/push-record',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds,record_id:$('exp-rec').value})})).json();
    if(r.error)throw Error(r.error);
    $('exp-goobi-status').style.display='block';
    $('exp-goobi-status').textContent='Record '+(r.record_id||'')+' erfolgreich gepusht\n'+JSON.stringify(r.remote||{},null,2);
  }catch(e){alert(e.message)}finally{hp()}}

async function goobiPushBatch(){const ds=$('exp-ds').value;if(!ds){alert('Datensatz wählen');return}
  sp('Goobi Batch Push …','');
  try{const r=await(await fetch('/api/goobi/push-batch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds})})).json();
    if(r.error)throw Error(r.error);
    $('exp-goobi-status').style.display='block';
    $('exp-goobi-status').textContent='Batch erfolgreich gepusht ('+(r.record_count||0)+' Records)\n'+JSON.stringify(r.remote||{},null,2);
  }catch(e){alert(e.message)}finally{hp()}}

// === WORKSPACE ===
async function updWS(){try{const r=await(await fetch('/api/workspace')).json();
    $('ws-name').textContent=r.name||'default';$('ws-ents').textContent=r.entity_count||0;
    $('ws-dates').textContent=r.date_count||0;$('ws-dict').textContent=r.dictionary_size||0}catch(e){}}
async function saveWS(){const name=prompt('Projektname:','debussy_project');if(!name)return;
  try{const r=await(await fetch('/api/workspace/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})).json();
    if(r.error)throw Error(r.error);alert('Gespeichert: '+r.path)}catch(e){alert(e.message)}}
async function loadWS(file){if(!file)return;const fd=new FormData();fd.append('file',file);
  try{const r=await(await fetch('/api/workspace/load',{method:'POST',body:fd})).json();
    if(r.error)throw Error(r.error);alert('Geladen: '+(r.entity_count||0)+' Entities');updWS()}catch(e){alert(e.message)}}

// === CONFIG ===
async function loadGPUConfig(){
  try{const d=await(await fetch('/api/gpu/config')).json();
    if($('cfg-url'))$('cfg-url').value=d.gpustack_url||'';
    if($('cfg-key'))$('cfg-key').placeholder=d.gpustack_key_masked
      ?'Aktuell: '+d.gpustack_key_masked+' (leer = unverändert)'
      :'sk-… (leer lassen = unverändert)';
    if(d.gpustack_model_text&&$('cfg-mt'))$('cfg-mt').value=d.gpustack_model_text;
    if(d.gpustack_model_vision&&$('cfg-mv'))$('cfg-mv').value=d.gpustack_model_vision;
  }catch(e){console.error('loadGPUConfig',e)}}

function toggleKeyVis(){const inp=$('cfg-key');inp.type=inp.type==='password'?'text':'password';}

async function saveGPUConfig(){
  const url=($('cfg-url')?.value||'').trim();
  const key=($('cfg-key')?.value||'').trim();
  const mt=($('cfg-mt')?.value||'').trim();
  const mv=($('cfg-mv')?.value||'').trim();
  const st=$('cfg-save-status');
  if(st)st.textContent='Speichern…';
  try{const r=await(await fetch('/api/gpu/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({gpustack_url:url,gpustack_key:key,gpustack_model_text:mt,gpustack_model_vision:mv})})).json();
    if(st)st.textContent=r.status==='ok'?'✓ Gespeichert':'✗ '+(r.message||'Fehler');
    if(r.status==='ok'){await chkGPU();await loadGPUConfig();}
  }catch(e){if(st)st.textContent='✗ '+e.message}}

function loadPreset(){const k=$('cfg-preset').value;$('cfg-sys').value=PRESETS[k]||''}
function applyActionPreset(action){const map={ner:['ner-preset','ner-sp'],scan:['scan-preset','scan-sp'],edtf:['edtf-preset','edtf-sp'],ocr:['ocr-preset','ocr-sp']};const m=map[action];if(!m)return;const src=$(m[0]);const tgt=$(m[1]);if(!src||!tgt)return;const k=src.value;if(k!=='custom')tgt.value=PRESETS[k]||'';}
async function testConn(){sp('Test …','');$('cfg-test').style.display='none';
  try{const r=await(await fetch('/api/gpu/test',{method:'POST'})).json();
    $('cfg-test').style.display='block';$('cfg-test').textContent=JSON.stringify(r,null,2)
  }catch(e){$('cfg-test').style.display='block';$('cfg-test').textContent='Fehler: '+e.message}finally{hp()}}

// === REPORT ===
function rrep(d){
  $('de').style.display='none';$('dr').style.display='block';
  const s=d.summary||{};
  $('dsg').innerHTML='<div class="mt su"><div class="v">'+(s.total_records||0).toLocaleString()+'</div><div class="l">Records</div></div><div class="mt"><div class="v">'+(s.total_columns||0)+'</div><div class="l">Spalten</div></div><div class="mt cr"><div class="v">'+(s.critical||0)+'</div><div class="l">Kritisch</div></div><div class="mt wr"><div class="v">'+(s.warnings||0)+'</div><div class="l">Warnungen</div></div><div class="mt in"><div class="v">'+(s.info||0)+'</div><div class="l">Hinweise</div></div>';
  const fs=d.findings||[];
  $('fbar').innerHTML='<div class="fb2 a" onclick="ff(\'all\',this)">Alle ('+fs.length+')</div><div class="fb2" onclick="ff(\'critical\',this)">Kritisch ('+(s.critical||0)+')</div><div class="fb2" onclick="ff(\'warning\',this)">Warnungen ('+(s.warnings||0)+')</div><div class="fb2" onclick="ff(\'info\',this)">Hinweise ('+(s.info||0)+')</div>';
  rfnd(fs);
  rQM(d.quality_measures||[]);
  rQualityAnalysis(d.quality_analysis||{});
  rCombinedCols(d.datasets||[]);
  if($('mdx'))$('mdx').value=d.markdown||'';
  // Show ID column selection bar
  showIdColBar(d);
  // Show LLM quality control panel (section 1d)
  if($('llm-quality-ctrl'))$('llm-quality-ctrl').style.display='block';
  // Reset LLM quality results to placeholder state for new dataset
  if($('llmq-placeholder'))$('llmq-placeholder').style.display='block';
  if($('llmq-result'))$('llmq-result').style.display='none';
  if($('llmq-run-status'))$('llmq-run-status').textContent='';
  // Unlock all phases since data is now loaded
  unlockAllPhases();
}
function ff(f,b){document.querySelectorAll('#fbar .fb2').forEach(x=>x.classList.remove('a'));if(b)b.classList.add('a');rfnd(f==='all'?(curRep?.findings||[]):(curRep?.findings||[]).filter(x=>x.severity===f))}
function rfnd(fs){if(!fs.length){$('flist').textContent='Keine Findings.';return}
  $('flist').innerHTML=fs.map(f=>'<div class="fd '+esc(f.severity)+'"><span class="sv '+esc(f.severity)+'">'+esc(f.severity)+'</span> <span style="font-size:.62rem;color:#888">'+esc(f.category)+'</span><div style="margin-top:.1rem">'+esc(f.message)+'</div>'+(f.column?'<div style="font-size:.68rem;color:#666">Spalte: '+esc(f.column)+'</div>':'')+(f.suggestion?'<div style="font-style:italic;color:var(--ac);font-size:.73rem">→ '+esc(f.suggestion)+'</div>':'')+'</div>').join('')}

// === QUALITY MEASURES PANEL ===
const QM_LABELS={completeness:'Vollständigkeit',uniqueness:'Eindeutigkeit',structural_validity:'Strukturelle Gültigkeit',consistency:'Konsistenz',semantic_correctness:'Semantische Korrektheit',normalization:'Normalisierung',clarity:'Klarheit',cross_field_coherence:'Feldzusammenhang',provenance:'Provenienz',fitness_for_use:'Nutzbarkeit',risk_severity:'Risiko / Schwere',actionability:'Handlungsrelevanz'};
const QM_ICONS={good:'✅',needs_review:'⚠️',critical:'🔴',insufficient_data:'⬜'};
const QM_COLORS={good:'var(--ok)',needs_review:'var(--warn)',critical:'var(--crit)',insufficient_data:'#aaa'};
function rQM(ms){
  const area=$('qmarea');if(!area)return;
  if(!ms||!ms.length){area.innerHTML='<p style="font-size:.8rem;color:#888;padding:.5rem">Keine Qualitätsmaße verfügbar.</p>';return}
  const rows=ms.map(m=>{
    const lbl=QM_LABELS[m.measure]||m.measure;
    const icon=QM_ICONS[m.status]||'';
    const col=QM_COLORS[m.status]||'#666';
    const sc=m.score!=null?m.score:'—';
    const barW=m.score!=null?Math.round(m.score*0.6):0;
    const actions=(m.recommended_actions||[]).map(a=>'<li>'+esc(a)+'</li>').join('');
    const actBlock=actions?'<ul style="margin:.2rem 0 0 1rem;padding:0;font-size:.68rem;color:#555">'+actions+'</ul>':'';
    return '<div style="border:1px solid var(--brd);border-radius:4px;padding:.5rem .6rem;margin-bottom:.4rem">'+
      '<div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">'+
      '<span style="font-weight:600;font-size:.8rem;min-width:180px">'+icon+' '+esc(lbl)+'</span>'+
      '<span style="background:#eef;border-radius:10px;padding:.1rem .45rem;font-size:.7rem;font-weight:700;color:'+col+'">'+sc+(sc!=='—'?'/100':'')+'</span>'+
      '<span class="fb0" style="width:'+barW+'px;background:'+col+'"></span>'+
      '</div>'+
      '<div style="font-size:.73rem;color:#444;margin-top:.25rem">'+esc(m.summary)+'</div>'+
      (m.evidence_count?'<div style="font-size:.67rem;color:#888;margin-top:.15rem">'+m.evidence_count+' Belege</div>':'')+
      actBlock+
      '</div>';
  });
  area.innerHTML=rows.join('');
}

// === PHASE-1 QUALITY ANALYSIS REPORT (Issue-Cluster, Arbeitspakete, Provenienz) ===
const _SEV_COLORS={critical:'var(--crit)',warning:'var(--warn)',info:'var(--info)'};

function rQualityAnalysis(qa){
  rIssueClusters(qa.issue_clusters||[]);
  rWorkPackages(qa.work_package_candidates||[]);
  rProvenance(qa.analysis_provenance||null);
}

function rIssueClusters(clusters){
  const area=$('qm-clusters-area');if(!area)return;
  if(!clusters.length){area.innerHTML='';return}
  area.innerHTML='<h4 style="font-size:.78rem;font-weight:700;margin:.2rem 0 .4rem;color:#444;border-top:1px solid var(--brd);padding-top:.4rem">Befund-Cluster</h4>'+
    clusters.map(cl=>{
      const sev=cl.severity||'info';const col=_SEV_COLORS[sev]||'#bbb';
      return '<div style="border-left:3px solid '+col+';padding:.35rem .6rem;margin-bottom:.3rem;background:#fff;border-radius:0 4px 4px 0;font-size:.77rem">'+
        '<span style="font-weight:700">'+esc(cl.label||cl.cluster_id||'Cluster')+'</span>'+
        ' <span class="sv '+esc(sev)+'" style="color:'+col+'">'+esc(sev)+'</span>'+
        (cl.affected_records_count?' <span style="color:#888;font-size:.68rem">'+cl.affected_records_count+' Records</span>':'')+
        (cl.affected_columns&&cl.affected_columns.length?'<div style="font-size:.68rem;color:#666;margin-top:.1rem">Spalten: '+cl.affected_columns.slice(0,6).map(c=>'<code>'+esc(c)+'</code>').join(', ')+(cl.affected_columns.length>6?' u.a.':'')+'</div>':'')+
        (cl.suggested_action?'<div style="font-size:.7rem;color:var(--ac);font-style:italic;margin-top:.1rem">&rarr; '+esc(cl.suggested_action)+'</div>':'')+
      '</div>';
    }).join('');
}

function rWorkPackages(wps){
  const area=$('qm-wps-area');if(!area)return;
  if(!wps.length){area.innerHTML='';return}
  area.innerHTML='<h4 style="font-size:.78rem;font-weight:700;margin:.2rem 0 .4rem;color:#444;border-top:1px solid var(--brd);padding-top:.4rem">Arbeitspakete</h4>'+
    wps.map((wp,i)=>{
      const prio=wp.priority||'info';const col=_SEV_COLORS[prio]||'#bbb';
      return '<div style="border:1px solid var(--brd);border-radius:4px;padding:.4rem .6rem;margin-bottom:.3rem;font-size:.77rem;background:#fff">'+
        '<div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">'+
        '<span style="font-weight:700;flex:1">'+esc(wp.title||'Arbeitspaket '+(i+1))+'</span>'+
        '<span class="sv '+esc(prio)+'" style="color:'+col+'">'+esc(prio)+'</span>'+
        (wp.estimated_records?'<span style="font-size:.68rem;color:#888">~'+wp.estimated_records+' Records</span>':'')+
        '</div>'+
        (wp.description?'<div style="font-size:.7rem;color:#555;margin-top:.15rem">'+esc(wp.description)+'</div>':'')+
        (wp.affected_columns&&wp.affected_columns.length?'<div style="font-size:.68rem;color:#666;margin-top:.1rem">Spalten: '+wp.affected_columns.slice(0,5).map(c=>'<code>'+esc(c)+'</code>').join(', ')+(wp.affected_columns.length>5?' u.a.':'')+'</div>':'')+
      '</div>';
    }).join('');
}

function rProvenance(prov){
  const area=$('qm-provenance-area');if(!area)return;
  if(!prov){area.innerHTML='';return}
  area.innerHTML='<div style="font-size:.67rem;color:#aaa;padding:.3rem 0 0;border-top:1px solid var(--brd);margin-top:.2rem">'+
    'Analyse: <strong>'+esc(prov.analysis_mode||'')+'</strong>'+
    (prov.analyzer_version?' &middot; v'+esc(prov.analyzer_version):'')+
    (prov.analyzed_at?' &middot; '+esc(prov.analyzed_at.substring(0,19).replace('T',' '))+' UTC':'')+
    (prov.source_name?' &middot; Quelle: '+esc(prov.source_name):'')+
  '</div>';
}

// === PHASE-2 KI-QUALITÄTSPRÜFUNG ===
function llmqToggleSampleRow(){
  const pilot=document.querySelector('input[name="llmq-mode"]:checked')?.value==='pilot';
  const row=$('llmq-sample-row');
  if(row)row.style.display=pilot?'block':'none';
}

function llmqSelectAllCols(checked){
  document.querySelectorAll('#llmq-cols .ci input[type="checkbox"]').forEach(cb=>cb.checked=checked);
}

async function runLLMQuality(){
  const dsEl=$('llmq-ds');
  if(!dsEl||!dsEl.value){alert('Bitte einen Datensatz w\u00e4hlen.');return}
  const dataset_id=dsEl.value;
  const model=($('llmq-model')?.value)||null;
  const levels=[...document.querySelectorAll('#llm-quality-ctrl input[id^="llmq-lvl-"]:checked')].map(cb=>cb.value);
  if(!levels.length){alert('Mindestens eine Analyseebene w\u00e4hlen.');return}
  const mode=document.querySelector('input[name="llmq-mode"]:checked')?.value||'pilot';
  const sample_size=parseInt($('llmq-sample')?.value||'50')||50;
  const selCols=[...document.querySelectorAll('#llmq-cols .ci input[type="checkbox"]:checked')].map(cb=>cb.value);
  const columns=selCols.length?selCols:null;

  const status=$('llmq-run-status');
  if(status)status.textContent='';
  sp('KI-Qualit\u00e4tspr\u00fcfung l\u00e4uft\u2026',mode==='pilot'?'Pilotlauf ('+sample_size+' Zeilen)':'Vollanalyse \u2014 '+levels.join(', '));
  _abortCtrl=new AbortController();

  try{
    const r=await(await fetch('/api/ai/quality-check',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      signal:_abortCtrl.signal,
      body:JSON.stringify({dataset_id,model:model||null,columns,levels,mode,sample_size})
    })).json();

    if(r.status==='error'){
      if(status)status.textContent='\u2717 '+(r.message||'Unbekannter Fehler');
      hp();return;
    }

    const sum=r.summary||{};
    if(status)status.innerHTML=
      '\u2713 Fertig &mdash; '+
      (sum.total_cell_findings||0)+' Zell-Befunde &middot; '+
      (sum.total_column_reports||0)+' Spalten-Berichte'+
      (r.model_used?' &middot; Modell: <code>'+esc(r.model_used)+'</code>':'');

    renderLLMQualityResults(r);
    // Switch to the KI-Qualitätsprüfung tab
    const tab=document.querySelector('#dt .tab[data-t="llmq"]');
    if(tab)tab.click();
  }catch(e){
    if(e.name!=='AbortError'&&status)status.textContent='\u2717 '+e.message;
  }finally{hp()}
}

function renderLLMQualityResults(data){
  const report=data.report||{};
  const summary=data.summary||{};

  if($('llmq-placeholder'))$('llmq-placeholder').style.display='none';
  const resultEl=$('llmq-result');
  if(resultEl)resultEl.style.display='block';

  // Summary metrics bar
  const sb=$('llmq-summary-bar');
  if(sb){
    sb.innerHTML=
      '<div class="mt"><div class="v">'+(data.analyzed_columns||[]).length+'</div><div class="l">Spalten</div></div>'+
      '<div class="mt cr"><div class="v">'+(summary.total_cell_findings||0)+'</div><div class="l">Zell-Befunde</div></div>'+
      '<div class="mt wr"><div class="v">'+(summary.total_column_reports||0)+'</div><div class="l">Spalten-Berichte</div></div>'+
      '<div class="mt in"><div class="v">'+(summary.total_record_reports||0)+'</div><div class="l">Record-Berichte</div></div>'+
      '<div class="mt su" style="font-size:.65rem"><div class="v" style="font-size:.8rem;word-break:break-all">'+esc(data.model_used||'Mock')+'</div><div class="l">Modell</div></div>';
  }

  // --- Cell findings ---
  const cellEl=$('llmq-cell-content');
  if(cellEl){
    const findings=report.cell_findings||[];
    if(!findings.length){
      cellEl.innerHTML='<p style="font-size:.8rem;color:#888;padding:.5rem">Keine Zell-Befunde (alle gepr\u00fcften Zellen korrekt oder keine Zell-Ebene aktiviert).</p>';
    }else{
      cellEl.innerHTML=
        '<div class="scroll-box"><table class="etbl"><thead><tr>'+
        '<th>Record</th><th>Spalte</th><th>Wert</th><th>Problem-Typ</th><th>Schwere</th><th>Konf.</th><th>Begr\u00fcndung</th><th>Empfehlung</th>'+
        '</tr></thead><tbody>'+
        findings.map(f=>{
          const sev=f.severity||'info';const sc=_SEV_COLORS[sev]||'#888';
          return '<tr>'+
            '<td style="font-size:.65rem;max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+esc(f.record_id)+'">'+esc(f.record_id)+'</td>'+
            '<td><code style="font-size:.68rem">'+esc(f.column)+'</code></td>'+
            '<td style="max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem" title="'+esc(f.value||'')+'">'+esc((f.value||'').substring(0,40))+'</td>'+
            '<td><span style="font-size:.62rem;font-weight:700;font-family:monospace;padding:.1rem .35rem;border-radius:3px;background:#f3f4f6;color:#374151">'+esc(f.issue_type||'')+'</span></td>'+
            '<td><span class="sv '+esc(sev)+'" style="color:'+sc+'">'+esc(sev)+'</span></td>'+
            '<td style="white-space:nowrap">'+Math.round((f.confidence||0)*100)+'%</td>'+
            '<td style="font-size:.7rem;max-width:190px">'+esc(f.reasoning||'')+'</td>'+
            '<td style="font-size:.7rem">'+esc(f.suggested_action||'')+
              (f.suggested_target_field?'<br><span style="color:var(--ac);font-size:.65rem">&rarr; '+esc(f.suggested_target_field)+'</span>':'')+
            '</td>'+
          '</tr>';
        }).join('')+
        '</tbody></table></div>'+
        '<p style="font-size:.68rem;color:#888;margin-top:.3rem">'+findings.length+' Befunde &mdash; korrekte Zellen ausgeblendet</p>';
    }
  }

  // --- Column reports ---
  const colEl=$('llmq-col-content');
  if(colEl){
    const cols=report.column_reports||[];
    if(!cols.length){
      colEl.innerHTML='<p style="font-size:.8rem;color:#888;padding:.5rem">Keine Spalten-Berichte (Spalten-Ebene nicht aktiviert oder keine Daten).</p>';
    }else{
      colEl.innerHTML=
        '<table class="etbl"><thead><tr>'+
        '<th>Spalte</th><th>Feldreinheit</th><th>Konf.</th><th>Dominante Probleme</th><th>Begr\u00fcndung</th><th>Empfehlung</th>'+
        '</tr></thead><tbody>'+
        cols.map(c=>{
          const score=c.field_purity_score||0;
          const bar=Math.round(score*0.5);
          const col=score>70?'var(--ok)':score>40?'var(--warn)':'var(--crit)';
          return '<tr>'+
            '<td><code>'+esc(c.column)+'</code></td>'+
            '<td style="white-space:nowrap"><span class="fb0" style="width:'+bar+'px;background:'+col+'"></span>'+score.toFixed(0)+'%</td>'+
            '<td style="white-space:nowrap">'+Math.round((c.confidence||0)*100)+'%</td>'+
            '<td style="font-size:.7rem">'+esc((c.dominant_issue_types||[]).join(', '))+'</td>'+
            '<td style="font-size:.7rem;max-width:180px">'+esc(c.reasoning||'')+'</td>'+
            '<td style="font-size:.7rem">'+esc(c.suggested_action||'')+'</td>'+
          '</tr>';
        }).join('')+
        '</tbody></table>';
    }
  }

  // --- Record reports ---
  const recEl=$('llmq-rec-content');
  if(recEl){
    const recs=report.record_reports||[];
    if(!recs.length){
      recEl.innerHTML='<p style="font-size:.8rem;color:#888;padding:.5rem">Keine Record-Berichte (Record-Ebene nicht aktiviert oder keine Konflikte gefunden).</p>';
    }else{
      recEl.innerHTML=
        '<div class="scroll-box"><table class="etbl"><thead><tr>'+
        '<th>Record</th><th>Schwere</th><th>Konf.</th><th>Konflikte / Begr\u00fcndung</th><th>Review</th>'+
        '</tr></thead><tbody>'+
        recs.map(r=>{
          const sev=r.severity||'info';const sc=_SEV_COLORS[sev]||'#888';
          const conflictTxt=(r.conflicts||[]).map(c=>esc(typeof c==='string'?c:(c.description||JSON.stringify(c)))).join('; ')||esc(r.reasoning||'');
          return '<tr>'+
            '<td><code style="font-size:.68rem">'+esc(r.record_id)+'</code></td>'+
            '<td><span class="sv '+esc(sev)+'" style="color:'+sc+'">'+esc(sev)+'</span></td>'+
            '<td>'+Math.round((r.confidence||0)*100)+'%</td>'+
            '<td style="font-size:.7rem;max-width:260px">'+conflictTxt+'</td>'+
            '<td>'+(r.review_required?'<span style="color:var(--warn);font-weight:700">\u2713</span>':'&mdash;')+'</td>'+
          '</tr>';
        }).join('')+
        '</tbody></table></div>';
    }
  }

  // --- Dataset report ---
  const dsEl=$('llmq-ds-content');
  if(dsEl){
    const ds=report.dataset_report;
    if(!ds){
      dsEl.innerHTML='<p style="font-size:.8rem;color:#888;padding:.5rem">Kein Datensatz-Bericht (Datensatz-Ebene nicht aktiviert).</p>';
    }else{
      let html='';
      if(ds.risk_summary)html+='<div style="padding:.5rem .6rem;background:#fff8f0;border:1px solid var(--warn);border-radius:4px;font-size:.78rem;margin-bottom:.6rem"><strong>Risikobewertung:</strong> '+esc(ds.risk_summary)+'</div>';
      if((ds.dominant_error_families||[]).length)html+='<h4 style="font-size:.78rem;margin:.4rem 0 .2rem">Dominante Fehlerfamilien</h4><ul style="font-size:.75rem;margin-left:1.2rem;margin-bottom:.5rem">'+ds.dominant_error_families.map(e=>'<li>'+esc(e)+'</li>').join('')+'</ul>';
      if((ds.issue_clusters||[]).length)html+='<h4 style="font-size:.78rem;margin:.4rem 0 .2rem">Issue-Cluster</h4>'+
        ds.issue_clusters.map(cl=>'<div style="border:1px solid var(--brd);border-radius:4px;padding:.35rem .6rem;margin-bottom:.3rem;font-size:.75rem">'+
          '<strong>'+esc(cl.label||'Cluster')+'</strong>'+
          (cl.severity?' <span class="sv '+esc(cl.severity)+'" style="color:'+((_SEV_COLORS[cl.severity])||'#888')+'">'+esc(cl.severity)+'</span>':'')+
          (cl.count?' &mdash; '+cl.count+' Records':'')+
          (cl.suggested_action?'<div style="font-size:.7rem;color:var(--ac);margin-top:.12rem">&rarr; '+esc(cl.suggested_action)+'</div>':'')+
        '</div>').join('');
      if((ds.work_package_candidates||[]).length)html+='<h4 style="font-size:.78rem;margin:.4rem 0 .2rem">Arbeitspakete</h4>'+
        ds.work_package_candidates.map(wp=>'<div style="border:1px solid var(--brd);border-radius:4px;padding:.35rem .6rem;margin-bottom:.3rem;font-size:.75rem">'+
          '<div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap"><span style="font-weight:700;flex:1">'+esc(wp.title||'Arbeitspaket')+'</span>'+
          (wp.priority?'<span class="sv '+esc(wp.priority)+'" style="color:'+(_SEV_COLORS[wp.priority]||'#888')+'">'+esc(wp.priority)+'</span>':'')+
          (wp.estimated_records?'<span style="font-size:.68rem;color:#888">~'+wp.estimated_records+' Records</span>':'')+
          '</div>'+
          (wp.description?'<div style="font-size:.7rem;color:#555;margin-top:.12rem">'+esc(wp.description)+'</div>':'')+
        '</div>').join('');
      dsEl.innerHTML=html||'<p style="font-size:.8rem;color:#888">Keine strukturierten Daten im Datensatz-Bericht.</p>';
    }
  }

  // Re-bind inner tabs (needed after dynamic show)
  const innerTabs=$('llmq-tabs');
  if(innerTabs)bindTabs(innerTabs);
}

// === COMBINED COLUMNS TABLE (merged Profile + Spalten with sort) ===
let _colsData=[];
function rCombinedCols(ds){
  _colsData=ds;
  renderCols();
}
function sortCols(key,btn){
  if(colSortKey===key)colSortDir*=-1;
  else{colSortKey=key;colSortDir=(key==='name'?1:-1);}
  document.querySelectorAll('#col-sort-bar .fb2').forEach(x=>x.classList.remove('a'));
  if(btn)btn.classList.add('a');
  renderCols();
}
function renderCols(){
  const area=$('colsarea');if(!area)return;
  area.innerHTML=_colsData.map(d=>{
    let cols=[...(d.columns||[])];
    if(colSortKey==='fill') cols.sort((a,b)=>colSortDir*(b.fill_rate-a.fill_rate));
    else if(colSortKey==='unique') cols.sort((a,b)=>colSortDir*(b.unique_count-a.unique_count));
    else cols.sort((a,b)=>colSortDir*a.name.localeCompare(b.name,'de'));
    const idCol=d.id_column||'';
    const info='<p style="font-size:.73rem;color:#666;margin:.3rem 0">'+((d.row_count||0).toLocaleString())+' Zeilen · '+d.column_count+' Spalten · ID-Spalte: <code>'+esc(idCol||'—')+'</code></p>';
    const rows=cols.map(c=>{
      const sm=(c.sample_values||[]).slice(0,2).join(' / ');
      const fr=Math.round(c.fill_rate*100);
      return '<tr><td><strong>'+esc(c.name)+'</strong>'+(c.name===idCol?' <span style="font-size:.6rem;background:#dcfce7;color:var(--ok);padding:.05rem .3rem;border-radius:3px">ID</span>':'')+'</td>'+
        '<td><span class="fb0" style="width:'+Math.round(c.fill_rate*50)+'px;background:'+(c.fill_rate>.8?'var(--ok)':c.fill_rate>.3?'var(--warn)':'var(--crit)')+'"></span>'+fr+'%</td>'+
        '<td>'+(c.unique_count||0).toLocaleString()+'</td>'+
        '<td style="font-size:.7rem;color:#555">'+(fr<1?'Fast leer':fr+'% gefüllt')+'</td>'+
        '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.68rem">'+esc(sm.substring(0,60)||'—')+'</td></tr>';
    }).join('');
    return '<h3 style="margin:.6rem 0 .2rem">'+esc(d.source_name)+'</h3>'+info+
      '<table class="pt"><thead><tr><th>Spalte</th><th>Gefüllt</th><th>Unique</th><th>Beschreibung</th><th>Beispiel</th></tr></thead><tbody>'+rows+'</tbody></table>';
  }).join('');
}

// === ARBEITSPAKET ERSTELLEN ===
// Parse a CSV line into fields, correctly handling quoted fields and empty cells.
function _csvSplitLine(line){
  const out=[];const re=/("(?:[^"]|"")*"|[^,]*)(,|$)/g;let m;
  while((m=re.exec(line))!==null){out.push(m[1]);if(m[2]==='')break;}
  return out;
}
async function createArbeitspaket(){
  if(!curRep){alert('Erst Daten laden und Analyse starten.');return;}
  const ds=curRep.datasets||[];
  if(!ds.length){alert('Keine Datensätze geladen.');return;}
  // Use first dataset
  const d=ds[0];
  const dsName=d.source_name;
  const idCol=d.id_column||d.columns?.[0]?.name||'';
  const fullName=d.source_path||(Object.values(ufiles).find(f=>f.uploadName===dsName||f.uploadName.startsWith(dsName+'.'))||Object.values(ufiles).find(f=>f.uploadName.includes(dsName))||Object.values(ufiles)[0]||{uploadName:''}).uploadName;
  if(!fullName){alert('Datensatz nicht mehr verfügbar. Bitte Seite neu laden.');return;}
  sp('Arbeitspaket wird erstellt…','CSV Export');
  try{
    const r=await fetch('/api/export/csv',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({dataset:fullName,include_ner:true,include_edtf:true,include_gnd:false})});
    if(!r.ok){const e=await r.json();alert('Fehler: '+(e.error||r.statusText));hp();return;}
    const blob=await r.blob();
    const text=await blob.text();
    // Ensure record_id is first column
    const lines=text.split('\n');
    if(lines.length>0){
      const hdrs=_csvSplitLine(lines[0]);
      const idIdx=hdrs.findIndex(h=>h.replace(/^"|"$/g,'')===idCol);
      let out=text;
      if(idIdx>0){
        // Move id column to front using correct CSV tokenizer
        const reordered=lines.map(line=>{
          const cols=_csvSplitLine(line);
          if(cols.length>idIdx){const id=cols.splice(idIdx,1);cols.unshift(id[0]);}
          return cols.join(',');
        });
        out=reordered.join('\n');
      }
      dl(dsName+'_arbeitspaket.csv',out,'text/csv;charset=utf-8-sig');
    }else{dl(dsName+'_arbeitspaket.csv',text,'text/csv;charset=utf-8-sig');}
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}

// === ID COLUMN SELECTION ===
function showIdColBar(reportData){
  const bar=$('id-col-bar');
  const cont=$('id-col-datasets');
  if(!bar||!cont)return;
  const ds=reportData.datasets||[];
  if(!ds.length){bar.style.display='none';return;}
  bar.style.display='block';
  cont.innerHTML=ds.map(d=>{
    const cols=d.columns||[];
    const detected=d.id_column||'';
    const fname=d.source_path||(Object.values(ufiles).find(f=>f.uploadName===d.source_name||f.uploadName.startsWith(d.source_name+'.'))||Object.values(ufiles).find(f=>f.uploadName.includes(d.source_name))||{uploadName:''}).uploadName;
    return '<div class="id-col-row">'+
      '<strong style="min-width:140px;font-size:.75rem">'+esc(d.source_name)+':</strong>'+
      '<select id="idcol-'+esc(d.source_name)+'" style="min-width:200px">'+
        cols.map(c=>'<option value="'+esc(c.name)+'"'+(c.name===detected?' selected':'')+'>'+esc(c.name)+' ('+Math.round(c.fill_rate*100)+'%, '+c.unique_count+' unique)</option>').join('')+
      '</select>'+
      '<button class="btn sm" onclick="setIdCol(\''+esc(fname)+'\',\''+esc(d.source_name)+'\')">✓ Festlegen</button>'+
      '<span id="idcol-msg-'+esc(d.source_name)+'" style="font-size:.7rem;margin-left:.3rem"></span>'+
    '</div>';
  }).join('');
}
async function setIdCol(filename,sourceName){
  const sel=$('idcol-'+sourceName);
  if(!sel)return;
  const col=sel.value;
  const msg=$('idcol-msg-'+sourceName);
  try{
    const r=await fetch('/api/dataset/'+encodeURIComponent(filename)+'/set-id-column',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id_column:col})});
    const d=await r.json();
    if(d.error){if(msg)msg.textContent='Fehler: '+d.error;return;}
    if(msg){
      if(d.unique===false){msg.style.color='var(--warn)';msg.textContent='⚠ Nicht eindeutig ('+d.unique_count+' von '+d.total+')';}
      else{msg.style.color='var(--ok)';msg.textContent='✓ Festgelegt (eindeutig)';}
    }
    // Update report data
    if(curRep){curRep.datasets.forEach(ds=>{if(ds.source_name===sourceName)ds.id_column=col;});renderCols();}
  }catch(e){if(msg)msg.textContent='Fehler: '+e.message;}
}

// === GPU ===
async function chkGPU(){try{const d=await(await fetch('/api/gpu/status')).json();
    // Update both header and KI tab status indicators
    function setDot(cls,txt){
      $('gd').className='dot '+cls;$('gl').textContent=txt;
      if($('gd2'))$('gd2').className='dot '+cls;if($('gl2'))$('gl2').textContent=txt;
    }
    if(!d.configured){
      setDot('mock','Testdaten-Modus');
      $('gi').textContent='KI-Analyse verwendet Testdaten. F\u00fcr echte Ergebnisse: KWB_GPUSTACK_URL in .env konfigurieren.';
      if($('img-mock-hint'))$('img-mock-hint').style.display='block';
      if($('model-cards'))$('model-cards').innerHTML='<p style="font-size:.73rem;color:#888">Keine Modelle verfügbar (Mock-Modus).</p>';
    }else if(d.available){
      setDot('on','GPUStack: '+(d.models?.length||0)+' Modelle');
      gpuM=d.models||[];const cfg=d.config||{};
      $('gi').innerHTML='<span style="color:var(--ok);font-weight:600">Verbunden</span> — '+(gpuM.length)+' Modelle verfügbar';
      // Populate model dropdowns with type hints
      const textModels=gpuM.filter(m=>{const h=getModelHint(m);return h.type==='text'||h.type==='unknown';});
      const visionModels=gpuM.filter(m=>{const h=getModelHint(m);return h.type==='vision'||h.type==='unknown';});
      $('cfg-mt').innerHTML=gpuM.map(m=>{const h=getModelHint(m);return '<option value="'+esc(m)+'">'+esc(m)+(h.type!=='unknown'?' ['+h.type.toUpperCase()+']':'')+'</option>';}).join('');
      $('cfg-mv').innerHTML=gpuM.map(m=>{const h=getModelHint(m);return '<option value="'+esc(m)+'">'+esc(m)+(h.type!=='unknown'?' ['+h.type.toUpperCase()+']':'')+'</option>';}).join('');
      if($('llmq-model'))$('llmq-model').innerHTML='<option value="">Standard (aus Konfiguration)</option>'+gpuM.map(m=>{const h=getModelHint(m);return '<option value="'+esc(m)+'">'+esc(m)+(h.type!=='unknown'?' ['+h.type.toUpperCase()+']':'')+'</option>';}).join('');
      // Pre-select configured models
      if(cfg.gpustack_model_text)$('cfg-mt').value=cfg.gpustack_model_text;
      if(cfg.gpustack_model_vision)$('cfg-mv').value=cfg.gpustack_model_vision;
      $('cfg-models').textContent='Aktiv — Text: '+(cfg.gpustack_model_text||'—')+' / Vision: '+(cfg.gpustack_model_vision||'—');
      // Render model cards
      if($('model-cards')){
        $('model-cards').innerHTML=gpuM.map(m=>{
          const h=getModelHint(m);
          return '<div class="model-card"><span class="mc-type mc-'+h.type+'">'+esc(h.type)+'</span><strong style="flex:1">'+esc(m)+'</strong><span style="color:#888;font-size:.68rem">'+esc(h.hint)+'</span></div>';
        }).join('');
      }
      // Also populate image and PDF model dropdowns
      const visionOpts='<option value="">Standard (aus Konfiguration)</option>'+
        visionModels.map(m=>safeOpt(m,m+' [VISION]')).join('')+
        textModels.map(m=>safeOpt(m,m+' [TEXT]')).join('');
      if($('img-model'))$('img-model').innerHTML=visionOpts;
      if($('img-model-sidebar'))$('img-model-sidebar').innerHTML=visionOpts;
      if($('pdf-model'))$('pdf-model').innerHTML=visionOpts;
    }else{
      setDot('off','GPUStack: nicht erreichbar');
      $('gi').textContent='Verbindung fehlgeschlagen. URL/Key in .env prüfen. '+(d.message||'');
    }
  }catch(e){$('gd').className='dot off';$('gl').textContent='Verbindungsfehler';}}

// === NER helpers ===
function nerSelectAll(checked){
  document.querySelectorAll('#ner-cols .ci input[type=checkbox]').forEach(cb=>cb.checked=checked);
}

function fmtMetrics(m){
  if(!m)return '';
  const done=m.processed_rows||0,total=m.total_rows||0,err=(m.error_rate||0)*100;
  return 'Abarbeitung: '+done+'/'+total+' Zeilen · Fehlerquote: '+err.toFixed(2)+'% · ETA ~ '+(m.eta_seconds||0)+'s · Chunks: '+(m.chunk_count||0);
}
function renderRunMetrics(target,m){const el=$(target);if(el)el.textContent=fmtMetrics(m)}

async function runPilot(task){
  if(task==='ner'){
    const ds=$('ner-ds').value;if(!ds)return alert('Datensatz wählen');
    const cols=[...document.querySelectorAll('#ner-cols .ci input:checked')].map(c=>c.value);if(!cols.length)return alert('Mindestens eine Spalte wählen');
    await runNER(true);
  }
  if(task==='scan'){
    const ds=$('scan-ds').value;if(!ds)return alert('Datensatz wählen');
    await runScan(true);
  }
  if(task==='edtf'){
    const ds=$('edtf-ds').value,col=$('edtf-col').value;if(!ds||!col)return alert('Datensatz und Spalte wählen');
    await runEDTF(true);
  }
}

// === IMAGES ===
let uploadedImages = [];
let imgFilter = 'all';

function applyImgPreset(){
  const presetEl=$('img-preset'),spEl=$('img-sp');
  if(!presetEl||!spEl)return;
  const key=presetEl.value;
  if(key!=='custom')spEl.value=PRESETS[key]||'';
}

async function uploadImages(){
  const imgExts = /\.(jpg|jpeg|png|tif|tiff|webp)$/i;
  // Read from both Step 1 (p1) and Step 2 inputs — distinct IDs avoid conflicts
  const s1Files = [...(($('img-files-p1')&&$('img-files-p1').files) || [])];
  const s1Folder = [...(($('img-folder-p1')&&$('img-folder-p1').files) || [])].filter(f => imgExts.test(f.name));
  const s2Files = [...(($('img-files')&&$('img-files').files) || [])];
  const s2Folder = [...(($('img-folder')&&$('img-folder').files) || [])].filter(f => imgExts.test(f.name));
  const allFiles = [...s1Files, ...s1Folder, ...s2Files, ...s2Folder];
  if(!allFiles.length){alert('Keine Bilddateien gewählt.');return}
  const fd = new FormData();
  for(const f of allFiles) fd.append('files', f, f.webkitRelativePath || f.name);
  sp('Bilder werden hochgeladen…', allFiles.length + ' Datei(en)');
  try{
    const r = await fetch('/api/images/upload',{method:'POST',body:fd});
    const data = await r.json();
    if(data.error){$('img-upload-status').textContent='Fehler: '+data.error;hp();return}
    uploadedImages = data.images || [];
    $('img-upload-status').textContent = data.uploaded + ' Bild(er) hochgeladen.';
    renderImgGrid();
    _refreshImgPane1();
    hp();
  }catch(e){$('img-upload-status').textContent='Fehler: '+e;hp();}
}

function _refreshImgPane1(){
  const info=$('img-pane1-info');const cnt=$('img-pane1-count');const list=$('img-pane1-list');
  if(!info)return;
  if(!uploadedImages.length){info.style.display='none';return;}
  info.style.display='block';
  if(cnt)cnt.textContent='('+uploadedImages.length+')';
  if(list)list.innerHTML=uploadedImages.slice(0,50).map(img=>
    '<div class="pdf-page-item">'+
    '<span class="pdf-page-num" style="background:var(--ac)">IMG</span>'+
    '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.73rem">'+esc(img.filename||img.id)+'</span>'+
    '<span style="color:#888;font-size:.65rem">'+(img.width&&img.height?img.width+'×'+img.height:'')+'</span>'+
    '</div>'
  ).join('')+(uploadedImages.length>50?'<div style="font-size:.7rem;color:#888;padding:.3rem .4rem">…+'+(uploadedImages.length-50)+' weitere</div>':'');
}

function _imgHashCounts(){
  const m = {};
  uploadedImages.forEach(img=>{
    const h = img.hash_sha256 || '';
    if(!h) return;
    m[h] = (m[h] || 0) + 1;
  });
  return m;
}

function setImgFilter(filter, btn){
  imgFilter = filter || 'all';
  document.querySelectorAll('#img-filters .fb2').forEach(x=>x.classList.remove('a'));
  if(btn) btn.classList.add('a');
  renderImgGrid();
}

function _filteredImages(){
  const hc = _imgHashCounts();
  if(imgFilter === 'tiny') return uploadedImages.filter(img=>{
    const w = Number(img.width || 0), h = Number(img.height || 0);
    return !!(w && h) && (w <= 256 || h <= 256);
  });
  if(imgFilter === 'dup') return uploadedImages.filter(img=>{
    const h = img.hash_sha256 || '';
    return !!h && (hc[h] || 0) > 1;
  });
  if(imgFilter === 'no_analysis') return uploadedImages.filter(img=>!img.analyzed);
  if(['pending','accepted','rejected'].includes(imgFilter))
    return uploadedImages.filter(img=>(img.review_status||'pending')===imgFilter);
  return uploadedImages;
}

function renderImgGrid(){
  const gallery = $('img-gallery');
  const empty = $('img-list-empty');
  if(!gallery) return;
  if(!uploadedImages.length){
    if(empty){empty.style.display='block';empty.textContent='Noch keine Bilder hochgeladen.';}
    gallery.innerHTML='';
    _updateGalleryStatusBar(0,0);
    return;
  }
  const shown = _filteredImages();
  if(!shown.length){
    if(empty){empty.style.display='block';empty.textContent='Keine Bilder für den gewählten Filter.';}
    gallery.innerHTML='';
    _updateGalleryStatusBar(0,uploadedImages.length);
    return;
  }
  if(empty) empty.style.display='none';
  gallery.innerHTML = shown.map(function(img){
    const imgUrl='/api/images/'+encPath(img.id)+'/data';
    const isTiff=(img.media_type||'').includes('tiff');
    const status=img.review_status||'pending';
    const thumbHtml=isTiff
      ?'<div class="it-tiff">TIFF</div>'
      :'<img class="it-thumb" src="'+esc(imgUrl)+'" alt="'+esc(img.filename||'')+'" loading="lazy">';
    const badgeCls=status==='accepted'?'it-badge-accepted':status==='rejected'?'it-badge-rejected':'it-badge-pending';
    const badgeTxt=status==='accepted'?'✓':status==='rejected'?'✗':'·';
    return '<div class="img-tile" data-id="'+esc(img.id)+'" onclick="openImgDetail(\''+esc(img.id)+'\')">'
      +thumbHtml
      +'<div class="it-badge '+badgeCls+'">'+badgeTxt+'</div>'
      +(img.analyzed?'<div class="it-analyzed-dot" title="Analysiert"></div>':'')
      +'<div class="it-name" title="'+esc(img.filename||img.id)+'">'+esc(img.filename||img.id)+'</div>'
      +'<div class="it-actions">'
      +'<button class="btn sm" onclick="event.stopPropagation();quickReview(\''+esc(img.id)+'\',\'accepted\')" title="Freigeben">&#10003;</button>'
      +'<button class="btn sm s" onclick="event.stopPropagation();quickReview(\''+esc(img.id)+'\',\'rejected\')" title="Verwerfen">&#10007;</button>'
      +'</div>'
      +'</div>';
  }).join('');
  // Error fallback for broken img tags
  gallery.querySelectorAll('.it-thumb').forEach(function(el){
    el.onerror=function(){this.style.display='none';
      var fb=document.createElement('div');fb.className='it-tiff';fb.textContent='n/v';
      this.parentNode.insertBefore(fb,this);};
  });
  _updateGalleryStatusBar(shown.length,uploadedImages.length);
}

function _updateGalleryStatusBar(shown, total){
  const cnt=$('img-gallery-count');
  const an=$('img-gallery-analyzed');
  if(cnt) cnt.textContent=total?shown+' / '+total+' Bilder':'';
  if(an){
    const analyzed=uploadedImages.filter(i=>i.analyzed).length;
    an.textContent=total?analyzed+' analysiert':'';
  }
}

function setGalleryDensity(size){
  const gallery=$('img-gallery');
  if(!gallery) return;
  gallery.className='img-gallery ig-'+size;
  ['s','m','l'].forEach(function(s){
    const btn=$('igd-'+s);
    if(btn) btn.classList.toggle('active',s===size);
  });
}

function openImgDetail(imageId){
  const img=uploadedImages.find(i=>i.id===imageId);
  if(!img) return;
  const panel=$('img-detail-panel');
  const mainEl=$('ig-main');
  if(!panel) return;
  // Highlight tile
  document.querySelectorAll('.img-tile').forEach(t=>t.classList.remove('selected'));
  const tile=document.querySelector('.img-tile[data-id="'+CSS.escape(imageId)+'"]');
  if(tile){tile.classList.add('selected');tile.scrollIntoView({block:'nearest'});}
  // Header
  const nm=$('img-detail-name');if(nm) nm.textContent=img.filename||img.id;
  // Preview
  const preview=$('img-detail-preview');
  if(preview){
    const isTiff=(img.media_type||'').includes('tiff');
    const imgUrl='/api/images/'+encPath(img.id)+'/data';
    preview.innerHTML=isTiff
      ?'<div style="background:var(--pw);padding:1.5rem;border-radius:var(--r);color:#888;font-size:.8rem">TIFF – Klick öffnet Vollbild</div>'
      :'<img src="'+esc(imgUrl)+'" style="max-width:100%;max-height:160px;object-fit:contain;border-radius:4px;cursor:pointer" '
        +'onclick="openLightbox(\''+esc(imgUrl)+'\',\''+esc(img.filename||img.id)+'\')" '
        +'onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{textContent:\'Vorschau n/v\',style:\'padding:.8rem;color:#aaa;font-size:.75rem\'}))">';
  }
  // Body
  const body=$('img-detail-body');
  if(!body) return;
  const r=img.result||{};
  const status=img.review_status||'pending';
  const stCls=status==='accepted'?'rev-st-accepted':status==='rejected'?'rev-st-rejected':'rev-st-pending';
  body.innerHTML=
    '<div style="margin-bottom:.5rem">'
    +'<table style="font-size:.72rem;width:100%;border-collapse:collapse">'
    +'<tr><td style="color:#888;padding:.1rem .4rem 0 0;white-space:nowrap">Status:</td><td><span class="rev-st '+stCls+'">'+esc(status)+'</span></td></tr>'
    +'<tr><td style="color:#888;padding:.1rem .4rem 0 0">Größe:</td><td>'+(img.width||'?')+'×'+(img.height||'?')+' px</td></tr>'
    +(img.size_bytes?'<tr><td style="color:#888;padding:.1rem .4rem 0 0">Datei:</td><td>'+((img.size_bytes/1024).toFixed(1))+' KB · '+esc(img.media_type||'')+'</td></tr>':'')
    +'</table>'
    +'</div>'
    +(img.analyzed&&(r.description||r.objects)
      ?'<div class="c" style="margin-bottom:.5rem;padding:.5rem">'
        +'<h3 style="font-size:.78rem;margin-bottom:.3rem">KI-Analyse</h3>'
        +(r.description?'<p style="font-size:.75rem;margin-bottom:.25rem">'+esc(r.description)+'</p>':'')
        +(r.objects&&r.objects.length?'<p style="font-size:.72rem"><strong>Objekte:</strong> '+esc(r.objects.join(', '))+'</p>':'')
        +(r.period?'<p style="font-size:.72rem"><strong>Periode:</strong> '+esc(r.period)+'</p>':'')
        +(r.confidence?'<p style="font-size:.68rem;color:#888;margin-top:.15rem">Konfidenz: '+(r.confidence*100).toFixed(0)+'%</p>':'')
        +'</div>'
      :'')
    +'<div class="c" style="padding:.5rem">'
    +'<h3 style="font-size:.78rem;margin-bottom:.4rem">Review</h3>'
    +'<input type="text" id="img-detail-record" placeholder="record_id (optional)" value="'+esc(img.record_id||'')+'" style="width:100%;margin-bottom:.3rem">'
    +'<textarea id="img-detail-desc" style="width:100%;height:3rem;margin-bottom:.3rem">'+esc(r.description||'')+'</textarea>'
    +'<input type="text" id="img-detail-comment" placeholder="Kommentar" value="'+esc(img.review_comment||'')+'" style="width:100%;margin-bottom:.3rem">'
    +'<input type="text" id="img-detail-reviewer" placeholder="Reviewer" value="'+esc(img.reviewer||'')+'" style="width:100%;margin-bottom:.4rem">'
    +'<div style="display:flex;gap:.3rem;flex-wrap:wrap">'
    +'<button class="btn sm" onclick="saveDetailReview(\''+esc(img.id)+'\',\'pending\')">&#128190; Speichern</button>'
    +'<button class="btn sm" style="background:var(--ok)" onclick="saveDetailReview(\''+esc(img.id)+'\',\'accepted\')">&#10003; Best&auml;tigen</button>'
    +'<button class="btn sm s" onclick="saveDetailReview(\''+esc(img.id)+'\',\'rejected\')">&#10007; Verwerfen</button>'
    +'</div>'
    +'</div>';
  panel.classList.add('open');
  if(mainEl) mainEl.classList.add('has-detail');
}

function closeImgDetail(){
  const panel=$('img-detail-panel');
  if(panel) panel.classList.remove('open');
  const mainEl=$('ig-main');if(mainEl) mainEl.classList.remove('has-detail');
  document.querySelectorAll('.img-tile').forEach(t=>t.classList.remove('selected'));
}

async function saveDetailReview(imageId, forceStatus){
  const img=uploadedImages.find(i=>i.id===imageId);
  if(!img) return;
  const payload={
    status:forceStatus,
    record_id:($('img-detail-record')&&$('img-detail-record').value)||img.record_id||'',
    comment:($('img-detail-comment')&&$('img-detail-comment').value)||'',
    reviewer:($('img-detail-reviewer')&&$('img-detail-reviewer').value)||'',
    result_updates:{description:($('img-detail-desc')&&$('img-detail-desc').value)||''}
  };
  try{
    const resp=await fetch('/api/images/'+encodeURIComponent(imageId)+'/review',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)
    });
    const d=await resp.json();
    if(d.error){alert('Review-Fehler: '+d.error);return;}
    img.review_status=d.image.review_status;
    img.review_comment=d.image.review_comment;
    img.reviewer=d.image.reviewer;
    img.record_id=d.image.record_id;
    if(d.image.result) img.result=d.image.result;
    renderImgGrid();
    openImgDetail(imageId);
  }catch(e){alert('Review-Fehler: '+e.message);}
}

async function quickReview(imageId, status){
  const img=uploadedImages.find(i=>i.id===imageId);
  if(!img) return;
  try{
    const resp=await fetch('/api/images/'+encodeURIComponent(imageId)+'/review',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({status,reviewer:'',comment:'',record_id:img.record_id||''})
    });
    const d=await resp.json();
    if(d.error) return;
    img.review_status=d.image.review_status;
    renderImgGrid();
  }catch(e){}
}

async function analyzeImages(){
  if(!uploadedImages.length){alert('Erst Bilder hochladen.');return}
  const mod=($('img-model-sidebar')&&$('img-model-sidebar').value)||($('img-model')&&$('img-model').value)||'';
  const sp_text=($('img-sp')&&$('img-sp').value)||'';
  const task=($('img-task-sidebar')&&$('img-task-sidebar').value)||($('img-task')&&$('img-task').value)||'image_description';
  const ids = uploadedImages.map(i=>i.id);
  sp('Bildanalyse läuft…', ids.length + ' Bild(er)');
  const boolParams=getBoolParams();
  const body={image_ids:ids, model:mod, system_prompt:sp_text, prompt_task:task, boolean_params:boolParams};
  try{
    await fetchSSE('/api/images/analyze/stream',body,
      evt=>{spUp(evt.current,evt.total,esc(evt.filename||''));},
      result=>{
        renderImgResults(result.results||[]);
        renderImgGrid();
      },
      msg=>{ const el=$('img-full-status');if(el)el.textContent='Fehler: '+msg; }
    );
  }catch(e){
    if(e.name!=='AbortError'){const el=$('img-full-status');if(el)el.textContent='Fehler: '+e;}
  }finally{hp();}
}

function renderImgResults(results){
  latestImageResults = results || [];
  // Merge analysis results into uploadedImages and re-render gallery
  results.forEach(function(res){
    var img=uploadedImages.find(i=>i.id===res.id);
    if(img){
      if(res.result) img.result=res.result;
      if(res.review_status) img.review_status=res.review_status;
      if(res.review_comment) img.review_comment=res.review_comment;
      if(res.reviewer) img.reviewer=res.reviewer;
      if(res.record_id) img.record_id=res.record_id;
      img.analyzed=true;
    }
  });
  renderImgGrid();
}

function applyImageFilter(){
  renderImgGrid();
}

async function saveImageReview(idx, forceStatus){
  const item = filteredImageResults[idx];
  if(!item)return;
  const payload={
    status:forceStatus || $('img-status-'+idx).value,
    record_id:$('img-record-'+idx).value,
    comment:$('img-comment-'+idx).value,
    reviewer:$('img-reviewer-'+idx).value,
    result_updates:{description:$('img-desc-'+idx).value}
  };
  try{
    const r=await fetch('/api/images/'+encodeURIComponent(item.id)+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){alert('Review-Fehler: '+d.error);return;}
    item.review_status=d.image.review_status;
    item.review_comment=d.image.review_comment;
    item.reviewer=d.image.reviewer;
    item.record_id=d.image.record_id;
    item.result=d.image.result;
    applyImageFilter();
  }catch(e){alert('Review-Fehler: '+e.message);}
}
async function reviewImage(imageId,status){
  try{
    const r=await fetch('/api/images/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_id:imageId,status})});
    const d=await r.json();
    if(d.error){alert(d.error);return}
    await refreshReviewStats();
  }catch(e){alert('Review-Fehler: '+e.message)}
}

async function refreshReviewStats(){
  try{
    const ws=await (await fetch('/api/workspace')).json();
    const rs=ws.image_review||{};
    if($('img-review-stats'))$('img-review-stats').textContent='Pending: '+(rs.pending||0)+' · Freigegeben: '+(rs.approved||0)+' · Abgelehnt: '+(rs.rejected||0);
    const list=(uploadedImages||[]).map(img=>'<div class="rev-pending" style="font-size:.74rem;margin:.2rem 0">'+esc(img.filename||img.id)+' <button class="btn sm" onclick="reviewImage(\''+esc(img.id)+'\',\'approved\')">✓</button> <button class="btn sm s" onclick="reviewImage(\''+esc(img.id)+'\',\'rejected\')">✗</button></div>').join('');
    if($('img-review-list'))$('img-review-list').innerHTML=list||'<span style="font-size:.72rem;color:#888">Keine Vorschläge.</span>';
  }catch(e){}
}


// === WIKIDATA ===
async function runWikidataLookup(){
  sp('Wikidata-Suche …','SPARQL');
  try{
    const r=await(await fetch('/api/wikidata/batch',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({limit:20,lang:'de'})})).json();
    if(r.error){alert('Wikidata-Fehler: '+r.error);hp();return;}
    alert('Wikidata: '+(r.matched||0)+' von '+(r.total||0)+' Entitäten gefunden und im Wörterbuch gespeichert.');
    updWS();
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}



async function bulkReviewVisible(status){
  const ids=filteredImageResults.filter(x=>!x.error).map(x=>x.id);
  if(!confirm('Bulk-Review für '+ids.length+' sichtbare Ergebnisse ausführen?')) return;
  if(!ids.length){alert('Keine sichtbaren Ergebnisse.');return;}
  try{
    const r=await fetch('/api/images/review/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      image_ids:ids,
      status:status,
      reviewer:$('img-bulk-reviewer')?$('img-bulk-reviewer').value:'',
      comment:$('img-bulk-comment')?$('img-bulk-comment').value:''
    })});
    const d=await r.json();
    if(d.error){alert('Bulk-Review-Fehler: '+d.error);return;}
    latestImageResults.forEach(function(item){
      if(ids.includes(item.id)){
        item.review_status=status;
        if($('img-bulk-reviewer') && $('img-bulk-reviewer').value) item.reviewer=$('img-bulk-reviewer').value;
        if($('img-bulk-comment') && $('img-bulk-comment').value) item.review_comment=$('img-bulk-comment').value;
      }
    });
    applyImageFilter();
  }catch(e){alert('Bulk-Review-Fehler: '+e.message);}
}

async function loadImages(){
  try{
    const r=await fetch('/api/images');
    const d=await r.json();
    uploadedImages=d.images||[];
    renderImgGrid();
    const reviewed=uploadedImages.filter(i=>i.result).map(i=>({
      id:i.id,filename:i.filename,result:i.result,record_id:i.record_id||'',
      review_status:i.review_status||'pending',review_comment:i.review_comment||'',
      reviewer:i.reviewer||''
    }));
    if(reviewed.length) renderImgResults(reviewed);
  }catch(e){}
}

// === OCR ===
async function runOCR(){
  if(!uploadedImages.length){alert('Erst Bilder hochladen.');return;}
  const mod=($('img-model-sidebar')&&$('img-model-sidebar').value)||($('img-model')&&$('img-model').value)||'';
  const ids=uploadedImages.map(i=>i.id);
  sp('OCR läuft…',ids.length+' Bild(er)');
  _abortCtrl=new AbortController();
  const statusEl=$('img-full-status');
  try{
    const r=await fetch('/api/images/ocr',{
      method:'POST',headers:{'Content-Type':'application/json'},
      signal:_abortCtrl.signal,
      body:JSON.stringify({image_ids:ids,model:mod,system_prompt:($('ocr-sp')&&$('ocr-sp').value)||''})
    });
    const data=await r.json();
    if(data.error){if(statusEl)statusEl.textContent='OCR-Fehler: '+data.error;hp();return;}
    // Merge OCR results into uploadedImages
    (data.results||[]).forEach(function(res){
      const img=uploadedImages.find(i=>i.id===res.id);
      if(img&&res.result){img.result=res.result;img.analyzed=true;}
    });
    renderImgGrid();
    if(statusEl)statusEl.textContent='OCR abgeschlossen: '+(data.processed||0)+'/'+(data.total||0)+' Bilder';
  }catch(e){if(statusEl)statusEl.textContent='Fehler: '+e;}finally{hp();}
}

// === CSV EXPORT ===
async function exportCSV(){
  const ds=($('exp-csv-ds')&&$('exp-csv-ds').value)||($('exp-ds')&&$('exp-ds').value)||'';
  if(!ds){alert('Datensatz wählen');return;}
  sp('CSV Export …','');
  try{
    const r=await fetch('/api/export/csv',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        dataset:ds,
        include_ner:$('exp-csv-ner')?$('exp-csv-ner').checked:true,
        include_edtf:$('exp-csv-edtf')?$('exp-csv-edtf').checked:true,
        include_gnd:$('exp-csv-gnd')?$('exp-csv-gnd').checked:true,
      })});
    if(!r.ok){var e=await r.json();alert('Fehler: '+(e.error||r.statusText));hp();return;}
    var blob=await r.blob();
    dl(ds+'_enriched.csv',await blob.text(),'text/csv;charset=utf-8-sig');
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}

// === JSON-LD EXPORT ===
async function exportImageResults(format){
  sp('Bildresultate Export …','');
  try{
    const st=($('exp-img-status')&&$('exp-img-status').value)||'';
    const r=await fetch('/api/export/image-results',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({format:format,review_status:st,as_file:true})});
    if(!r.ok){var e=await r.json();alert('Fehler: '+(e.error||r.statusText));hp();return;}
    var blob=await r.blob();
    if(format==='jsonld') dl('image_results.jsonld',await blob.text(),'application/ld+json');
    else dl('image_results.csv',await blob.text(),'text/csv;charset=utf-8-sig');
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}

async function exportJSONLD(){
  const ds=($('exp-ld-ds')&&$('exp-ld-ds').value)||($('exp-ds')&&$('exp-ds').value)||'';
  if(!ds){alert('Datensatz wählen');return;}
  var url=($('exp-ld-url')&&$('exp-ld-url').value)||'https://example.org/collection/';
  sp('JSON-LD Export …','');
  try{
    const r=await fetch('/api/export/jsonld',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({dataset:ds,base_url:url,as_file:true,limit:10000})});
    if(!r.ok){var e=await r.json();alert('Fehler: '+(e.error||r.statusText));hp();return;}
    var blob=await r.blob();
    dl(ds+'.jsonld',await blob.text(),'application/ld+json');
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
}

// === LIGHTBOX (Feature 8) ===
let lbRotation=0,lbZoom=1;
function openLightbox(imgSrc,info){
  const lb=$('lightbox'),img=$('lightbox-img');
  img.src=imgSrc;lbRotation=0;lbZoom=1;
  img.style.transform='';
  $('lightbox-info').textContent=info||'';
  lb.classList.add('a');
  document.addEventListener('keydown',lbKeyHandler);
}
function closeLightbox(){$('lightbox').classList.remove('a');document.removeEventListener('keydown',lbKeyHandler)}
function lbKeyHandler(e){if(e.key==='Escape')closeLightbox();if(e.key==='+')zoomLightbox(1.2);if(e.key==='-')zoomLightbox(0.8)}
function rotateLightbox(deg){lbRotation=(lbRotation+deg)%360;applyLbTransform()}
function zoomLightbox(factor){lbZoom=Math.max(0.1,Math.min(10,lbZoom*factor));applyLbTransform()}
function resetLightbox(){lbRotation=0;lbZoom=1;applyLbTransform()}
function applyLbTransform(){$('lightbox-img').style.transform='rotate('+lbRotation+'deg) scale('+lbZoom+')'}

// === AUTH (Feature 6) ===
let authToken='';
function showLogin(){$('login-overlay').classList.add('a');$('login-user').focus()}
async function doLogin(){
  const u=$('login-user').value.trim(),p=$('login-pw').value;
  if(!u||!p){$('login-err').textContent='Bitte ausfüllen';$('login-err').style.display='block';return}
  try{const r=await(await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})})).json();
    if(r.error){$('login-err').textContent=r.error;$('login-err').style.display='block';return}
    authToken=r.token;$('login-overlay').classList.remove('a');
    $('user-info').textContent='👤 '+esc(r.display_name||r.username);
    $('login-btn').style.display='none';$('logout-btn').style.display='';
  }catch(e){$('login-err').textContent=e.message;$('login-err').style.display='block';}
}
async function doLogout(){
  try{await fetch('/api/auth/logout',{method:'POST',headers:{'Authorization':'Bearer '+authToken}})}catch(e){}
  authToken='';$('user-info').textContent='';$('login-btn').style.display='';$('logout-btn').style.display='none';
}
async function checkAuth(){
  try{const r=await(await fetch('/api/auth/me')).json();
    if(r.username){$('user-info').textContent='👤 '+esc(r.display_name||r.username);$('login-btn').style.display='none';$('logout-btn').style.display='';}
  }catch(e){}
}

// === DICTIONARY (Features 1-3, 10-11) ===
let dictData=[];
async function loadDictEntries(){
  const t=$('dict-type-filter').value;
  try{const r=await(await fetch('/api/dictionary'+(t?'?entity_type='+encodeURIComponent(t):''))).json();
    dictData=r.entries||[];renderDictList();
    $('dict-count').textContent='('+dictData.length+(t?' '+t:'')+')';
  }catch(e){console.error(e)}
}
function renderDictList(){
  if(!dictData.length){$('dict-list-empty').style.display='block';$('dict-list').innerHTML='';return}
  $('dict-list-empty').style.display='none';
  $('dict-list').innerHTML=dictData.map((e,i)=>{
    const auth=e.gnd_id?'GND:'+esc(e.gnd_id):'';
    const wk=e.wikidata_id?'WD:'+esc(e.wikidata_id):'';
    const rids=e.record_ids?e.record_ids.slice(0,3).join(', ')+(e.record_ids.length>3?' +'+( e.record_ids.length-3):''):'';
    return '<div class="dict-entry" onclick="showDictDetail(\''+esc(e.entry_id)+'\')">'
      +'<span class="dict-type dict-type-'+(e.entity_type||'other')+'">'+esc(e.entity_type||'?')+'</span>'
      +'<span class="dict-term">'+esc(e.term)+(e.preferred_name?' → <em>'+esc(e.preferred_name)+'</em>':'')+'</span>'
      +(auth?'<span class="dict-auth">'+auth+'</span>':'')
      +(wk?'<span class="dict-auth">'+wk+'</span>':'')
      +(rids?'<span class="dict-rids">'+esc(rids)+'</span>':'')
      +'</div>';
  }).join('');
}
async function loadDictTypes(){
  try{const r=await(await fetch('/api/dictionary/types')).json();
    $('dict-type-counts').innerHTML=(r.types||[]).map(t=>'<span class="dict-type dict-type-'+esc(t.type)+'">'+esc(t.label)+': '+t.count+'</span> ').join('');
  }catch(e){}
}
async function addDictEntry(){
  const term=$('dict-new-term').value.trim();if(!term){alert('Begriff eingeben');return}
  const body={term,entity_type:$('dict-new-type').value,preferred_name:$('dict-new-preferred').value.trim()};
  try{const r=await(await fetch('/api/dictionary/entry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(r.error){alert(r.error);return}$('dict-new-term').value='';loadDictEntries();loadDictTypes();updWS();
  }catch(e){alert(e.message)}
}
async function buildDict(){
  const ds=$('dict-build-ds').value;if(!ds){alert('Datensatz wählen');return}
  const cols=[...document.querySelectorAll('#dict-build-cols .ci input:checked')].map(c=>c.value);
  if(!cols.length){alert('Spalten wählen');return}
  sp('Dictionary aufbauen …','');
  try{const r=await(await fetch('/api/dictionary/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset:ds,columns:cols,entity_type:$('dict-build-type').value})})).json();
    if(r.error){alert(r.error);return}loadDictEntries();loadDictTypes();updWS();alert(r.added+' neue Einträge hinzugefügt.');
  }catch(e){alert(e.message)}finally{hp()}
}
async function nerToDict(){
  sp('NER → Wörterbuch …','');
  try{const r=await(await fetch('/api/dictionary/from-ner',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:'accepted'})})).json();
    if(r.error){alert(r.error);return}loadDictEntries();loadDictTypes();updWS();alert(r.added+' Einträge übernommen.');
  }catch(e){alert(e.message)}finally{hp()}
}
async function ocrToDict(){
  sp('OCR → NER (Review-Queue) …','');
  try{const r=await(await fetch('/api/dictionary/from-ocr',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('cfg-mt').value||''})})).json();
    if(r.error){alert(r.error);return}loadDictEntries();loadDictTypes();updWS();loadPipelineStatus();
    alert('OCR: '+r.ocr_texts_processed+' Texte → '+r.entities_found+' Entities in Review-Queue.'
      +(r.skipped_pending?' ('+r.skipped_pending+' ungeprüft übersprungen)':'')
      +'\nNächster Schritt: Entities im NER-Tab prüfen, dann "NER → Wörterbuch".');
  }catch(e){alert(e.message)}finally{hp()}
}
async function showDictDetail(entryId){
  const entry=dictData.find(e=>e.entry_id===entryId);if(!entry)return;
  if(!$('dict-detail')){
    // Create detail panel if missing
    const panel=document.createElement('div');panel.id='dict-detail';panel.className='c';panel.style.marginTop='1rem';
    panel.innerHTML='<div id="dict-detail-content"></div>';
    const list=$('dict-list');if(list&&list.parentElement)list.parentElement.appendChild(panel);else return;
  }
  $('dict-detail').style.display='block';
  $('dict-detail-content').innerHTML=
    '<div style="font-size:.78rem">'
    +'<strong>'+esc(entry.term)+'</strong> <span class="dict-type dict-type-'+(entry.entity_type||'other')+'">'+esc(entry.entity_type||'?')+'</span>'
    +'<br>ID: <code>'+esc(entry.entry_id)+'</code>'
    +(entry.preferred_name?'<br>Vorzugsbenennung: <em>'+esc(entry.preferred_name)+'</em>':'')
    +(entry.alternatives&&entry.alternatives.length?'<br>Schreibweisen: '+entry.alternatives.map(a=>esc(a)).join(', '):'')
    +(entry.record_ids&&entry.record_ids.length?'<br>Records ('+entry.record_ids.length+'): '+entry.record_ids.slice(0,10).map(r=>esc(r)).join(', ')+(entry.record_ids.length>10?' …':''):'')
    +'<br>Quelle: '+esc(entry.source||'—')
    +'<hr style="border:none;border-top:1px solid var(--brd);margin:.4rem 0">'
    +'<strong>Normdaten:</strong>'
    +(entry.gnd_id?'<br>GND: <a href="https://d-nb.info/gnd/'+esc(entry.gnd_id)+'" target="_blank">'+esc(entry.gnd_id)+'</a> '+esc(entry.gnd_preferred||''):'<br>GND: —')
    +(entry.wikidata_id?'<br>Wikidata: <a href="https://www.wikidata.org/wiki/'+esc(entry.wikidata_id)+'" target="_blank">'+esc(entry.wikidata_id)+'</a>':'')
    +(entry.geonames_id?'<br>GeoNames: <a href="'+esc(entry.geonames_uri||('https://www.geonames.org/'+entry.geonames_id))+'" target="_blank" rel="noopener">'+esc(entry.geonames_id)+'</a>'+(entry.geonames_preferred?' '+esc(entry.geonames_preferred):'')+(entry.geonames_type?' <span style="font-size:.7rem;color:#666">['+esc(entry.geonames_type)+']</span>':''):'')
    +'<hr style="border:none;border-top:1px solid var(--brd);margin:.4rem 0">'
    +'<div style="display:flex;gap:.3rem;flex-wrap:wrap">'
    +'<button class="btn sm" onclick="enrichDictGND(\''+esc(entryId)+'\',\''+esc(entry.term)+'\')">🔍 GND suchen</button>'
    +'<button class="btn sm" onclick="enrichDictWikidata(\''+esc(entryId)+'\',\''+esc(entry.term)+'\')">🌐 Wikidata suchen</button>'
    +'<button class="btn sm s" style="background:var(--crit)" onclick="deleteDictEntry(\''+esc(entryId)+'\')">🗑 Löschen</button>'
    +'</div><div id="dict-enrich-results" style="margin-top:.4rem;font-size:.73rem"></div></div>';
}
async function enrichDictGND(entryId,term){
  try{const r=await(await fetch('/api/gnd/search?term='+encodeURIComponent(term))).json();
    if(!r.results||!r.results.length){$('dict-enrich-results').innerHTML='<em>Keine GND-Treffer.</em>';return}
    $('dict-enrich-results').innerHTML='<strong>GND-Treffer:</strong><br>'+r.results.slice(0,5).map(g=>
      '<div style="padding:.2rem 0;cursor:pointer" onclick="applyGNDToDict(\''+esc(entryId)+'\',\''+esc(g.gnd_id)+'\',\''+esc(g.preferred_name||'')+'\',\''+esc(g.type||'')+'\',\''+esc(g.uri||'')+'\')">'
      +'<span class="gnd-match">'+esc(g.gnd_id)+'</span> '+esc(g.preferred_name||g.label||'')+' <span style="color:#888;font-size:.68rem">('+esc(g.type||'')+')</span></div>'
    ).join('');
  }catch(e){$('dict-enrich-results').innerHTML='Fehler: '+esc(e.message)}
}
async function applyGNDToDict(entryId,gndId,preferred,gndType,uri){
  try{await fetch('/api/dictionary/enrich/'+entryId,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({gnd_id:gndId,gnd_preferred:preferred,gnd_type:gndType,gnd_uri:uri,source:'api'})});
    loadDictEntries();showDictDetail(entryId);
  }catch(e){alert(e.message)}
}
async function enrichDictWikidata(entryId,term){
  try{const r=await(await fetch('/api/wikidata/search?term='+encodeURIComponent(term))).json();
    if(!r.results||!r.results.length){$('dict-enrich-results').innerHTML='<em>Keine Wikidata-Treffer.</em>';return}
    $('dict-enrich-results').innerHTML='<strong>Wikidata-Treffer:</strong><br>'+r.results.slice(0,5).map(w=>
      '<div style="padding:.2rem 0;cursor:pointer" onclick="applyWDToDict(\''+esc(entryId)+'\',\''+esc(w.id||w.wikidata_id||'')+'\')">'
      +esc(w.id||w.wikidata_id||'')+' — '+esc(w.label||w.name||'')+'</div>'
    ).join('');
  }catch(e){$('dict-enrich-results').innerHTML='Fehler: '+esc(e.message)}
}
async function applyWDToDict(entryId,wdId){
  try{await fetch('/api/dictionary/enrich/'+entryId,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({wikidata_id:wdId,source:'api'})});
    loadDictEntries();showDictDetail(entryId);
  }catch(e){alert(e.message)}
}
async function deleteDictEntry(entryId){
  if(!confirm('Eintrag wirklich löschen?'))return;
  try{await fetch('/api/dictionary/entry/'+entryId,{method:'DELETE'});
    if($('dict-detail'))$('dict-detail').style.display='none';loadDictEntries();loadDictTypes();updWS();
  }catch(e){alert(e.message)}
}
function exportDict(entityType){
  window.open('/api/dictionary/export'+(entityType?'?entity_type='+encodeURIComponent(entityType):''),'_blank');
}
function exportDictTyped(){window.open('/api/dictionary/export-typed','_blank')}
function exportDictTarget(){window.open('/api/dictionary/export-target','_blank')}

// === PIPELINE STATUS ===
async function loadPipelineStatus(){
  try{
    const r=await(await fetch('/api/pipeline/status')).json();
    const el=$('pipeline-status');if(!el){return;}
    const s=r;
    function bar(label,done,total){
      const pct=total?Math.round(done/total*100):0;
      return '<span class="wsi" title="'+label+': '+done+'/'+total+'">'
        +label+': <strong>'+done+'/'+total+'</strong>'
        +'<span style="display:inline-block;width:40px;height:6px;background:#e0e0e0;border-radius:3px;vertical-align:middle;margin-left:.3rem">'
        +'<span style="display:block;height:100%;width:'+pct+'%;background:var(--pri);border-radius:3px"></span></span></span>';
    }
    el.innerHTML=bar('OCR',s.phase1_ocr.accepted,s.phase1_ocr.total)
      +bar('NER',s.phase2_ner.accepted,s.phase2_ner.total)
      +bar('Authority',s.phase3_authority.accepted,s.phase3_authority.total)
      +'<span class="wsi">Dict: <strong>'+s.dictionary.enriched+'/'+s.dictionary.total+' angereichert</strong></span>';
  }catch(e){console.error('[pipeline-status]',e)}
}

// === OCR REVIEW GATE ===
async function ocrSpotCheck(){
  sp('Stichprobe laden …','');
  try{
    const r=await(await fetch('/api/images/review/sample',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sample_size:10,strategy:'low_confidence'})})).json();
    alert('Stichprobe: '+r.sample_size+' von '+r.total_pending+' ausstehend. Prüfen Sie die Ergebnisse im Bilder-Tab.');
    loadImages();
  }catch(e){alert(e.message)}finally{hp()}
}
async function ocrAutoAccept(){
  const conf=parseFloat(prompt('Minimale Konfidenz (0.0-1.0):','0.85'));
  if(isNaN(conf))return;
  sp('Auto-Accept …','');
  try{
    const r=await(await fetch('/api/images/review/auto-accept',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({min_confidence:conf})})).json();
    alert(r.auto_accepted+' akzeptiert, '+r.remaining_pending+' noch ausstehend.');
    loadImages();loadPipelineStatus();
  }catch(e){alert(e.message)}finally{hp()}
}

// === NER REVIEW GATE ===
async function nerSpotCheck(){
  sp('NER-Stichprobe …','');
  try{
    const r=await(await fetch('/api/ner/review/sample',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({sample_size:20,strategy:'low_confidence'})})).json();
    alert('Stichprobe: '+r.sample_size+' von '+r.total_pending+' ausstehend.');
  }catch(e){alert(e.message)}finally{hp()}
}
async function nerAutoAccept(){
  const conf=parseFloat(prompt('Minimale Konfidenz (0.0-1.0):','0.8'));
  if(isNaN(conf))return;
  sp('NER Auto-Accept …','');
  try{
    const r=await(await fetch('/api/ner/review/auto-accept',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({min_confidence:conf})})).json();
    alert(r.auto_accepted+' akzeptiert, '+r.remaining_pending+' noch ausstehend.');
    loadPipelineStatus();
  }catch(e){alert(e.message)}finally{hp()}
}

// === AUTHORITY REVIEW ===
async function loadAuthorityCandidates(){
  try{
    const r=await(await fetch('/api/authority/candidates?status=pending')).json();
    const el=$('authority-candidates');if(!el)return;
    const cands=r.candidates||[];
    if(!cands.length){el.innerHTML='<em>Keine ausstehenden Kandidaten.</em>';return}
    el.innerHTML=cands.slice(0,100).map(c=>
      '<div style="padding:.3rem;border-bottom:1px solid var(--brd);font-size:.75rem;display:flex;align-items:center;gap:.3rem">'
      +'<span class="dict-type dict-type-'+(c.authority_type||'other')+'">'+esc(c.source)+'</span>'
      +'<span>'+esc(c.preferred_name)+' ('+esc(c.authority_id)+')</span>'
      +'<span style="color:#888">Score: '+(c.score*100).toFixed(0)+'%</span>'
      +'<button class="btn sm" onclick="reviewAuthCandidate(\''+esc(c.candidate_id)+'\',\'accepted\')">✓</button>'
      +'<button class="btn sm s" onclick="reviewAuthCandidate(\''+esc(c.candidate_id)+'\',\'rejected\')">✗</button>'
      +'</div>'
    ).join('')+'<div style="margin-top:.3rem;font-size:.72rem;color:#888">'+r.total+' Kandidaten gesamt</div>';
  }catch(e){console.error(e)}
}
async function reviewAuthCandidate(candidateId,status){
  try{await fetch('/api/authority/candidates/'+candidateId+'/review',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({status})});loadAuthorityCandidates();loadPipelineStatus();
  }catch(e){alert(e.message)}
}
async function commitAuthority(){
  sp('Normdaten übernehmen …','');
  try{
    const r=await(await fetch('/api/authority/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    alert(r.committed+' Normdaten in Wörterbuch übernommen.');
    loadDictEntries();loadDictTypes();loadAuthorityCandidates();loadPipelineStatus();updWS();
  }catch(e){alert(e.message)}finally{hp()}
}

// === MDS VALIDATION (Feature 4) ===
async function runMdsValidation(){
  const ds=$('mds-ds').value;if(!ds){alert('Datensatz wählen');return}
  sp('MDS validieren …','');
  _abortCtrl=new AbortController();
  try{const r=await(await fetch('/api/mds/validate',{method:'POST',headers:{'Content-Type':'application/json'},
    signal:_abortCtrl.signal,
    body:JSON.stringify({dataset:ds,include_custom:$('mds-custom').checked})})).json();
    if(r.error){alert(r.error);return}renderMdsResults(r);
  }catch(e){if(e.name!=='AbortError')alert(e.message);}finally{hp()}
}
function renderMdsResults(r){
  if(!$('mds-empty')||!$('mds-results'))return;
  $('mds-empty').style.display='none';$('mds-results').style.display='block';
  $('mds-schema').textContent=r.schema_name||'MDS 1.1';
  $('mds-summary').innerHTML=
    '<div class="mt"><div class="v">'+r.required_mapped+'/'+r.required_total+'</div><div class="l">Pflichtfelder zugeordnet</div></div>'
    +'<div class="mt"><div class="v">'+r.required_filled+'/'+r.required_total+'</div><div class="l">Pflichtfelder befüllt</div></div>'
    +'<div class="mt su"><div class="v">'+(r.completeness_score*100).toFixed(0)+'%</div><div class="l">Vollständigkeit</div></div>';
  $('mds-body').innerHTML=(r.fields||[]).map(f=>{
    const st=f.mapped?(f.fill_rate>0.5?'mds-ok':'mds-partial'):'mds-missing';
    return '<tr><td><span class="mds-status '+st+'"></span>'+esc(f.mds_name)+'</td>'
      +'<td style="font-family:monospace;font-size:.68rem">'+esc(f.goobi_type)+'</td>'
      +'<td><span class="bg '+(f.requirement==='required'?'no':'pl')+'">'+esc(f.requirement)+'</span></td>'
      +'<td>'+(f.mapped?'✓':'✗')+'</td>'
      +'<td style="font-size:.7rem">'+esc(f.csv_column||'—')+'</td>'
      +'<td><div class="mds-bar"><div class="mds-fill" style="width:'+(f.fill_rate*100)+'%"></div></div> '+(f.fill_rate*100).toFixed(0)+'%</td></tr>';
  }).join('');
}

// === TASKS (Feature 5) ===
let tasksFilter='all';
async function generateTasks(){
  const ds=$('mds-ds').value;if(!ds){alert('Datensatz wählen');return}
  sp('Tasks generieren …','');
  try{const r=await(await fetch('/api/tasks/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset:ds})})).json();
    if(r.error){alert(r.error);return}renderTasks(r.tasks||[]);alert(r.added+' neue Tasks erzeugt.');
  }catch(e){alert(e.message)}finally{hp()}
}
async function loadTasks(){
  try{const r=await(await fetch('/api/tasks')).json();renderTasks(r.tasks||[])}catch(e){}
}
function renderTasks(tasks){
  const flt=tasksFilter==='all'?tasks:tasks.filter(t=>t.status===tasksFilter);
  $('tasks-count').textContent='('+flt.length+'/'+tasks.length+')';
  $('tasks-list').innerHTML=flt.length?flt.map(t=>
    '<div class="task-item">'
    +'<span class="task-prio task-prio-'+t.priority+'">P'+t.priority+'</span>'
    +'<span class="task-status task-'+t.status+'">'+esc(t.status)+'</span>'
    +'<div style="flex:1"><strong>'+esc(t.title)+'</strong><br><span style="font-size:.7rem;color:#666">'+esc(t.description||'')+'</span>'
    +(t.suggestion?'<br><span style="font-size:.68rem;color:var(--ok)">💡 '+esc(t.suggestion)+'</span>':'')
    +'</div>'
    +'<div style="display:flex;gap:.2rem;flex-shrink:0">'
    +(t.status==='open'?'<button class="btn sm" onclick="updateTask(\''+esc(t.task_id)+'\',\'in_progress\')">▶</button>':'')
    +(t.status==='in_progress'?'<button class="btn sm" onclick="updateTask(\''+esc(t.task_id)+'\',\'done\')">✓</button>':'')
    +(t.status!=='done'?'<button class="btn sm s" onclick="updateTask(\''+esc(t.task_id)+'\',\'skipped\')">⏭</button>':'')
    +'</div></div>'
  ).join(''):'<div class="em" style="font-size:.75rem">Keine Tasks vorhanden.</div>';
}
function filterTasks(f,btn){
  tasksFilter=f;
  document.querySelectorAll('#tasks-filter-bar .fb2').forEach(x=>x.classList.remove('a'));
  if(btn)btn.classList.add('a');
  loadTasks();
}
async function updateTask(taskId,status){
  try{await fetch('/api/tasks/'+taskId+'/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});loadTasks()}catch(e){alert(e.message)}
}
async function clearDoneTasks(){
  try{await fetch('/api/tasks/clear-done',{method:'POST'});loadTasks()}catch(e){alert(e.message)}
}
async function addCustomMdsField(){
  const name=$('mds-cf-name').value.trim(),goobi=$('mds-cf-goobi').value.trim();
  if(!name||!goobi){alert('Feldname und Goobi-Typ erforderlich');return}
  try{const r=await(await fetch('/api/mds/custom-field',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mds_name:name,goobi_type:goobi,requirement:$('mds-cf-req').value})})).json();
    if(r.error){alert(r.error);return}$('mds-cf-name').value='';$('mds-cf-goobi').value='';loadCustomMdsFields();
  }catch(e){alert(e.message)}
}
async function loadCustomMdsFields(){
  try{const r=await(await fetch('/api/mds/fields')).json();
    const custom=r.custom||[];
    $('mds-custom-list').innerHTML=custom.length?custom.map((f,i)=>'<div style="display:flex;gap:.3rem;align-items:center;padding:.2rem 0"><span>'+esc(f.mds_name)+' → '+esc(f.goobi_type)+'</span><span class="bg '+(f.requirement==='required'?'no':'pl')+'">'+esc(f.requirement)+'</span><button class="btn sm s" onclick="delCustomMdsField('+i+')">✗</button></div>').join(''):'<em style="color:#888">Keine benutzerdefinierten Felder.</em>';
  }catch(e){}
}
async function delCustomMdsField(idx){
  try{await fetch('/api/mds/custom-field/'+idx,{method:'DELETE'});loadCustomMdsFields()}catch(e){alert(e.message)}
}

// === CATALOG ===
function renderCatalog(){if(!$('cat-body'))return;$('cat-body').innerHTML=CATALOG.map(c=>'<tr><td style="font-size:.62rem">'+esc(c.id)+'</td><td style="font-weight:600">'+esc(c.name)+'</td><td style="font-size:.68rem">'+esc(c.module)+'</td><td><span class="bg '+(c.status==='done'?'ac':c.status==='partial'?'pl':'no')+'">'+esc(c.status)+'</span></td><td style="font-size:.68rem">'+esc(c.tests||'—')+'</td><td style="font-size:.7rem;color:#666">'+esc(c.note||'')+'</td></tr>').join('')}

// === PROGRESS ===
function sp(t,x){
  _opCancelled=false;
  $('pt').textContent=t;$('pp').textContent=x||'';$('pct').textContent='';
  const pf=$('pf');pf.style.width='0';pf.classList.add('ind');
  $('po').classList.add('a');
}
function spUp(current,total,detail){
  const pf=$('pf');pf.classList.remove('ind');
  const pct=total>0?Math.round((current/total)*100):0;
  pf.style.width=pct+'%';
  $('pct').textContent=current+' / '+total+' ('+pct+'%)';
  if(detail)$('pp').textContent=detail;
}
function hp(){$('po').classList.remove('a');_abortCtrl=null;}
function cancelOp(){
  _opCancelled=true;
  if(_abortCtrl){_abortCtrl.abort();_abortCtrl=null;}
  hp();
}
// ESC handler
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){
    if($('lightbox').classList.contains('a')){closeLightbox();return;}
    if($('po').classList.contains('a')){cancelOp();return;}
  }
});

// === PDF UPLOAD & EXTRACTION ===
let _pdfDocs = [];          // list of uploaded PDF doc metadata
let _pdfExtraction = null;  // last extraction result (structured JSON)
let _pdfNerResult = null;   // last NER result (structured JSON)

// Bind PDF upload zone drag-and-drop
function bindPDFUpload(){
  const uz=$('uz-pdf'),fi=$('fi-pdf');
  if(!uz||!fi)return;
  fi.onchange=e=>{if(e.target.files&&e.target.files.length)uploadPDF();};
  uz.ondragover=e=>{e.preventDefault();uz.classList.add('dr')};
  uz.ondragleave=()=>uz.classList.remove('dr');
  uz.ondrop=e=>{
    e.preventDefault();uz.classList.remove('dr');
    const dt=e.dataTransfer;
    if(dt&&dt.files&&dt.files.length){
      // inject files into the input
      try{
        const dlist=new DataTransfer();
        for(const f of dt.files)if(f.name.toLowerCase().endsWith('.pdf'))dlist.items.add(f);
        fi.files=dlist.files;
        if(dlist.files.length)uploadPDF();
      }catch(ex){alert('Drag-and-Drop fehlgeschlagen: '+ex.message);}
    }
  };
}

async function uploadPDF(){
  const fi=$('fi-pdf');
  if(!fi||!fi.files||!fi.files.length){alert('Bitte PDF-Datei auswählen.');return;}
  const fd=new FormData();
  for(const f of fi.files)fd.append('files',f,f.name);
  sp('PDF wird verarbeitet …',fi.files.length+' Datei(en)');
  const statusEl=$('pdf-upload-status');
  try{
    const r=await(await fetch('/api/pdf/upload',{method:'POST',body:fd})).json();
    if(r.error){if(statusEl)statusEl.textContent='Fehler: '+r.error;hp();return;}
    _pdfDocs=(_pdfDocs||[]).concat(r.uploaded||[]);
    const total=r.total||0;
    if(statusEl)statusEl.textContent=total+' Dokument(e) hochgeladen.';
    renderPDFPane1();
    populatePDFDocSelector();
    hp();
  }catch(e){if(statusEl)statusEl.textContent='Fehler: '+e.message;hp();}
}

function renderPDFPane1(){
  const info=$('pdf-pane1-info');const cnt=$('pdf-pane1-count');const list=$('pdf-pane1-list');
  if(!info)return;
  if(!_pdfDocs.length){info.style.display='none';return;}
  info.style.display='block';
  if(cnt)cnt.textContent='('+_pdfDocs.length+')';
  if(list)list.innerHTML=_pdfDocs.map(d=>
    '<div class="pdf-page-item">'+
    '<span class="pdf-page-num">PDF</span>'+
    '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(d.filename)+'</span>'+
    '<span style="color:#888;font-size:.68rem">'+d.page_count+' S.</span>'+
    '</div>'
  ).join('');
}

function populatePDFDocSelector(){
  const sel=$('pdf-ner-doc');if(!sel)return;
  sel.innerHTML='<option value="">&#8212;</option>'+
    _pdfDocs.map(d=>'<option value="'+esc(d.id)+'">'+esc(d.filename)+' ('+d.page_count+' S.)</option>').join('');
}

function onPdfDocChange(){
  const sel=$('pdf-ner-doc');const info=$('pdf-doc-info');
  if(!sel||!info)return;
  const doc=_pdfDocs.find(d=>d.id===sel.value);
  info.textContent=doc?(doc.page_count+' Seiten · '+esc(doc.filename)):'';
  _pdfExtraction=null;_pdfNerResult=null;_pdfCurrentPage=1;_pdfTotalPages=1;
  // Reset split view
  const sc=$('pdf-scan-container');if(sc)sc.style.display='none';
  const emptyEl=$('pdf-text-empty');if(emptyEl)emptyEl.style.display='';
  const content=document.getElementById('pdf-text-content');if(content)content.remove();
  const summary=$('pdf-ner-summary-view');if(summary)summary.innerHTML='';
  const body=$('pdf-ner-body-view');if(body)body.innerHTML='';
  const imgEl=$('pdf-page-img');if(imgEl){imgEl.style.display='none';imgEl.src='';}
}

async function extractPDFText(){
  const docId=($('pdf-ner-doc')&&$('pdf-ner-doc').value)||'';
  if(!docId){alert('Bitte Dokument auswählen.');return;}
  const model=($('pdf-model')&&$('pdf-model').value)||'';
  const maxPages=parseInt(($('pdf-max-pages')&&$('pdf-max-pages').value)||'20')||20;
  const statusEl=$('pdf-extract-status');
  if(statusEl)statusEl.textContent='Extrahiere Text …';
  sp('PDF-Textextraktion …','OCR läuft');
  try{
    const r=await(await fetch('/api/pdf/extract',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({doc_id:docId,model,max_pages:maxPages})
    })).json();
    if(r.error){if(statusEl)statusEl.textContent='Fehler: '+r.error;hp();return;}
    _pdfExtraction=r;
    if(statusEl)statusEl.textContent=r.extracted_pages+' Seiten extrahiert.';
    renderPDFExtractResults(r);
  }catch(e){if(statusEl)statusEl.textContent='Fehler: '+e.message;}finally{hp();}
}

function renderPDFExtractResults(r){
  // Show scan container + navigate to page 1
  const sc=$('pdf-scan-container');if(sc)sc.style.display='block';
  _pdfCurrentPage=1;
  _pdfTotalPages=(r.pages||[]).length||r.total_pages||1;
  renderPDFSplitView();
}

function renderPDFNERResults(r){
  // Update entity tab in split view
  const summary=$('pdf-ner-summary-view');
  const body=$('pdf-ner-body-view');
  if(summary)summary.innerHTML=Object.entries(r.entity_types||{}).map(([t,n])=>
    '<span class="etype etype-'+esc(t)+'">'+esc(t)+'</span><span style="font-size:.68rem;margin-left:.15rem">'+n+'</span>'
  ).join('');
  if(body)body.innerHTML=(r.entities||[]).map(e=>'<tr>'+
    '<td style="font-weight:600">'+esc(e.text||'')+'</td>'+
    '<td><span class="etype etype-'+esc(e.type||'CON')+'">'+esc(e.type||'')+'</span></td>'+
    '<td>'+Math.round((e.confidence||0)*100)+'%</td>'+
    '<td style="font-size:.68rem;color:#888">'+esc(e.source||'')+'</td>'+
  '</tr>').join('');
  // Re-render text with highlighting for current page
  renderPDFSplitView();
}

// State for split view
let _pdfCurrentPage=1;
let _pdfTotalPages=1;

function renderPDFSplitView(){
  const pages=(_pdfExtraction&&_pdfExtraction.pages)||[];
  const totalPages=_pdfTotalPages||pages.length||1;
  const page=pages.find(p=>p.page===_pdfCurrentPage);

  // Page indicator
  const indicator=$('pdf-page-indicator');
  if(indicator)indicator.textContent='Seite '+_pdfCurrentPage+' / '+totalPages;
  const pageInfo=$('pdf-view-pageinfo');
  if(pageInfo)pageInfo.textContent='Seite '+_pdfCurrentPage+' von '+totalPages;

  // Prev/next buttons
  const prev=$('pdf-prev-btn');const next=$('pdf-next-btn');
  if(prev)prev.disabled=_pdfCurrentPage<=1;
  if(next)next.disabled=_pdfCurrentPage>=totalPages;

  // Load scan image
  const docSel=$('pdf-ner-doc');
  const docId=docSel&&docSel.value;
  const imgEl=$('pdf-page-img');
  const noImgEl=$('pdf-page-no-img');
  if(imgEl&&docId){
    imgEl.style.display='none';
    if(noImgEl)noImgEl.style.display='none';
    imgEl.onerror=function(){
      this.style.display='none';
      if(noImgEl)noImgEl.style.display='block';
    };
    imgEl.onload=function(){this.style.display='block';};
    imgEl.src='/api/pdf/'+encodeURIComponent(docId)+'/page/'+_pdfCurrentPage+'/image?_t='+Date.now();
  }

  // Render text with NER highlighting
  const textTab=$('pdf-text-tab');
  const emptyEl=$('pdf-text-empty');
  if(textTab){
    if(!page||!page.text){
      if(emptyEl)emptyEl.style.display='';
      const existing=textTab.querySelector('#pdf-text-content');
      if(existing)existing.remove();
    }else{
      if(emptyEl)emptyEl.style.display='none';
      const entities=(_pdfNerResult&&_pdfNerResult.entities)||[];
      const pageEntities=entities.filter(e=>e.source==='page_'+_pdfCurrentPage||e.source==='page '+_pdfCurrentPage);
      let content=textTab.querySelector('#pdf-text-content');
      if(!content){content=document.createElement('div');content.id='pdf-text-content';textTab.appendChild(content);}
      content.style.display='block';
      content.innerHTML=_buildHighlightedText(page.text,pageEntities);
    }
  }
}

function _buildHighlightedText(text,entities){
  if(!entities||!entities.length) return '<span>'+esc(text)+'</span>';
  // Sort by length (longest first) to avoid partial overlaps
  const sorted=[...entities].sort((a,b)=>(b.text||'').length-(a.text||'').length);
  // Build segments
  let segs=[{start:0,end:text.length,raw:text,entity:null}];
  for(const entity of sorted){
    const etxt=entity.text||'';if(!etxt)continue;
    const newSegs=[];
    for(const seg of segs){
      if(seg.entity){newSegs.push(seg);continue;}
      const idx=seg.raw.toLowerCase().indexOf(etxt.toLowerCase());
      if(idx<0){newSegs.push(seg);continue;}
      if(idx>0)newSegs.push({start:seg.start,end:seg.start+idx,raw:seg.raw.slice(0,idx),entity:null});
      newSegs.push({start:seg.start+idx,end:seg.start+idx+etxt.length,raw:seg.raw.slice(idx,idx+etxt.length),entity});
      const rest=seg.raw.slice(idx+etxt.length);
      if(rest)newSegs.push({start:seg.start+idx+etxt.length,end:seg.end,raw:rest,entity:null});
    }
    segs=newSegs;
  }
  return segs.filter(s=>s.raw).map(s=>{
    if(!s.entity) return esc(s.raw);
    return '<mark class="ner-highlight ner-'+esc(s.entity.type||'CON')+'" data-type="'+esc(s.entity.type||'')+'" title="'+esc(s.entity.type||'')+' · '+Math.round((s.entity.confidence||0)*100)+'%">'+esc(s.raw)+'</mark>';
  }).join('');
}

function pdfPageNav(delta){
  const pages=(_pdfExtraction&&_pdfExtraction.pages)||[];
  const total=_pdfTotalPages||pages.length||1;
  _pdfCurrentPage=Math.max(1,Math.min(total,_pdfCurrentPage+delta));
  renderPDFSplitView();
}

function setPdfViewTab(tab,btn){
  const textTab=$('pdf-text-tab');const entTab=$('pdf-entities-tab');
  if(textTab)textTab.style.display=tab==='text'?'':'none';
  if(entTab)entTab.style.display=tab==='entities'?'':'none';
  document.querySelectorAll('.pdf-view-hdr .tab').forEach(t=>t.classList.remove('a'));
  if(btn)btn.classList.add('a');
}

async function runPDFNER(){
  const docId=($('pdf-ner-doc')&&$('pdf-ner-doc').value)||'';
  if(!docId){alert('Bitte Dokument auswählen.');return;}
  if(!_pdfExtraction){alert('Bitte erst Textextraktion ausführen.');return;}
  const model=($('pdf-model')&&$('pdf-model').value)||'';
  const entityTypes=[...document.querySelectorAll('.pdf-ner-cb:checked')].map(c=>c.value);
  const statusEl=$('pdf-ner-status');
  if(statusEl)statusEl.textContent='NER läuft …';
  sp('PDF NER …','Entities werden erkannt');
  try{
    const r=await(await fetch('/api/pdf/ner',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({doc_id:docId,model,entity_types:entityTypes})
    })).json();
    if(r.error){if(statusEl)statusEl.textContent='Fehler: '+r.error;hp();return;}
    _pdfNerResult=r;
    if(statusEl)statusEl.textContent=r.entity_count+' Entities erkannt.';
    renderPDFNERResults(r);
  }catch(e){if(statusEl)statusEl.textContent='Fehler: '+e.message;}finally{hp();}
}

function renderPDFNERResults(r){
  const el=$('pdf-ner-result');const body=$('pdf-ner-body');
  const cnt=$('pdf-ner-count');const summary=$('pdf-ner-summary');
  if(!el||!body)return;
  el.style.display='block';
  if(cnt)cnt.textContent='('+r.entity_count+')';
  if(summary)summary.innerHTML=Object.entries(r.entity_types||{}).map(([t,n])=>
    '<span class="etype etype-'+esc(t)+'">'+esc(t)+'</span> <span style="font-size:.68rem">'+n+'</span>'
  ).join('');
  body.innerHTML=(r.entities||[]).map(e=>'<tr>'+
    '<td style="font-weight:600">'+esc(e.text||'')+'</td>'+
    '<td><span class="etype etype-'+esc(e.type||'CON')+'">'+esc(e.type||'')+'</span></td>'+
    '<td>'+Math.round((e.confidence||0)*100)+'%</td>'+
    '<td style="font-size:.68rem;color:#888">'+esc(e.source||'')+'</td>'+
  '</tr>').join('');
}

// Download PDF extraction as structured JSON
function downloadPDFExtractionJSON(){
  if(!_pdfExtraction){alert('Bitte erst Textextraktion ausführen.');return;}
  const out={
    schema:'debussy-pdf-extraction/1.0',
    generated:new Date().toISOString(),
    document:_pdfExtraction.document,
    doc_id:_pdfExtraction.doc_id,
    total_pages:_pdfExtraction.total_pages,
    extracted_pages:_pdfExtraction.extracted_pages,
    pages:_pdfExtraction.pages||[],
  };
  dl('debussy_pdf_extraction.json',JSON.stringify(out,null,2),'application/json');
}

// Download PDF NER as structured JSON
function downloadPDFNERJSON(){
  if(!_pdfNerResult){alert('Bitte erst NER ausführen.');return;}
  const out={
    schema:'debussy-pdf-ner/1.0',
    generated:new Date().toISOString(),
    document:_pdfNerResult.document,
    doc_id:_pdfNerResult.doc_id,
    entity_count:_pdfNerResult.entity_count,
    entity_types:_pdfNerResult.entity_types||{},
    entities:_pdfNerResult.entities||[],
  };
  dl('debussy_pdf_ner.json',JSON.stringify(out,null,2),'application/json');
}

// === NER JSON EXPORT ===
function downloadNERJSON(){
  if(!nerData||!nerData.length){alert('Bitte erst NER ausführen.');return;}
  const out={
    schema:'debussy-ner/1.0',
    generated:new Date().toISOString(),
    entity_count:nerData.length,
    entities:nerData.map(e=>({
      text:e.text||'',
      type:e.type||'',
      confidence:e.confidence||0,
      reasoning:e.reasoning||'',
      record_id:e.record_id||'',
      column:e.column||'',
      source:e.source||'',
      status:e.status||'pending',
      gnd_id:e.gnd_id||null,
      gnd_preferred:e.gnd_preferred||null,
    })),
  };
  dl('debussy_ner.json',JSON.stringify(out,null,2),'application/json');
}

// === SSE READER ===
async function fetchSSE(url,body,onProgress,onDone,onError){
  _abortCtrl=new AbortController();
  const resp=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body),signal:_abortCtrl.signal});
  if(!resp.ok){const e=await resp.json().catch(()=>({error:resp.statusText}));throw Error(e.error||resp.statusText);}
  const reader=resp.body.getReader();
  const decoder=new TextDecoder();
  let buf='';
  while(true){
    const{done,value}=await reader.read();
    if(done)break;
    buf+=decoder.decode(value,{stream:true});
    const lines=buf.split('\n');
    buf=lines.pop()||'';
    for(const line of lines){
      if(!line.startsWith('data: '))continue;
      try{
        const evt=JSON.parse(line.slice(6));
        if(evt.type==='progress'&&onProgress)onProgress(evt);
        else if(evt.type==='done'&&onDone)onDone(evt.result);
        else if(evt.type==='error'&&onError)onError(evt.message);
      }catch(parseErr){console.warn('SSE parse error',parseErr);}
    }
  }
}

// === INIT ===
function showInitError(label){const b=document.createElement('div');b.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#fee2e2;color:#991b1b;padding:.4rem 1rem;font-size:.78rem;border-top:2px solid #f87171';b.textContent='⚠ UI-Initialisierung fehlgeschlagen'+(label?': '+label:'')+' – bitte Konsole prüfen';document.body.appendChild(b)}
(function(){
  const failed=[];
  [initNav,initTabs,initUpload,initPanels].forEach(fn=>{try{fn()}catch(err){console.error('[init]',fn.name,err);failed.push(fn.name)}});
  try{loadPreset()}catch(err){console.error('[init] loadPreset',err);failed.push('loadPreset')}
  try{applyImgPreset()}catch(err){console.error('[init] applyImgPreset',err);failed.push('applyImgPreset')}
  try{applyActionPreset('ner');applyActionPreset('scan');applyActionPreset('edtf');applyActionPreset('ocr')}catch(err){console.error('[init] applyActionPreset',err);failed.push('applyActionPreset')}
  try{refreshReviewStats()}catch(err){console.error('[init] refreshReviewStats',err);failed.push('refreshReviewStats')}
  try{const ct=$('cfg-tasks');if(ct)ct.innerHTML=Object.values(TASKS).map(t=>'<div class="ft"><span class="bg ac">'+esc(t.type||'')+'</span><div><strong>'+esc(t.name)+'</strong><br><span class="d">'+esc(t.description||'')+'</span></div></div>').join('');}catch(err){console.error('[init] cfg-tasks',err);failed.push('cfg-tasks')}
  try{if(typeof renderCatalog==='function')renderCatalog()}catch(err){console.error('[init] renderCatalog',err);failed.push('renderCatalog')}
  try{chkGPU()}catch(err){console.error('[init] chkGPU',err);failed.push('chkGPU')}
  try{updWS()}catch(err){console.error('[init] updWS',err);failed.push('updWS')}
  try{loadImages().catch(()=>{})}catch(err){console.error('[init] loadImages',err);failed.push('loadImages')}
  try{loadTermsDict()}catch(err){console.error('[init] loadTermsDict',err);failed.push('loadTermsDict')}
  try{loadGPUConfig()}catch(err){console.error('[init] loadGPUConfig',err);failed.push('loadGPUConfig')}
  try{checkAuth()}catch(err){console.error('[init] checkAuth',err);failed.push('checkAuth')}
  try{loadDictEntries();loadDictTypes()}catch(err){console.error('[init] dict',err);failed.push('dict')}
  try{loadPipelineStatus()}catch(err){console.error('[init] pipeline',err);failed.push('pipeline')}
  try{loadTasks()}catch(err){console.error('[init] tasks',err);failed.push('tasks')}
  try{loadCustomMdsFields()}catch(err){console.error('[init] mdsFields',err);failed.push('mdsFields')}
  if(failed.length)showInitError(failed.join(', '));
})();

// ============================================================
// PHASE 2 — BEREINIGUNG: Material Context + Review Queue
// ============================================================

// --- Material context detection ---
let currentMatCtx='table';

function detectMatCtx(files){
  const exts=[...files].map(f=>f.name.toLowerCase().replace(/^.*\./,''));
  const hasTable=exts.some(e=>['csv','tsv','xlsx','xls','xml'].includes(e));
  const hasImg=exts.some(e=>['jpg','jpeg','png','tif','tiff','webp','img'].includes(e));
  const hasPdf=exts.some(e=>e==='pdf');
  const count=[hasTable,hasImg,hasPdf].filter(Boolean).length;
  if(count>1)return'mixed';
  if(hasImg)return'images';
  if(hasPdf)return'pdf';
  return'table';
}

function setMatCtx(ctx){
  currentMatCtx=ctx;
  const ws=$('mat-workspace');
  if(!ws)return;
  ws.className='mat-workspace mat-ctx-'+ctx;
  document.querySelectorAll('.mat-ctx-pill').forEach(p=>{
    p.classList.toggle('active',p.dataset.ctx===ctx);
  });
}

/** Called after file selection — auto-detect material type and update workspace layout. */
function detectAndSetMatCtx(files){
  if(!files||!files.length)return;
  const ctx=detectMatCtx(files);
  setMatCtx(ctx);
  const hint=$('mat-auto-hint');
  if(hint)hint.style.display='inline';
}

// --- Phase 2 state ---
let revItems=[],revFilters={status:'',severity:'',category:''};
let revWorkPackages=[],revSuggestions=[],revChangelog=[];

// --- Summary ---
async function loadRevSummary(){
  try{
    const r=await fetch('/api/review/items/summary');
    if(!r.ok)return;
    const d=await r.json();
    const el=$('rev-summary-bar');
    if(!el)return;
    const total=d.total||0;
    const bs=d.by_status||{};
    const bsv=d.by_severity||{};
    el.innerHTML='<div class="mt"><div class="v">'+total+'</div><div class="l">Gesamt</div></div>'+
      Object.entries(bs).map(([k,v])=>'<div class="mt'+(k==='accepted'?' su':k==='rejected'?' cr':k==='needs_expert_review'?' wr':'')+'"><div class="v">'+v+'</div><div class="l">'+esc(k)+'</div></div>').join('')+
      Object.entries(bsv).filter(([k])=>k!=='info').map(([k,v])=>'<div class="mt'+(k==='critical'?' cr':k==='warning'?' wr':'')+'"><div class="v">'+v+'</div><div class="l">'+esc(k)+'</div></div>').join('');
  }catch(e){console.error('[loadRevSummary]',e);}
}

async function buildRevQueue(){
  const src=$('rev-source')?$('rev-source').value:'';
  const aiB=$('rev-is-ai')?$('rev-is-ai').checked:false;
  sp('Review-Queue aufbauen \u2026');
  try{
    const r=await fetch('/api/review/queue/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:src,is_ai_based:aiB})});
    const d=await r.json();
    if(d.error){alert(d.error);return;}
    const el=$('rev-build-status');
    if(el)el.textContent='\u2713 '+(d.items_created||0)+' Items erstellt';
    loadRevSummary();
    loadRevItems();
  }catch(e){alert('Fehler: '+e.message);}
  finally{hp();}
}

async function generateWorkPackages(){
  sp('Arbeitspakete generieren \u2026');
  try{
    const r=await fetch('/api/review/work-packages/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    if(d.error){alert(d.error);return;}
    const el=$('rev-wp-status');
    if(el)el.textContent='\u2713 '+(d.packages_created||0)+' Pakete erstellt';
    loadWorkPackages();
  }catch(e){alert('Fehler: '+e.message);}
  finally{hp();}
}

// --- Review Items ---
async function loadRevItems(){
  try{
    const p=new URLSearchParams();
    if(revFilters.status)p.set('status',revFilters.status);
    if(revFilters.severity)p.set('severity',revFilters.severity);
    if(revFilters.category)p.set('category',revFilters.category);
    p.set('limit','100');
    const r=await fetch('/api/review/items?'+p);
    if(!r.ok)return;
    const d=await r.json();
    revItems=d.items||[];
    renderRevItems();
    const el=$('rev-items-count');
    if(el)el.textContent='('+(d.total||revItems.length)+')';
  }catch(e){console.error('[loadRevItems]',e);}
}

function renderRevItems(){
  const el=$('rev-items-list');
  if(!el)return;
  if(!revItems.length){el.innerHTML='<div class="em" style="font-size:.78rem">Keine Items. Queue aufbauen oder Laden klicken.</div>';return;}
  el.innerHTML=revItems.map(item=>{
    const sev=item.severity||'info';
    const st=item.status||'pending';
    return '<div class="rev-item">'+
      '<div class="rev-item-hdr">'+
        '<span class="sv '+esc(sev)+'">'+esc(sev)+'</span>'+
        '<span class="rev-st rev-st-'+esc(st)+'">'+esc(st)+'</span>'+
        (item.column?'<span style="font-size:.68rem;background:#f5f5f4;padding:.1rem .3rem;border-radius:3px">'+esc(item.column)+'</span>':'')+
        '<span class="rev-item-msg">'+esc(item.message||'')+'</span>'+
      '</div>'+
      (item.reasoning?'<div style="font-size:.68rem;color:#666;margin-bottom:.15rem">'+esc(item.reasoning)+'</div>':'')+
      '<div class="rev-item-meta">'+
        (item.record_id?'Record: '+esc(item.record_id)+' \u00b7 ':'')+
        esc(item.category||'')+
        (item.confidence!=null?' \u00b7 '+Math.round(item.confidence*100)+'%':'')+
      '</div>'+
      '<div class="rev-item-actions">'+
        '<button class="btn sm" onclick="setRevStatus(\''+esc(item.item_id)+'\',\'accepted\')">&#10003; Akzeptieren</button>'+
        '<button class="btn sm s" onclick="setRevStatus(\''+esc(item.item_id)+'\',\'rejected\')" style="background:#888">&#10007; Ablehnen</button>'+
        '<button class="btn sm s" onclick="setRevStatus(\''+esc(item.item_id)+'\',\'needs_expert_review\')" style="background:var(--warn)">? Experte</button>'+
      '</div>'+
    '</div>';
  }).join('');
}

async function setRevStatus(itemId,status){
  try{
    const r=await fetch('/api/review/items/'+encodeURIComponent(itemId)+'/status',{
      method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({status,reviewer:'curator'})
    });
    if(!r.ok){alert('Fehler beim Update');return;}
    const item=revItems.find(i=>i.item_id===itemId);
    if(item)item.status=status;
    renderRevItems();
    loadRevSummary();
  }catch(e){alert('Fehler: '+e.message);}
}

async function batchRevStatus(status){
  const visible=revItems.filter(i=>!revFilters.status||i.status===revFilters.status);
  for(const item of visible){if(item.status!==status)await setRevStatus(item.item_id,status);}
}

function filterRevQueue(field,val,btn){
  revFilters[field]=revFilters[field]===val?'':val;
  const bar=$('rev-filter-'+field);
  if(bar)bar.querySelectorAll('.fb2').forEach(p=>p.classList.toggle('a',p.dataset.val===(revFilters[field]||'')));
  loadRevItems();
}

// --- Work Packages ---
async function loadWorkPackages(){
  try{
    const r=await fetch('/api/review/work-packages');
    if(!r.ok)return;
    const d=await r.json();
    revWorkPackages=d.packages||[];
    renderWorkPackages();
    const el=$('rev-wp-count');
    if(el)el.textContent='('+revWorkPackages.length+')';
  }catch(e){console.error('[loadWorkPackages]',e);}
}

function renderWorkPackages(){
  const el=$('rev-wp-list');
  if(!el)return;
  if(!revWorkPackages.length){el.innerHTML='<div class="em" style="font-size:.78rem">Keine Arbeitspakete. Zuerst generieren.</div>';return;}
  el.innerHTML=revWorkPackages.map(wp=>{
    const prio=wp.priority||'medium';
    const auto=wp.automation_potential||'low';
    return '<div class="wp-card">'+
      '<div class="wp-card-hdr">'+
        '<div class="wp-card-title">'+esc(wp.title||'')+'</div>'+
        '<div class="wp-card-badges">'+
          '<span class="wp-prio-'+esc(prio)+'">'+esc(prio.toUpperCase())+'</span>'+
          '<span class="wp-auto wp-auto-'+esc(auto)+'">Auto: '+esc(auto)+'</span>'+
        '</div>'+
      '</div>'+
      '<div class="wp-card-meta">'+esc(wp.description||'')+
        (wp.affected_columns&&wp.affected_columns.length?' \u00b7 Spalten: '+esc(wp.affected_columns.join(', ')):'')+(wp.estimated_records?' \u00b7 ~'+wp.estimated_records+' Datens\u00e4tze':'')+
      '</div>'+
      (wp.recommended_strategy?'<div class="wp-card-strategy">'+esc(wp.recommended_strategy)+'</div>':'')+
    '</div>';
  }).join('');
}

// --- Suggestions ---
async function loadRevSuggestions(){
  try{
    const r=await fetch('/api/review/suggestions');
    if(!r.ok)return;
    const d=await r.json();
    revSuggestions=d.suggestions||[];
    renderRevSuggestions();
    const el=$('rev-sug-count');
    if(el)el.textContent='('+revSuggestions.length+')';
  }catch(e){console.error('[loadRevSuggestions]',e);}
}

function renderRevSuggestions(){
  const el=$('rev-sug-list');
  if(!el)return;
  if(!revSuggestions.length){el.innerHTML='<div class="em" style="font-size:.78rem">Keine Vorschl\u00e4ge.</div>';return;}
  el.innerHTML=revSuggestions.map(s=>{
    const st=s.status||'pending';
    return '<div class="rev-item">'+
      '<div class="rev-item-hdr">'+
        '<span class="rev-st rev-st-'+esc(st)+'">'+esc(st)+'</span>'+
        '<span style="font-size:.73rem;font-weight:600">'+esc(s.action_type||'')+'</span>'+
      '</div>'+
      '<div style="font-size:.73rem;margin:.15rem 0">'+
        '<strong>Original:</strong> '+esc(s.original_value||'\u2014')+
        (s.suggested_value?' \u2192 <strong>'+esc(s.suggested_value)+'</strong>':'')+
      '</div>'+
      (s.reasoning?'<div style="font-size:.68rem;color:#666">'+esc(s.reasoning)+'</div>':'')+
      '<div class="rev-item-actions">'+
        '<button class="btn sm" onclick="setSugStatus(\''+esc(s.suggestion_id)+'\',\'accepted\')">&#10003; Akzeptieren</button>'+
        '<button class="btn sm s" onclick="setSugStatus(\''+esc(s.suggestion_id)+'\',\'rejected\')" style="background:#888">&#10007; Ablehnen</button>'+
      '</div>'+
    '</div>';
  }).join('');
}

async function setSugStatus(sugId,status){
  try{
    const r=await fetch('/api/review/suggestions/'+encodeURIComponent(sugId)+'/status',{
      method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})
    });
    if(!r.ok){alert('Fehler beim Update');return;}
    await loadRevSuggestions();
  }catch(e){alert('Fehler: '+e.message);}
}

async function revApplyChanges(dryRun){
  sp(dryRun?'Vorschau \u2026':'Änderungen anwenden \u2026');
  try{
    const dsId=$('rev-apply-ds')?$('rev-apply-ds').value:'';
    const body={dry_run:!!dryRun,reviewer:'curator'};
    if(dsId)body.dataset_id=dsId;
    const r=await fetch('/api/review/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(d.error){alert(d.error);return;}
    const el=$('rev-apply-status');
    if(el)el.textContent=(dryRun?'Vorschau: ':'\u2713 Angewendet: ')+(d.changes_applied||d.changes_preview||0)+' \u00c4nderungen';
    if(!dryRun){loadRevChangelog();populateDS();}
  }catch(e){alert('Fehler: '+e.message);}
  finally{hp();}
}

// --- Changelog ---
async function loadRevChangelog(){
  try{
    const r=await fetch('/api/review/changelog');
    if(!r.ok)return;
    const d=await r.json();
    revChangelog=d.changelog||[];
    renderRevChangelog();
    const el=$('rev-log-count');
    if(el)el.textContent='('+revChangelog.length+')';
  }catch(e){console.error('[loadRevChangelog]',e);}
}

function renderRevChangelog(){
  const el=$('rev-log-body');
  if(!el)return;
  const empty=$('rev-log-empty');
  if(!revChangelog.length){if(empty)empty.style.display='block';el.innerHTML='';return;}
  if(empty)empty.style.display='none';
  el.innerHTML=revChangelog.map(c=>'<tr>'+
    '<td>'+esc(c.record_id||'\u2014')+'</td>'+
    '<td>'+esc(c.column||'\u2014')+'</td>'+
    '<td style="font-family:monospace">'+esc(c.original_value||'')+'</td>'+
    '<td style="font-family:monospace;color:var(--ok)">'+esc(c.new_value||'')+'</td>'+
    '<td>'+esc(c.action_type||'')+'</td>'+
    '<td style="font-size:.65rem">'+esc((c.applied_at||'').replace('T',' ').slice(0,16))+'</td>'+
  '</tr>').join('');
}

async function exportRevStatus(){
  try{
    const r=await fetch('/api/review/export');
    if(!r.ok)return;
    const d=await r.json();
    dl('review-export.json',JSON.stringify(d,null,2),'application/json');
  }catch(e){alert('Export-Fehler: '+e.message);}
}

// Populate rev-apply-ds with loaded datasets
function populateRevApplyDs(){
  const sel=$('rev-apply-ds');
  if(!sel)return;
  const ds=Object.keys(ufiles).length?Object.values(ufiles).map(f=>f.uploadName):[];
  // Also check loaded dataset names from state
  const existing=new Set([...sel.options].map(o=>o.value).filter(Boolean));
  ds.forEach(name=>{if(!existing.has(name)){const o=document.createElement('option');o.value=name;o.textContent=name;sel.appendChild(o);}});
}

// === SYSTEM CHECK (issue #180) ===
async function loadSystemCheck(){
  const body=$('sys-check-body'),sum=$('sys-check-summary');
  if(!body)return;
  body.innerHTML='<div style="color:#888">Pr&uuml;fe Abh&auml;ngigkeiten &hellip;</div>';
  if(sum)sum.textContent='';
  try{
    const r=await(await fetch('/api/system/check')).json();
    renderSystemCheck(r);
  }catch(e){
    body.innerHTML='<div style="color:var(--crit,#c33)">Fehler: '+esc(e.message||String(e))+'</div>';
  }
}

function renderSystemCheck(r){
  const body=$('sys-check-body'),sum=$('sys-check-summary');
  if(!body)return;
  const icons={ok:'&#10003;',warn:'&#9888;',missing:'&#10007;'};
  const colors={ok:'var(--ok,#080)',warn:'var(--warn,#a60)',missing:'var(--crit,#c33)'};
  let html='';
  for(const p of (r.probes||[])){
    const c=colors[p.status]||'#666';
    html+='<div style="border-left:3px solid '+c+';padding:.4rem .6rem;margin-bottom:.4rem;background:#fafafa">';
    html+='<div><span style="color:'+c+';font-weight:600">'+icons[p.status]+'</span> ';
    html+='<strong>'+esc(p.name)+'</strong> <span style="color:#666">&middot; '+esc(p.capability)+'</span>';
    if(p.version)html+=' <span style="color:#888;font-size:.74rem">('+esc(p.version)+')</span>';
    html+='</div>';
    html+='<div style="font-size:.76rem;color:#444;margin-top:.15rem">'+esc(p.message)+'</div>';
    if(p.status!=='ok' && p.install_hint){
      html+='<div style="font-size:.74rem;margin-top:.2rem"><code style="background:#eef;padding:1px 4px">'+esc(p.install_hint)+'</code></div>';
    }
    if(p.related_issues && p.related_issues.length){
      html+='<div style="font-size:.7rem;color:#888;margin-top:.15rem">Related: '+p.related_issues.map(esc).join(', ')+'</div>';
    }
    html+='</div>';
  }
  body.innerHTML=html;
  if(sum){
    const s=r.summary||{};
    const overall=r.overall_status||'ok';
    const c=colors[overall]||'#666';
    sum.innerHTML='<span style="color:'+c+';font-weight:600">'+icons[overall]+' '+overall.toUpperCase()+'</span> '+
      '('+(s.ok||0)+' ok, '+(s.warn||0)+' Warnungen, '+(s.missing||0)+' fehlt)';
  }
}
