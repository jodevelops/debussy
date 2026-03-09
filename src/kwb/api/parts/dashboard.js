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

// === SECURITY ===
function esc(s){return s==null?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function safeOpt(val,label){return '<option value="'+esc(val)+'">'+esc(label)+'</option>'}
function dl(name,content,type){const b=new Blob([content],{type});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click()}

// === NAV ===
function bindTabs(id){const el=$(id);if(!el)return;el.onclick=e=>{if(!e.target.classList.contains('tab'))return;const t=e.target.dataset.t;e.currentTarget.querySelectorAll('.tab').forEach(x=>x.classList.toggle('a',x.dataset.t===t));e.currentTarget.parentElement.querySelectorAll('[data-t].tp').forEach(x=>x.classList.toggle('a',x.dataset.t===t))}}
function initNav(){try{const nav=document.querySelector('.nav');if(!nav)return;nav.onclick=e=>{if(!e.target.classList.contains('nt'))return;const p=e.target.dataset.p;document.querySelectorAll('.nt').forEach(t=>t.classList.toggle('a',t.dataset.p===p));document.querySelectorAll('.pg').forEach(x=>x.classList.toggle('a',x.dataset.p===p))}}catch(err){console.error('[initNav]',err)}}
function initTabs(){try{bindTabs('dt')}catch(err){console.error('[initTabs]',err)}}

// === UPLOAD ===
function initUpload(){try{const uz=$('uz'),fi=$('fi');if(fi)fi.onchange=e=>hf(e.target.files);if(uz){uz.ondragover=e=>{e.preventDefault();uz.classList.add('dr')};uz.ondragleave=()=>uz.classList.remove('dr');uz.ondrop=e=>{e.preventDefault();uz.classList.remove('dr');hf(e.dataTransfer.files)}}}catch(err){console.error('[initUpload]',err)}}
function hf(files){for(const f of files)ufiles[f.name]=f;rfl()}
function rfl(){
  const n=Object.keys(ufiles);$('fc').style.display=n.length?'block':'none';
  $('fcl').innerHTML=n.map(x=>'<div class="ci"><input type="checkbox" checked value="'+esc(x)+'" class="fcb"><span>'+esc(x)+'</span><span class="m">'+(ufiles[x].size/1024).toFixed(0)+'KB</span></div>').join('');
}
function populateDS(){
  const n=Object.keys(ufiles);
  for(const id of['ner-ds','scan-ds','edtf-ds','exp-ds','exp-csv-ds','exp-ld-ds','fm-ds','terms-ds']){
    const s=$(id);if(!s)continue;
    s.innerHTML=n.map((x,i)=>'<option value="'+esc(x)+'"'+(i===0?' selected':'')+'>'+esc(x)+'</option>').join('')}
  if(n.length>0){
    loadCols('ner-ds','ner-cols');loadDateCols();loadRecords();loadFMCols();
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
      $('exp-rec-info').textContent=(recordTotal?((recordOffset+1)+'–'+Math.min(recordOffset+recordLimit,recordTotal)+' / '+recordTotal):'0 / 0');
      $('exp-rec-prev').disabled=recordOffset<=0;
      $('exp-rec-next').disabled=!d.has_more;
    }
  }catch(e){}
}
function pageRecords(dir){recordOffset=Math.max(0,recordOffset+(dir*recordLimit));loadRecords(false)}
function initPanels(){try{const expDs=$('exp-ds');if(expDs)expDs.onchange=()=>loadRecords(true)}catch(err){console.error('[initPanels]',err)}}

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
  const mdsOpts=MDS_FIELDS.map(f=>'<option value="'+esc(f.goobi)+'"'+(f.goobi===selectedType?' selected':'')+(f.pflicht?'')+'>'+esc(f.mds+(f.pflicht?' ★':''))+' ('+esc(f.goobi)+')</option>').join('');
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
async function runStruct(){
  const sel=[...document.querySelectorAll('.fcb:checked')].map(c=>c.value);
  if(!sel.length){alert('Mindestens eine Datei auswählen.');return}
  sp('Strukturelle Analyse …',sel.length+' Datei(en)');
  const fd=new FormData();for(const n of sel)fd.append('files',ufiles[n]);
  try{const r=await(await fetch('/api/analyze',{method:'POST',body:fd})).json();
    if(r.error)throw Error(r.error);curRep=r;rrep(r);populateDS();updWS()
  }catch(e){alert(e.message)}finally{hp()}
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
  try{const r=await(await fetch('/api/ner',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds,columns:cols,method,sample_size:n,
      sample_mode:isPilot?'stratified':'random',sample_percent:isPilot?2:null,
      stratified:isPilot,chunk_size:parseInt($('ner-chunk').value)||200,
      model:$('cfg-mt').value||'',
      system_prompt:($('ner-sp')?.value||$('cfg-sys').value)})})).json();
    if(r.error)throw Error(r.error);nerData=r.entities||[];renderNER(r);renderRunMetrics('ner-metrics',r.run_metrics);updWS()
  }catch(e){alert(e.message)}finally{hp()}
}

