const $=id=>document.getElementById(id);
const PRESETS=__PRESETS_JSON__;
const TASKS=__TASKS_JSON__;
const CATALOG=__CATALOG_JSON__;

// Goobi metadata types (common)
const GOOBI_TYPES=[
  "CatalogIDDigital","TitleDocMain","Description","PublicationYear",
  "DocLanguage","singleDigCollection","Author","SubjectTopic",
  "PlaceOfPublication","Publisher","Format","Source",
];

let ufiles={},curRep=null,gpuM=[],nerData=[],edtfData=[];
let recordOffset=0,recordLimit=50,recordTotal=0;
let nerStatusFilter='all', nerTypeFilter='all';
let fmMapping={}; // current field mapping state
let latestImageResults=[];
let filteredImageResults=[];

// === SECURITY ===
function esc(s){return s==null?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function safeOpt(val,label){return '<option value="'+esc(val)+'">'+esc(label)+'</option>'}
function dl(name,content,type){const b=new Blob([content],{type});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click()}

// === NAV ===
document.querySelector('.nav').onclick=e=>{if(!e.target.classList.contains('nt'))return;const p=e.target.dataset.p;document.querySelectorAll('.nt').forEach(t=>t.classList.toggle('a',t.dataset.p===p));document.querySelectorAll('.pg').forEach(x=>x.classList.toggle('a',x.dataset.p===p))};
function bindTabs(id){const el=$(id);if(!el)return;el.onclick=e=>{if(!e.target.classList.contains('tab'))return;const t=e.target.dataset.t;e.currentTarget.querySelectorAll('.tab').forEach(x=>x.classList.toggle('a',x.dataset.t===t));e.currentTarget.parentElement.querySelectorAll('[data-t].tp').forEach(x=>x.classList.toggle('a',x.dataset.t===t))}}
bindTabs('dt');

// === UPLOAD ===
const uz=$('uz'),fi=$('fi');
fi.onchange=e=>hf(e.target.files);uz.ondragover=e=>{e.preventDefault();uz.classList.add('dr')};uz.ondragleave=()=>uz.classList.remove('dr');uz.ondrop=e=>{e.preventDefault();uz.classList.remove('dr');hf(e.dataTransfer.files)};
function hf(files){for(const f of files)ufiles[f.name]=f;rfl()}
function rfl(){
  const n=Object.keys(ufiles);$('fc').style.display=n.length?'block':'none';
  $('fcl').innerHTML=n.map(x=>'<div class="ci"><input type="checkbox" checked value="'+esc(x)+'" class="fcb"><span>'+esc(x)+'</span><span class="m">'+(ufiles[x].size/1024).toFixed(0)+'KB</span></div>').join('');
}
function populateDS(){
  const n=Object.keys(ufiles);
  for(const id of['ner-ds','scan-ds','edtf-ds','exp-ds','exp-csv-ds','exp-ld-ds','fm-ds']){
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
$('exp-ds').onchange=()=>loadRecords(true);

// === FIELD MAPPING ===
let fmCols=[];
async function loadFMCols(){
  const ds=$('fm-ds').value;
  if(!ds){$('fm-table-wrap').style.display='none';return}
  try{
    const d=await(await fetch('/api/dataset/'+encodeURIComponent(ds)+'/columns')).json();
    if(d.error)return;
    fmCols=d.columns;
    // Load existing mapping
    const ex=await(await fetch('/api/workspace/field-mapping')).json();
    fmMapping=ex.mapping||{};
    renderFMTable();
    $('fm-table-wrap').style.display='block';
  }catch(e){}
}
function renderFMTable(){
  const typeOpts=GOOBI_TYPES.map(t=>safeOpt(t,t)).join('');
  $('fm-body').innerHTML=fmCols.map(c=>{
    const mapped=fmMapping[c.name];
    const label=mapped?(Array.isArray(mapped)?mapped[0]:mapped):'';
    const type=mapped?(Array.isArray(mapped)?mapped[1]:''):'';
    return '<tr>'+
      '<td><strong>'+esc(c.name)+'</strong><br><span style="font-size:.65rem;color:#888">'+Math.round(c.fill_rate*100)+'%</span></td>'+
      '<td><input type="text" id="fm-lbl-'+esc(c.name)+'" value="'+esc(label)+'" placeholder="z.B. Titel" style="width:120px"></td>'+
      '<td><select id="fm-typ-'+esc(c.name)+'" style="width:160px"><option value="">— kein Export —</option>'+typeOpts+'</select></td>'+
      '<td><button class="btn sm" onclick="clearFMRow(\''+esc(c.name)+'\')">✕</button></td>'+
    '</tr>';
  }).join('');
  // Set current type values
  fmCols.forEach(c=>{
    const mapped=fmMapping[c.name];
    if(mapped){
      const type=Array.isArray(mapped)?mapped[1]:mapped;
      const sel=$('fm-typ-'+c.name);
      if(sel)sel.value=type;
    }
  });
}
function clearFMRow(col){
  const lbl=$('fm-lbl-'+col);const typ=$('fm-typ-'+col);
  if(lbl)lbl.value='';if(typ)typ.value='';
}
async function saveFM(){
  const mapping={};
  fmCols.forEach(c=>{
    const lbl=$('fm-lbl-'+c.name);const typ=$('fm-typ-'+c.name);
    if(lbl&&typ&&typ.value){
      mapping[c.name]=[lbl.value||typ.value,typ.value];
    }
  });
  try{
    await fetch('/api/workspace/field-mapping',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mapping})});
    fmMapping=mapping;
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
      system_prompt:$('ner-sp').value||$('cfg-sys').value})})).json();
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
      system_prompt:$('scan-sp').value||$('cfg-sys').value})})).json();
    if(r.error)throw Error(r.error);renderScan(r);renderRunMetrics('scan-metrics',r.run_metrics)
  }catch(e){alert(e.message)}finally{hp()}}


