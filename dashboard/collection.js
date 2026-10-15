// Daily collection keeps facts, source coverage and routing separate from causal review.
let collectionPlan = null, collectionBatches = [], collectionReport = null;
let collectionTab = 'coverage', collectionCategory = 'TECH', collectionSource = null;
let collectionEditing = null, collectionMode = null, collectionInbox = [];
let discoveryStatus = 'All';
let discoverySource = 'All', discoveryPage = 0;
const discoveryNames = {Pending:'待读正文',Blocked:'读取受阻',Linked:'已关联原文',Excluded:'已排除'};
const coverageNames = {Unreviewed:'未检查',Partial:'部分覆盖',Blocked:'入口受阻',Complete:'登记覆盖完成'};
const routeNames = {NewParent:'新事件候选',EventUpdate:'既有事件新增信息',MarketState:'市场反馈',Background:'背景资料',Pending:'待核实'};
const relationNames = {InWindow:'窗口内公开',Late:'早于窗口 · 补录',AfterCutoff:'晚于截止 · 转下一批',TimeUnknown:'公开时间未核实'};
const reviewNames = {NoChange:'未发现新增信息',NewInformation:'发现新增信息',Pending:'仍待核实'};
function categoryLabel(value){return categoryNames[categories.indexOf(value)] || value;}
function collectionLocalTime(value){const date=new Date(value);return Number.isNaN(date.getTime())?'':new Date(date.getTime()+8*3600000).toISOString().slice(0,19);}
function collectionNow(){return collectionLocalTime(new Date().toISOString());}
function collectionPublishedTime(value){if(!value)return '未核实';if(/^\d{4}-\d{2}-\d{2}$/.test(value))return `日期级：${value}（时刻待核实）`;return /T\d{2}:\d{2}/.test(value)&&!Number.isNaN(new Date(value).getTime())?datetime(value):`时间待核实：${value}`;}
function collectionField(name,label,type='text',required=false,value=''){return `<div class="field"><label>${esc(label)}<input name="${esc(name)}" type="${type}" ${type==='datetime-local'?'step="1"':''} ${type==='number'?'min="0" step="1"':''} ${required?'required':''} value="${esc(value)}"></label></div>`;}
function collectionArea(name,label,required=false,value=''){return `<div class="field"><label>${esc(label)}<textarea name="${esc(name)}" ${required?'required':''}>${esc(value)}</textarea></label></div>`;}
function collectionSelect(name,label,values,names=values,value='',required=true){return `<div class="field"><label>${esc(label)}<select name="${esc(name)}" ${required?'required':''}><option value="">请选择</option>${values.map((v,i)=>`<option value="${esc(v)}" ${value===v?'selected':''}>${esc(names[i])}</option>`).join('')}</select></label></div>`;}
function collectionForm(id,fields,label='追加登记'){return `<form id="${id}" class="collection-form">${fields}<div class="submit"><button class="primary" type="submit">${label}</button><small>仅追加记录；时间均为北京时间</small></div></form>`;}
function collectionEvidence(data){return String(data.get('evidence')||'').split('\n').map(v=>v.trim()).filter(Boolean);}
function collectionLink(url,label){return /^https?:\/\//i.test(url||'')?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`:esc(label);}
function batchLabel(batch){return `${datetime(batch.window_start)} → ${datetime(batch.cutoff)}`;}

async function openCollections(){
  view='collection';const sequence=++loadSequence;$('detail').innerHTML='<h2>每日收集</h2><p>正在读取收集窗口与来源清单…</p>';
  const values=await Promise.all([api('/api/collection-plan'),api('/api/collections')]);
  if(sequence!==loadSequence||view!=='collection')return;
  collectionPlan=values[0];collectionBatches=values[1];
  const wanted=collectionReport?.batch?.batch_id;
  const batch=collectionBatches.find(b=>b.batch_id===wanted)||collectionBatches[0];
  if(batch)await loadCollection(batch.batch_id);else {collectionReport=null;renderCollection();}
}
async function loadCollection(id){
  view='collection';const sequence=++loadSequence;
  $('detail').innerHTML='<h2>每日收集与分流</h2><p>正在读取所选批次…</p>';
  const report=await api('/api/collection?id='+encodeURIComponent(id));
  if(sequence!==loadSequence||view!=='collection')return;
  collectionReport=report;collectionEditing=null;collectionMode=null;
  discoveryPage=0;
  if(!report.discovery?.leads.some(l=>l.source_id===discoverySource))discoverySource='All';
  if(!report.coverage.some(c=>c.category===collectionCategory))collectionCategory=report.coverage[0]?.category;
  if(!report.coverage.find(c=>c.category===collectionCategory)?.required_sources.some(s=>s.source_id===collectionSource))collectionSource=null;
  renderCollection();
}
function renderCollection(){
  if(view!=='collection')return;++loadSequence;
  const report=collectionReport,defaults=collectionPlan.defaults;
  $('detail').innerHTML=`<div class="collection-heading"><div><h2>每日收集与分流</h2><p>检查原文、记录信息增量，再决定进入哪类研究记录。</p></div><button id="collection-refresh">刷新清单</button></div>
  <div class="collection-caution">来源链接是登记入口。打开链接或保存一条检查记录，不等于已自动联网扫描。空白类别不代表没有事件；收集完成也不生成方向、市场确认或交易资格。</div>
  ${collectionBatches.length?`<div class="field"><label for="collection-picker">选择固定截止时刻的收集批次</label><select id="collection-picker">${collectionBatches.map(b=>`<option value="${esc(b.batch_id)}" ${report?.batch.batch_id===b.batch_id?'selected':''}>${esc(batchLabel(b))} · ${esc(b.batch_id)}</option>`).join('')}</select></div>`:''}
  <details ${report?'':'open'} id="collection-create"><summary>建立新批次 · 前一天到现在</summary><p>周一默认包含周末；完整节假日历尚未接入，节后由Codex核对休市期并扩大起点。已有批次的起点和截止时刻固定，新时刻请建立新批次。</p>${collectionForm('collection-create-form',`<div class="grid">${collectionField('window_start','收集起点','datetime-local',true,collectionLocalTime(defaults.window_start))}${collectionField('cutoff','固定截止时刻（Cutoff）','datetime-local',true,collectionLocalTime(defaults.cutoff))}</div>${collectionArea('window_reason','窗口依据 / 节假日扩大说明',true,defaults.window_reason)}`,'建立收集批次')}</details>
  ${report?collectionReportBody(report):'<p class="empty-state">尚未建立收集批次。创建后，14类来源覆盖、信息分流和既有事件复核都从待检查开始。</p>'}`;
  $('collection-refresh').onclick=()=>openCollections().catch(e=>message(e.message,true));
  if($('collection-picker'))$('collection-picker').onchange=ev=>loadCollection(ev.target.value).catch(e=>message(e.message,true));
  bindCollectionSubmit('collection-create-form',d=>api('/api/collection',{window_start:chinaTime(d.get('window_start')),cutoff:chinaTime(d.get('cutoff')),window_reason:d.get('window_reason')}),async (result,sequence)=>{
    const batches=await api('/api/collections');if(sequence!==loadSequence||view!=='collection')return;
    collectionBatches=batches;collectionTab='coverage';await loadCollection(result.id);
  });
  if(!report)return;
  $('collection-download').onclick=()=>downloadCollection(report);
  document.querySelectorAll('[data-collection-tab]').forEach(b=>b.onclick=()=>{collectionTab=b.dataset.collectionTab;collectionEditing=null;collectionMode=null;renderCollection();});
  if(collectionTab==='coverage')bindCoverage();
  if(collectionTab==='information')bindCollectionInformation();
  if(collectionTab==='parents')bindParentFollowups();
  if(collectionTab==='discovery'){
    $('discovery-status').onchange=e=>{discoveryStatus=e.target.value;discoveryPage=0;renderCollection();};
    $('discovery-source').onchange=e=>{discoverySource=e.target.value;discoveryPage=0;renderCollection();};
    $('discovery-prev').onclick=()=>{discoveryPage--;renderCollection();};
    $('discovery-next').onclick=()=>{discoveryPage++;renderCollection();};
  }
}
function collectionReportBody(report){
  const batch=report.batch,c=report.counts;
  return `<div class="collection-window"><b>本批窗口：</b>${esc(batchLabel(batch))}<br><small>${esc(batch.window_reason)} · 建立于 ${esc(datetime(batch.known_at))} · 报告截至 ${esc(datetime(report.as_of))}</small></div>
  <div class="collection-metrics">${[['原始信息',c.information],['待分流',c.pending_triage],['未完成类别',c.missing_categories],['时间待核实',c.unknown_time],['待处理线索',c.unresolved_leads],['待复核事件',c.pending_parent_reviews]].map(([label,count])=>`<div><b>${count??0}</b><span>${label}</span></div>`).join('')}</div>
  <div class="collection-readiness ${report.ready?'complete':'incomplete'}"><div><strong>${report.ready?'本批登记与复核清单已完成':'本批仍有待处理事项'}</strong>${report.gaps?.length?`<ul>${report.gaps.map(g=>`<li>${esc(g)}</li>`).join('')}</ul>`:'<p>完成范围仅限本批登记入口及研究复核清单。</p>'}</div><button id="collection-download">下载报告 JSON</button></div>
  <div class="tabs">${[['coverage','① 来源覆盖'],['discovery','② 新闻线索'],['information','③ 信息分流'],['parents','④ 既有事件复核']].map(([key,label])=>`<button data-collection-tab="${key}" class="${collectionTab===key?'active':''}">${label}</button>`).join('')}</div>
  ${{coverage:renderCoverage,discovery:renderDiscovery,information:renderCollectionInformation,parents:renderParentFollowups}[collectionTab]()}`;
}
function renderDiscovery(){
  const report=collectionReport.discovery||{leads:[],counts:{},note:'旧批次尚未登记新闻线索。'};
  const filtered=report.leads.filter(l=>(discoveryStatus==='All'||l.status===discoveryStatus)&&(discoverySource==='All'||l.source_id===discoverySource));
  discoveryPage=Math.max(0,Math.min(discoveryPage,Math.ceil(filtered.length/50)-1));
  const leads=filtered.slice(discoveryPage*50,(discoveryPage+1)*50);
  const sources=new Map(collectionReport.batch.sources.map(s=>[s.source_id,s.name]));
  return `<h3>新闻线索 · 先保留，再决定是否读正文</h3><p>${esc(report.note)}</p>
  <p>${Object.entries(discoveryNames).map(([k,v])=>`${v} ${report.counts[k]||0}`).join(' · ')} · 部分读取 ${report.counts.PartialRead||0}</p>
  <div class="field"><label for="discovery-status">处理状态</label><select id="discovery-status">${[['All','全部线索'],...Object.entries(discoveryNames)].map(([k,v])=>`<option value="${k}" ${discoveryStatus===k?'selected':''}>${v}</option>`).join('')}</select></div>
  <div class="field"><label for="discovery-source">发现来源</label><select id="discovery-source"><option value="All">全部来源</option>${[...new Set(report.leads.map(l=>l.source_id))].map(k=>`<option value="${esc(k)}" ${discoverySource===k?'selected':''}>${esc(sources.get(k)||k)}</option>`).join('')}</select></div>
  <p>筛选后 ${filtered.length} 条 · 第 ${discoveryPage+1} / ${Math.max(1,Math.ceil(filtered.length/50))} 页（每页50条，全部记录仍保留） <button id="discovery-prev" ${discoveryPage===0?'disabled':''}>上一页</button> <button id="discovery-next" ${(discoveryPage+1)*50>=filtered.length?'disabled':''}>下一页</button></p>
  <p><small>由Codex追加处理；标题和日期线索未核实，点击链接不改变读取状态。这里只覆盖已登记发现，未收齐的分页仍是缺口。</small></p>
  ${leads.length?leads.map(l=>`<details class="source-card"><summary>${esc(discoveryNames[l.status])}${l.read_status==='Partial'?' · 部分读取':''} ｜ ${esc(l.title)}</summary>
    <p>${esc(sources.get(l.source_id)||l.source_id)} · ${collectionLink(l.url,'查看线索链接')} · ${collectionLink(l.index_url,'发现入口')}</p>
    <p>未核实日期线索：${esc(l.date_clue||'无')}<br>扫描注记：${esc(datetime(l.captured_at))}<br>实际登记：${esc(datetime(l.known_at))}</p>
    <p>${esc(l.resolution?.reason||'尚未读取或作出处理判断。')}</p>
    ${l.resolution?.information_id?`<p>关联资料：${esc(l.resolution.information_id)}；仍按原初筛规则处理。</p>`:''}
    <small>线索编号 ${esc(l.lead_id)}</small>
    ${report.history.filter(r=>r.lead_id===l.lead_id).map(r=>`<p><small>${esc(datetime(r.known_at))} · ${esc(discoveryNames[r.status])}：${esc(r.reason)}</small></p>`).join('')}</details>`).join(''):'<p class="empty-state">本筛选下没有已登记线索；不代表没有新闻。</p>'}`;
}
function renderCoverage(){
  const coverage=collectionReport.coverage;
  const currentCoverage=coverage.find(c=>c.category===collectionCategory)||coverage[0];
  if(!currentCoverage)return '<p>当前没有登记类别。</p>';
  const sources=currentCoverage.required_sources||[];
  const checks=new Map((currentCoverage.checks||[]).map(c=>[c.source_id,c]));
  const source=sources.find(s=>s.source_id===collectionSource);
  return `<div class="coverage-grid">${coverage.map(c=>`<button class="coverage-card ${collectionCategory===c.category?'active':''} ${c.status.toLowerCase()}" data-coverage-category="${esc(c.category)}"><strong>${esc(categoryLabel(c.category))}</strong><span>${esc(coverageNames[c.status])}</span><small>${c.required_sources.length-c.missing_source_ids.length} / ${c.required_sources.length} 入口已登记</small></button>`).join('')}</div>
  <h3>${esc(categoryLabel(currentCoverage.category))} · 逐个来源检查</h3><p>需要检查本批冻结清单中的每个入口。检索完成时刻必须不早于截止时刻，且命中全文已读；没有命中也要记录检索范围与证据。</p>
  <div class="source-list">${sources.map(s=>{const check=checks.get(s.source_id);return `<div class="source-row"><div><strong>${collectionLink(s.url,s.name)}</strong><small>${esc(s.source_id)} · ${esc(s.collect||'检查该类别的相关公开信息')}</small><span class="pill">${esc(coverageNames[check?.status||'Unreviewed'])}</span>${check?`<small>检查于 ${esc(datetime(check.searched_at))} · ${check.hit_count}条命中 · ${esc({Readable:'全文可读',NoHits:'无命中',Partial:'部分全文未读',Unavailable:'全文不可获取'}[check.fulltext_status]||check.fulltext_status)}</small><p>检查范围：${esc(check.search_scope)}</p>${check.gaps?`<p>${esc(check.gaps)}</p>`:''}${rawDetails(check)}`:''}</div><button data-check-source="${esc(s.source_id)}">${check?'追加检查':'登记检查'}</button></div>`;}).join('')||'<div class="warning">本类别没有登记来源，不能标记完整覆盖。</div>'}</div>
  ${source?`<div class="collection-editor"><h3>登记检查 · ${esc(source.name)}</h3><p>Codex核对原文后保存检查结果。此表单供补充记录，保存不会触发联网检索。</p>${collectionForm('source-check-form',`<div class="grid">${collectionSelect('status','本入口检查状态',['Partial','Blocked','Complete'],['部分覆盖 · 尚有缺口','受阻 · 无法完成','完成 · 本窗口已完整检查'],'Partial')}${collectionField('searched_at','实际完成检查时刻','datetime-local',true,collectionNow())}${collectionField('hit_count','检索命中条数（不是独立事件数）','number',true,'0')}${collectionSelect('fulltext_status','命中信息全文情况',['Partial','Unavailable','Readable','NoHits'],['部分全文未读','全文无法获取','命中全文已阅读','确认没有命中'],'Partial')}</div>${collectionArea('search_scope','实际检查的范围、关键词与时间口径',true)}${collectionArea('evidence','检查证据链接或可核查位置（每行一项）',true)}${collectionArea('gaps','尚未完成的范围 / 受阻原因（完成时留空）')}`)}</div>`:''}`;
}
function bindCoverage(){
  document.querySelectorAll('[data-coverage-category]').forEach(b=>b.onclick=()=>{collectionCategory=b.dataset.coverageCategory;collectionSource=null;renderCollection();});
  document.querySelectorAll('[data-check-source]').forEach(b=>b.onclick=()=>{collectionSource=b.dataset.checkSource;renderCollection();$('source-check-form')?.scrollIntoView({block:'nearest'});});
  if(!$('source-check-form'))return;
  const batchId=collectionReport.batch.batch_id,category=collectionCategory,sourceId=collectionSource;
  bindCollectionSubmit('source-check-form',d=>{
    const hitCount=Number(d.get('hit_count')),status=d.get('status'),gaps=String(d.get('gaps')||'');
    if(!Number.isInteger(hitCount)||hitCount<0)throw Error('命中条数须为非负整数');
    if(status==='Complete'&&(gaps.trim()||d.get('fulltext_status')!==(hitCount===0?'NoHits':'Readable')))throw Error('完整检查要求：有命中时全文已读，零命中时选“确认没有命中”，且没有未完成缺口');
    if(status!=='Complete'&&!gaps.trim())throw Error('部分覆盖或受阻必须说明缺口');
    return api('/api/source-check',{batch_id:batchId,category,source_id:sourceId,status,searched_at:chinaTime(d.get('searched_at')),search_scope:d.get('search_scope'),hit_count:hitCount,fulltext_status:d.get('fulltext_status'),evidence:collectionEvidence(d),gaps});
  });
}
function renderCollectionInformation(){
  const report=collectionReport;
  return `<div class="collection-heading"><p>每条原始信息保留原文时间、发现依据、重复提示和最新分流。分流不会替代因果或市场审核。</p><div class="actions"><button id="collection-add-new">新增并归档</button><button id="collection-add-existing">从信息池加入</button></div></div>
  ${collectionMode==='new'?renderCollectionNewInformation():collectionMode==='existing'?renderCollectionExistingInformation():''}
  ${report.information.map(i=>`<div class="record collection-item"><div class="collection-heading"><div><strong>${esc(i.title)}</strong><div class="id">${esc(i.information_id)} · ${esc(categoryLabel(i.category))}</div></div><div class="actions"><button data-archive-info="${esc(i.information_id)}">修订归档</button><button data-triage-info="${esc(i.information_id)}">${i.routing?'追加分流':'登记分流'}</button></div></div>
  <span class="pill">${esc(relationNames[i.temporal_relation])}</span>${i.found_late===true?`<span class="pill caution">${i.first_seen_at?'首次发现晚于截止':'录入晚于截止 · 实际首次发现待核实'}</span>`:''}<span class="pill">${esc(routeNames[i.routing?.route]||'尚未分流')}</span>
  <p>${esc(i.fact)}</p><p>原文公开：${esc(collectionPublishedTime(i.published_at))} · 实际首次发现：${esc(datetime(i.first_seen_at))} · 录入：${esc(datetime(i.recorded_at||i.observed_at))}</p>${i.first_seen_evidence?`<p>首次发现依据：${esc(i.first_seen_evidence)}</p>`:''}<p>核实情况：${esc(i.verification||'待补齐')}${i.collection_notes?' · '+esc(i.collection_notes):''}</p>${collectionLink(i.url,'查看原文')}
  ${i.duplicate_ids?.length?`<div class="warning">疑似同一原文：${i.duplicate_ids.map(esc).join('、')}。仅提示，未自动合并。</div>`:''}
  ${i.routing?`<p>分流依据：${esc(i.routing.reason)}${i.routing.event_id?' · '+esc(i.routing.event_id):''}<br><small>登记于 ${esc(datetime(i.routing.known_at))}</small></p>`:''}
  ${collectionEditing===i.information_id?(collectionMode==='revision'?renderArchiveRevision(i):renderTriageForm(i)):''}</div>`).join('')||'<p class="empty-state">尚无批次信息。请录入核实后的原文，或从信息池关联资料。</p>'}`;
}
function renderArchiveRevision(info){
  return `<div class="collection-editor"><h3>修订归档 · ${esc(info.title)}</h3><p>追加本批的主分类和归档说明，保留原关联历史。原文与已有分流判断保持独立。</p>${collectionForm('collection-revision-form',`${collectionSelect('category','修订后的主信息类别',categories,categoryNames,info.category)}${collectionArea('notes','归档说明 / 本次修订理由',false,info.collection_notes||'')}`,'追加归档修订')}</div>`;
}
function renderCollectionNewInformation(){
  const sourceList=collectionReport.batch.sources||collectionPlan.sources;
  return `<div class="collection-editor"><h3>新增原始信息并加入本批</h3><p>未知的公开时间或实际首次发现时间可留空。录入时间只表示此刻存入系统；填写实际首次发现时间时，必须提供依据。</p>${collectionForm('collection-information-form',`${collectionField('title','标题','text',true)}${collectionField('url','原文链接','url',true)}<div class="grid">${collectionSelect('source_id','来源入口',sourceList.map(s=>s.source_id),sourceList.map(s=>s.name))}${collectionSelect('category','主信息类别',categories,categoryNames,collectionCategory)}${collectionField('published_at','原文公开时间（未知可留空）','datetime-local')}${collectionField('first_seen_at','实际首次发现时间（未知可留空）','datetime-local')}</div>${collectionArea('first_seen_evidence','实际首次发现时间的依据（填时间时必填）')}${collectionArea('fact','原始事实',true)}${collectionArea('verification','核实情况与时间精度缺口',true)}${collectionArea('notes','本批归档说明 / 补录原因')}`,'保存原文并加入本批')}</div>`;
}
function renderCollectionExistingInformation(){
  const existingIds=new Set(collectionReport.information.map(i=>i.information_id));
  const available=collectionInbox.filter(i=>!existingIds.has(i.information_id));
  return `<div class="collection-editor"><h3>从信息池关联</h3><p>关联保留原始来源与时间，不修改原文。早于窗口的资料会标注补录，晚于截止的资料需要下一批继续检查。</p>${available.length?collectionForm('collection-existing-form',`${collectionSelect('information_id','选择原始信息',available.map(i=>i.information_id),available.map(i=>`${i.title} · ${i.information_id}`))}${collectionSelect('category','本批主信息类别',categories,categoryNames,collectionCategory)}${collectionArea('notes','关联理由 / 补录原因')}`,'加入本批'):'<p>当前信息池没有尚未加入本批的资料。</p>'}</div>`;
}
function renderTriageForm(info){
  const parents=events.filter(e=>e.scope!=='Historical');
  return `<div class="collection-editor"><h3>分流依据 · ${esc(info.title)}</h3><p>“新事件候选”需要先用页面顶部“创建事件”建立近期候选，再返回本批关联；已有正式因果审核的事件应使用“新增信息”。分流仅建立资料关系。</p>${collectionForm('collection-triage-form',`<div class="grid">${collectionSelect('route','信息去向',Object.keys(routeNames),Object.values(routeNames),info.routing?.route||'Pending')}${collectionSelect('event_id','关联近期事件（背景 / 待核实留空）',parents.map(e=>e.event_id),parents.map(e=>`${e.name} · ${e.event_id}`),info.routing?.event_id||'',false)}</div>${collectionArea('reason','为何是新逻辑、信息增量、价格反馈或背景？',true,info.routing?.reason||'')}${collectionArea('evidence','本条分流的事实证据（每行一项）',true,info.url||'')}`)}</div>`;
}
function bindCollectionInformation(){
  $('collection-add-new').onclick=()=>{collectionMode='new';collectionEditing=null;renderCollection();};
  $('collection-add-existing').onclick=async()=>{
    const sequence=++loadSequence,batchId=collectionReport.batch.batch_id;
    try{const infos=await api('/api/information');if(sequence!==loadSequence||view!=='collection'||collectionReport.batch.batch_id!==batchId)return;collectionInbox=infos;collectionMode='existing';collectionEditing=null;renderCollection();}catch(e){message(e.message,true);}
  };
  document.querySelectorAll('[data-triage-info]').forEach(b=>b.onclick=()=>{collectionEditing=b.dataset.triageInfo;collectionMode=null;renderCollection();});
  document.querySelectorAll('[data-archive-info]').forEach(b=>b.onclick=()=>{collectionEditing=b.dataset.archiveInfo;collectionMode='revision';renderCollection();});
  const batchId=collectionReport.batch.batch_id;
  if($('collection-information-form')){
    const editor=$('collection-information-form');
    editor.elements.first_seen_at.onchange=()=>{editor.elements.first_seen_evidence.required=!!editor.elements.first_seen_at.value;};
    bindCollectionSubmit('collection-information-form',d=>{
      if(d.get('first_seen_at')&&!String(d.get('first_seen_evidence')||'').trim())throw Error('实际首次发现时间需要可核查的依据；无法核实可将时间留空');
      return api('/api/information',{batch_id:batchId,category:d.get('category'),notes:d.get('notes'),title:d.get('title'),url:d.get('url'),source_id:d.get('source_id'),published_at:chinaTime(d.get('published_at')),first_seen_at:chinaTime(d.get('first_seen_at')),first_seen_evidence:d.get('first_seen_evidence'),fact:d.get('fact'),verification:d.get('verification')});
    });
  }
  if($('collection-existing-form'))bindCollectionSubmit('collection-existing-form',d=>api('/api/collection-item',{batch_id:batchId,information_id:d.get('information_id'),category:d.get('category'),notes:d.get('notes')}));
  if($('collection-revision-form')){const informationId=collectionEditing;bindCollectionSubmit('collection-revision-form',d=>api('/api/collection-item',{batch_id:batchId,information_id:informationId,category:d.get('category'),notes:d.get('notes')}));}
  if($('collection-triage-form')){
    const informationId=collectionEditing,editor=$('collection-triage-form');
    function updateParentRequirement(){const needsParent=['NewParent','EventUpdate','MarketState'].includes(editor.elements.route.value);editor.elements.event_id.required=needsParent;editor.elements.event_id.disabled=!needsParent;if(!needsParent)editor.elements.event_id.value='';}
    editor.elements.route.onchange=updateParentRequirement;updateParentRequirement();
    bindCollectionSubmit('collection-triage-form',d=>api('/api/triage',{batch_id:batchId,information_id:informationId,route:d.get('route'),event_id:d.get('event_id')||null,reason:d.get('reason'),evidence:collectionEvidence(d)}));
  }
}
function renderParentFollowups(){
  return `<p>逐一检查建立批次时的既有事件是否出现新增信息、失效证据或相反传导。无新增信息也需要范围与证据；“发现新增信息”还应把原文归档并分流。历史研究记录若出现在名单中，只登记研究后续，不作为近期事件改向。</p>${collectionReport.parent_followups.map(p=>`<div class="record"><div class="collection-heading"><div><strong>${esc(p.name)}</strong><div class="id">${esc(p.event_id)} · ${p.scope==='Historical'?'历史研究':'近期候选'}</div></div><div class="actions"><button data-parent-open="${esc(p.event_id)}">查看事件</button><button data-parent-review="${esc(p.event_id)}">${p.review?'追加复核':'登记复核'}</button></div></div><span class="pill">${esc(reviewNames[p.review?.result]||'尚未复核')}</span>${p.review?`<p>${esc(p.review.reason)}<br><small>登记于 ${esc(datetime(p.review.known_at))}</small></p>`:''}${collectionEditing===p.event_id?`<div class="collection-editor">${collectionForm('collection-parent-form',`${collectionSelect('result','本批后续检查结果',Object.keys(reviewNames),Object.values(reviewNames),p.review?.result||'Pending')}${collectionArea('reason','实际检查范围、新增 / 无新增判断与剩余缺口',true)}${collectionArea('evidence','检查证据链接或可核查位置（每行一项）',true)}`)}</div>`:''}</div>`).join('')||'<p>本批创建时没有需要复核的既有事件。</p>'}`;
}
function bindParentFollowups(){
  document.querySelectorAll('[data-parent-open]').forEach(b=>b.onclick=()=>choose(b.dataset.parentOpen).catch(e=>message(e.message,true)));
  document.querySelectorAll('[data-parent-review]').forEach(b=>b.onclick=()=>{collectionEditing=b.dataset.parentReview;renderCollection();});
  if($('collection-parent-form')){const batchId=collectionReport.batch.batch_id,eventId=collectionEditing;bindCollectionSubmit('collection-parent-form',d=>api('/api/parent-review',{batch_id:batchId,event_id:eventId,result:d.get('result'),reason:d.get('reason'),evidence:collectionEvidence(d)}));}
}
function bindCollectionSubmit(id,action,onSaved){
  const editor=$(id);if(!editor)return;const sequence=loadSequence,batchId=collectionReport?.batch.batch_id;
  editor.onsubmit=async ev=>{ev.preventDefault();const button=editor.querySelector('button[type="submit"]');button.disabled=true;
    try{const result=await action(new FormData(editor));message('已追加登记：'+result.id);if(sequence===loadSequence&&view==='collection'){if(onSaved)await onSaved(result,sequence);else if(collectionReport?.batch.batch_id===batchId)await loadCollection(batchId);}await refresh(false);}
    catch(e){message(e.message,true);}finally{button.disabled=false;}
  };
}
function downloadCollection(report){
  const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob);
  const link=document.createElement('a');link.href=url;link.download=`${report.batch.batch_id}-collection-report.json`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('daily-collection').onclick=()=>openCollections().catch(e=>message(e.message,true));