function renderNER(r){
  $('ner-e').style.display='none';$('ner-r').style.display='block';
  $('ner-count').textContent='('+nerData.length+' gefunden, Modell: '+(r.model||'?')+')';
  const types=[...new Set(nerData.map(e=>e.type))].sort();
  $('ner-filter').innerHTML='<div class="fb2 a" onclick="setNerType(\'all\',this)">Alle Typen</div>'+
    types.map(t=>'<div class="fb2" onclick="setNerType(\''+esc(t)+'\',this)"><span class="etype etype-'+esc(t)+'">'+esc(t)+'</span> '+nerData.filter(e=>e.type===t).length+'</div>').join('');
  applyNERFilters();
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
  $('ner-body').innerHTML=ents.map((e,i)=>{
    const status=e.status||'pending';
    return '<tr>'+
      '<td style="font-weight:600">'+esc(e.text)+(e.gnd_preferred?'<br><span style="font-size:.65rem;color:var(--ok)">GND: '+esc(e.gnd_preferred)+'</span>':'')+'</td>'+
      '<td><span class="etype etype-'+esc(e.type)+'">'+esc(e.type)+'</span></td>'+
      '<td><span class="conf-bar" style="width:'+Math.round((e.confidence||0)*40)+'px;background:'+((e.confidence||0)>.7?'var(--ok)':(e.confidence||0)>.4?'var(--warn)':'var(--crit)')+'"></span>'+((e.confidence||0)*100).toFixed(0)+'%</td>'+
      '<td style="font-size:.7rem">'+esc(e.reasoning||'')+'</td>'+
      '<td style="font-size:.68rem">'+esc(e.record_id||'')+'</td>'+
      '<td style="font-size:.62rem">'+esc(e.source||'')+'</td>'+
      '<td><span class="est est-'+esc(status)+'">'+esc(status)+'</span></td>'+
      '<td><button class="btn sm" onclick="setEntity('+i+',\'accepted\')">✓</button> <button class="btn sm s" onclick="setEntity('+i+',\'rejected\')">✗</button></td>'+
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
  $('gnd-r').style.display='block';
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
  try{const r=await(await fetch('/api/scan',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds,sample_size:n,
      sample_mode:isPilot?'stratified':'random',sample_percent:isPilot?2:null,
      stratified:isPilot,chunk_size:parseInt($('scan-chunk').value)||200,
      model:$('cfg-mt').value||'',
      system_prompt:($('scan-sp')?.value||$('cfg-sys').value)})})).json();
    if(r.error)throw Error(r.error);renderScan(r);renderRunMetrics('scan-metrics',r.run_metrics)
  }catch(e){alert(e.message)}finally{hp()}}