function renderScan(r){$('scan-r').style.display='block';const issues=r.issues||[];
  if(!issues.length){$('scan-body').innerHTML='<p style="color:var(--ok)">Keine problematischen Begriffe gefunden.</p>';return}
  $('scan-body').innerHTML=issues.map(i=>'<div class="fd '+(i.severity==='high'?'critical':'warning')+'">'+
    '<strong>'+esc(i.term||'?')+'</strong> <span style="font-size:.7rem;color:#888">'+esc(i.record_id||'')+'</span>'+
    '<div style="font-size:.75rem">'+esc(i.reason||'')+'</div>'+
    (i.suggestion?'<div style="font-style:italic;color:var(--ac);font-size:.73rem">→ '+esc(i.suggestion)+'</div>':'')+
  '</div>').join('')}

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
function applyActionPreset(action){const map={ner:['ner-preset','ner-sp'],scan:['scan-preset','scan-sp'],edtf:['edtf-preset','edtf-sp'],ocr:['ocr-preset','ocr-sp']};const m=map[action];if(!m)return;const k=$(m[0]).value;if(k!=='custom')$(m[1]).value=PRESETS[k]||'';}
async function testConn(){sp('Test …','');$('cfg-test').style.display='none';
  try{const r=await(await fetch('/api/gpu/test',{method:'POST'})).json();
    $('cfg-test').style.display='block';$('cfg-test').textContent=JSON.stringify(r,null,2)
  }catch(e){$('cfg-test').style.display='block';$('cfg-test').textContent='Fehler: '+e.message}finally{hp()}}

// === REPORT ===
function rrep(d){$('de').style.display='none';$('dr').style.display='block';const s=d.summary||{};
  $('dsg').innerHTML='<div class="mt su"><div class="v">'+(s.total_records||0).toLocaleString()+'</div><div class="l">Records</div></div><div class="mt"><div class="v">'+(s.total_columns||0)+'</div><div class="l">Spalten</div></div><div class="mt cr"><div class="v">'+(s.critical||0)+'</div><div class="l">Kritisch</div></div><div class="mt wr"><div class="v">'+(s.warnings||0)+'</div><div class="l">Warnungen</div></div><div class="mt in"><div class="v">'+(s.info||0)+'</div><div class="l">Hinweise</div></div>';
  const fs=d.findings||[];
  $('fbar').innerHTML='<div class="fb2 a" onclick="ff(\'all\',this)">Alle ('+fs.length+')</div><div class="fb2" onclick="ff(\'critical\',this)">Kritisch ('+(s.critical||0)+')</div><div class="fb2" onclick="ff(\'warning\',this)">Warnungen ('+(s.warnings||0)+')</div><div class="fb2" onclick="ff(\'info\',this)">Hinweise ('+(s.info||0)+')</div>';
  rfnd(fs);rprf(d.datasets||[]);rcd(d.datasets||[]);$('mdx').value=d.markdown||''}
function ff(f,b){document.querySelectorAll('#fbar .fb2').forEach(x=>x.classList.remove('a'));if(b)b.classList.add('a');rfnd(f==='all'?(curRep?.findings||[]):(curRep?.findings||[]).filter(x=>x.severity===f))}
function rfnd(fs){if(!fs.length){$('flist').textContent='Keine Findings.';return}
  $('flist').innerHTML=fs.map(f=>'<div class="fd '+esc(f.severity)+'"><span class="sv '+esc(f.severity)+'">'+esc(f.severity)+'</span> <span style="font-size:.62rem;color:#888">'+esc(f.category)+'</span><div style="margin-top:.1rem">'+esc(f.message)+'</div>'+(f.column?'<div style="font-size:.68rem;color:#666">Spalte: '+esc(f.column)+'</div>':'')+(f.suggestion?'<div style="font-style:italic;color:var(--ac);font-size:.73rem">→ '+esc(f.suggestion)+'</div>':'')+'</div>').join('')}
function rprf(ds){$('parea').innerHTML=ds.map(d=>'<h3 style="margin:.5rem 0 .3rem">'+esc(d.source_name)+'</h3><p style="font-size:.73rem;color:#666">'+((d.row_count||0).toLocaleString())+' Zeilen, '+d.column_count+' Spalten, ID: <code>'+esc(d.id_column||'—')+'</code></p><table class="pt"><thead><tr><th>Spalte</th><th>Gefüllt</th><th>Unique</th><th>Beispiel</th></tr></thead><tbody>'+(d.columns||[]).map(c=>'<tr><td>'+esc(c.name)+'</td><td><span class="fb0" style="width:'+Math.round(c.fill_rate*50)+'px;background:'+(c.fill_rate>.8?'var(--ok)':c.fill_rate>.3?'var(--warn)':'var(--crit)')+'"></span>'+Math.round(c.fill_rate*100)+'%</td><td>'+(c.unique_count||0).toLocaleString()+'</td><td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc((c.sample_values?.[0]||'—').substring(0,40))+'</td></tr>').join('')+'</tbody></table>').join('')}
function rcd(ds){$('cdarea').innerHTML=ds.map(d=>'<h3 style="margin:.5rem 0 .3rem">'+esc(d.source_name)+'</h3><table class="pt"><thead><tr><th>Spalte</th><th>Gefüllt</th><th>Unique</th><th>Beschreibung</th></tr></thead><tbody>'+(d.columns||[]).map(c=>{const sm=(c.sample_values||[]).slice(0,3).join(', ');return'<tr><td><strong>'+esc(c.name)+'</strong></td><td>'+Math.round(c.fill_rate*100)+'%</td><td>'+c.unique_count+'</td><td style="font-size:.73rem">'+(c.fill_rate<.01?'Fast leer':Math.round(c.fill_rate*100)+'% gefüllt. Bsp: '+esc(sm))+'</td></tr>'}).join('')+'</tbody></table>').join('')}

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
function renderCatalog(){$('cat-body').innerHTML=CATALOG.map(c=>'<tr><td style="font-size:.62rem">'+esc(c.id)+'</td><td style="font-weight:600">'+esc(c.name)+'</td><td style="font-size:.68rem">'+esc(c.module)+'</td><td><span class="bg '+(c.status==='done'?'ac':c.status==='partial'?'pl':'no')+'">'+esc(c.status_label)+'</span></td><td style="font-size:.68rem">'+esc(c.tests||'—')+'</td><td style="font-size:.7rem;color:#666">'+esc(c.note||'')+'</td></tr>').join('')}

// === PROGRESS ===
function sp(t,x){$('pt').textContent=t;$('pp').textContent=x||'';$('po').classList.add('a')}
function hp(){$('po').classList.remove('a')}

// === INIT ===
(function(){loadPreset(); applyImgPreset(); applyActionPreset('ner'); applyActionPreset('scan'); applyActionPreset('edtf'); applyActionPreset('ocr'); refreshReviewStats();
  $('cfg-tasks').innerHTML=Object.values(TASKS).map(t=>'<div class="ft"><span class="bg ac">'+esc(t.type||'')+'</span><div><strong>'+esc(t.name)+'</strong><br><span class="d">'+esc(t.description||'')+'</span></div></div>').join('');
  renderCatalog();chkGPU();updWS();loadImages()})();