function renderScan(r){$('scan-r').style.display='block';const issues=r.issues||[];
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
  try{
    const r=await fetch('/api/dict-scan',{method:'POST',headers:{'Content-Type':'application/json'},
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
  }catch(e){alert('Fehler: '+e.message);}finally{hp();}
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
  try{const r=await(await fetch('/api/edtf',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dataset:ds,column:col,sample_size:n,
      sample_mode:isPilot?'stratified':'random',sample_percent:isPilot?2:null,
      stratified:isPilot,chunk_size:parseInt($('edtf-chunk').value)||200,
      use_llm:$('edtf-llm').value==='1',
      model:$('cfg-mt').value||'',
      system_prompt:$('edtf-sp').value||$('cfg-sys').value})})).json();
    if(r.error)throw Error(r.error);edtfData=r.results||[];renderEDTF(r);renderRunMetrics('edtf-metrics',r.run_metrics);updWS()
  }catch(e){alert(e.message)}finally{hp()}}


function renderEDTF(r){
  $('edtf-e').style.display='none';$('edtf-r').style.display='block';
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
  rCombinedCols(d.datasets||[]);
  $('mdx').value=d.markdown||'';
  // Show ID column selection bar
  showIdColBar(d);
}
function ff(f,b){document.querySelectorAll('#fbar .fb2').forEach(x=>x.classList.remove('a'));if(b)b.classList.add('a');rfnd(f==='all'?(curRep?.findings||[]):(curRep?.findings||[]).filter(x=>x.severity===f))}
function rfnd(fs){if(!fs.length){$('flist').textContent='Keine Findings.';return}
  $('flist').innerHTML=fs.map(f=>'<div class="fd '+esc(f.severity)+'"><span class="sv '+esc(f.severity)+'">'+esc(f.severity)+'</span> <span style="font-size:.62rem;color:#888">'+esc(f.category)+'</span><div style="margin-top:.1rem">'+esc(f.message)+'</div>'+(f.column?'<div style="font-size:.68rem;color:#666">Spalte: '+esc(f.column)+'</div>':'')+(f.suggestion?'<div style="font-style:italic;color:var(--ac);font-size:.73rem">→ '+esc(f.suggestion)+'</div>':'')+'</div>').join('')}

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
async function createArbeitspaket(){
  if(!curRep){alert('Erst Daten laden und Analyse starten.');return;}
  const ds=curRep.datasets||[];
  if(!ds.length){alert('Keine Datensätze geladen.');return;}
  // Use first dataset
  const d=ds[0];
  const dsName=d.source_name;
  const idCol=d.id_column||d.columns?.[0]?.name||'';
  const fullName=Object.keys(ufiles).find(n=>n.includes(dsName)||n.startsWith(dsName))||Object.keys(ufiles)[0]||'';
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
      const hdrs=lines[0].split(',');
      const idIdx=hdrs.findIndex(h=>h.replace(/^"|"$/g,'')===idCol);
      let out=text;
      if(idIdx>0){
        // Move id column to front
        const reordered=lines.map(line=>{
          const cols=line.match(/"(?:[^"]|"")*"|[^,]*/g)||line.split(',');
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
    const fname=Object.keys(ufiles).find(n=>n.includes(d.source_name)||n.startsWith(d.source_name))||'';
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
    if(!d.configured){
      $('gd').className='dot mock';$('gl').textContent='Testdaten-Modus';
      $('gi').textContent='KI-Analyse verwendet Testdaten. F\u00fcr echte Ergebnisse: KWB_GPUSTACK_URL in .env konfigurieren.';
      if($('img-mock-hint'))$('img-mock-hint').style.display='block';
    }else if(d.available){
      $('gd').className='dot on';$('gl').textContent='GPUStack: '+(d.models?.length||0)+' Modelle';
      gpuM=d.models||[];const cfg=d.config||{};
      $('gi').innerHTML='<div style="font-size:.7rem;font-family:monospace">'+gpuM.map(m=>'<div>'+esc(m)+'</div>').join('')+'</div>';
      for(const sid of['cfg-mt','cfg-mv']){$(sid).innerHTML=gpuM.map(m=>safeOpt(m,m)).join('')}
      $('cfg-models').textContent='Text: '+(cfg.gpustack_model_text||'—')+' / Vision: '+(cfg.gpustack_model_vision||'—')
    }else{
      $('gd').className='dot off';$('gl').textContent='GPUStack: nicht erreichbar';
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
  const key = $('img-preset').value;
  if(key !== 'custom') $('img-sp').value = PRESETS[key] || '';
}

async function uploadImages(){
  const imgExts = /\.(jpg|jpeg|png|tif|tiff|webp)$/i;
  const fileFiles = [...($('img-files').files || [])];
  const folderFiles = [...($('img-folder').files || [])].filter(f => imgExts.test(f.name));
  const allFiles = [...fileFiles, ...folderFiles];
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
    hp();
  }catch(e){$('img-upload-status').textContent='Fehler: '+e;hp();}
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
  return uploadedImages;
}

function renderImgGrid(){
  const grid = $('img-grid');
  const empty = $('img-list-empty');
  if(!uploadedImages.length){empty.style.display='block';grid.innerHTML='';return}
  const shown = _filteredImages();
  if(!shown.length){empty.style.display='block';empty.textContent='Keine Bilder für den gewählten Filter.';grid.innerHTML='';return}
  empty.style.display='none';
  empty.textContent='Noch keine Bilder hochgeladen.';
  grid.innerHTML = shown.map(function(img){
    return '<div style="border:1px solid var(--brd);border-radius:4px;padding:.4rem;font-size:.72rem;background:#fafafa;display:flex;flex-direction:column;gap:.25rem">'
      +'<img src="/api/images/'+esc(img.id)+'/data" alt="'+esc(img.filename)+'"'
      +' style="width:100%;height:140px;object-fit:contain;background:#eee;border-radius:3px;display:block"'
      +' onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'
      +'<div style="display:none;height:140px;align-items:center;justify-content:center;background:#eee;border-radius:3px;color:#aaa;font-size:.68rem">Vorschau n/v</div>'
      +'<div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+esc(img.filename)+'">'+esc(img.filename)+'</div>'
      +'<div style="color:#888;font-size:.65rem">'+((img.size_bytes/1024).toFixed(1))+' KB &middot; '+esc(img.media_type||'')+'</div>'
      +'<div><span class="bg '+(img.analyzed?'ac':'no')+'">'+esc(img.analyzed?'analysiert':'ausstehend')+'</span></div>'
      +'</div>'}).join('');
}

async function analyzeImages(){
  if(!uploadedImages.length){alert('Erst Bilder hochladen.');return}
  const mod = $('img-model').value;
  const sp_text = $('img-sp').value;
  const ids = uploadedImages.map(i=>i.id);
  sp('Bildanalyse läuft…', ids.length + ' Bild(er)');
  try{
    const r = await fetch('/api/images/analyze',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({image_ids:ids, model:mod, system_prompt:sp_text, prompt_task:$('img-task').value})
    });
    const data = await r.json();
    if(data.error){$('img-results-empty').textContent='Fehler: '+data.error;hp();return}
    renderImgResults(data.results||[]);
    hp();
    // Persistence hint
    if((data.results||[]).some(r=>r.result))$('img-results-empty').textContent='';
    // Update analyzed flag
    (data.results||[]).forEach(res=>{
      const img = uploadedImages.find(i=>i.id===res.id);
      if(img) img.analyzed = !!res.result;
    });
    renderImgGrid();
  }catch(e){$('img-results-empty').textContent='Fehler: '+e;hp();}
}

function renderImgResults(results){
  latestImageResults = results || [];
  applyImageFilter();
}

function applyImageFilter(){
  const el=$('img-results');
  const empty=$('img-results-empty');
  const filter=($('img-review-filter')&&$('img-review-filter').value)||'all';
  filteredImageResults = latestImageResults.filter(function(res){
    return filter==='all' || (res.review_status||'pending')===filter;
  });
  if(!filteredImageResults.length){empty.style.display='block';el.innerHTML='';return}
  empty.style.display='none';
  el.innerHTML = filteredImageResults.map(function(res, idx){
    const originalIdx = latestImageResults.indexOf(res);
    if(res.error) return '<div class="card" style="border-color:#e55"><strong>'+esc(res.id||res.filename||'')+'</strong><br><span style="color:#c00">'+esc(res.error)+'</span></div>';
    var r = res.result || {};
    var status = res.review_status || 'pending';
    return '<div class="card" style="margin-bottom:.5rem">'
      +'<strong style="font-size:.8rem">'+esc(res.filename||res.id)+'</strong>'
      +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:.4rem;margin:.35rem 0">'
      +'<input type="text" id="img-record-'+idx+'" placeholder="record_id (optional)" value="'+esc(res.record_id||'')+'">'
      +'<select id="img-status-'+idx+'"><option value="pending"'+(status==='pending'?' selected':'')+'>pending</option><option value="accepted"'+(status==='accepted'?' selected':'')+'>accepted</option><option value="rejected"'+(status==='rejected'?' selected':'')+'>rejected</option></select>'
      +'</div>'
      +'<textarea id="img-desc-'+idx+'" style="height:4rem">'+esc(r.description||'')+'</textarea>'
      +'<p style="font-size:.78rem;margin:.3rem 0">Objekte: '+esc((r.objects||[]).join(', '))+'</p>'
      +(r.period?'<div style="font-size:.72rem;color:#555">Periode: '+esc(r.period)+'</div>':'')
      +(r.confidence?'<div style="font-size:.65rem;color:#888">Konfidenz: '+(r.confidence*100).toFixed(0)+'%</div>':'')
      +'<input type="text" id="img-comment-'+idx+'" placeholder="Kommentar" value="'+esc(res.review_comment||'')+'" style="margin-top:.25rem">'
      +'<input type="text" id="img-reviewer-'+idx+'" placeholder="Reviewer" value="'+esc(res.reviewer||'')+'" style="margin-top:.25rem">'
      +'<div style="display:flex;gap:.3rem;margin-top:.35rem">'
      +'<button class="btn sm" onclick="saveImageReview('+idx+',\'pending\')">💾 anpassen</button>'
      +'<button class="btn sm" style="background:var(--ok)" onclick="saveImageReview('+idx+',\'accepted\')">✅ bestätigen</button>'
      +'<button class="btn sm" style="background:var(--crit)" onclick="saveImageReview('+idx+',\'rejected\')">🗑 verwerfen</button>'
      +'</div>'
      +'<div style="font-size:.65rem;color:#777;margin-top:.2rem">ID: '+esc(res.id)+' • #'+(originalIdx+1)+'</div>'
      +'</div>';
  }).join('');
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
  const mod=$('img-model').value;
  const ids=uploadedImages.map(i=>i.id);
  sp('OCR läuft…',ids.length+' Bild(er)');
  try{
    const r=await fetch('/api/images/ocr',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({image_ids:ids,model:mod,system_prompt:$('ocr-sp').value||''})
    });
    const data=await r.json();
    if(data.error){$('img-results-empty').textContent='OCR-Fehler: '+data.error;hp();return;}
    const el=$('img-results');
    el.innerHTML='<h3 style="margin:.5rem 0">OCR-Ergebnisse ('+(data.processed||0)+'/'+(data.total||0)+')</h3>'
      +(data.results||[]).map(function(res){
        if(res.error)return '<div style="border:1px solid #e55;padding:.4rem;margin-bottom:.3rem;border-radius:4px">'+esc(res.id)+': '+esc(res.error)+'</div>';
        var rc=res.result||{};var txt=rc.transcription||rc.text||'(kein Text erkannt)';
        return '<div style="border:1px solid var(--brd);padding:.5rem;margin-bottom:.3rem;border-radius:4px">'
          +'<strong style="font-size:.78rem">'+esc(res.filename||res.id)+'</strong> '
          +(rc.text_found?'<span class="bg ac">Text</span>':'<span class="bg no">Kein Text</span>')
          +'<div style="font-family:monospace;font-size:.75rem;margin:.3rem 0;padding:.3rem;background:var(--pw);border-radius:3px">'+esc(txt)+'</div>'
          +(rc.overall_confidence?'<div style="font-size:.68rem;color:#888">Konfidenz: '+(rc.overall_confidence*100).toFixed(0)+'%</div>':'')
          +'</div>';
      }).join('');
    $('img-results-empty').textContent='';
  }catch(e){$('img-results-empty').textContent='Fehler: '+e;}finally{hp();}
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

// === CATALOG ===
function renderCatalog(){$('cat-body').innerHTML=CATALOG.map(c=>'<tr><td style="font-size:.62rem">'+esc(c.id)+'</td><td style="font-weight:600">'+esc(c.name)+'</td><td style="font-size:.68rem">'+esc(c.module)+'</td><td><span class="bg '+(c.status==='done'?'ac':c.status==='partial'?'pl':'no')+'">'+esc(c.status)+'</span></td><td style="font-size:.68rem">'+esc(c.tests||'—')+'</td><td style="font-size:.7rem;color:#666">'+esc(c.note||'')+'</td></tr>').join('')}

// === PROGRESS ===
function sp(t,x){$('pt').textContent=t;$('pp').textContent=x||'';$('po').classList.add('a')}
function hp(){$('po').classList.remove('a')}

// === INIT ===
function showInitError(label){const b=document.createElement('div');b.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#fee2e2;color:#991b1b;padding:.4rem 1rem;font-size:.78rem;border-top:2px solid #f87171';b.textContent='⚠ UI-Initialisierung fehlgeschlagen'+(label?': '+label:'')+' – bitte Konsole prüfen';document.body.appendChild(b)}
(function(){
  const failed=[];
  [initNav,initTabs,initUpload,initPanels].forEach(fn=>{try{fn()}catch(err){console.error('[init]',fn.name,err);failed.push(fn.name)}});
  if(failed.length)showInitError(failed.join(', '));
  try{loadPreset()}catch(err){console.error('[init] loadPreset',err)}
  try{applyImgPreset()}catch(err){console.error('[init] applyImgPreset',err)}
  try{applyActionPreset('ner');applyActionPreset('scan');applyActionPreset('edtf');applyActionPreset('ocr')}catch(err){console.error('[init] applyActionPreset',err)}
  try{refreshReviewStats()}catch(err){console.error('[init] refreshReviewStats',err)}
  try{const ct=$('cfg-tasks');if(ct)ct.innerHTML=Object.values(TASKS).map(t=>'<div class="ft"><span class="bg ac">'+esc(t.type||'')+'</span><div><strong>'+esc(t.name)+'</strong><br><span class="d">'+esc(t.description||'')+'</span></div></div>').join('')}catch(err){console.error('[init] cfg-tasks',err)}
  try{renderCatalog()}catch(err){console.error('[init] renderCatalog',err)}
  try{chkGPU()}catch(err){console.error('[init] chkGPU',err)}
  try{updWS()}catch(err){console.error('[init] updWS',err)}
  try{loadImages()}catch(err){console.error('[init] loadImages',err)}
  try{loadTermsDict()}catch(err){console.error('[init] loadTermsDict',err)}
})();
