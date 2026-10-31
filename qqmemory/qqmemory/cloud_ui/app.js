'use strict';
const $ = id => document.getElementById(id);
let csrf = '', current = null, polling = null, busy = false, pausePending = null;
const phases = {login:'等待 QQ 扫码',collecting:'正在整理回忆',stopping:'正在暂停并保存',exporting:'正在生成离线文件',done:'归档已生成',partial:'本轮结果已保存',error:'任务未完成',cancelled:'已取消'};
async function api(path, method='GET', body) {
  const response = await fetch(path,{method,credentials:'same-origin',headers:method==='GET'?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})});
  let data; try {data=await response.json();}catch {throw new Error('服务暂时不可用，请稍后重试');}
  if(!response.ok)throw new Error(data.error||'请求未完成，请重试');
  return data;
}
function duration(seconds){
  const n=Math.max(0,Math.floor(Number(seconds)||0));
  return n<60?n+' 秒':Math.floor(n/60)+' 分 '+n%60+' 秒';
}
function render(job){
  if(pausePending===job.id&&job.active&&['login','collecting'].includes(job.phase))job={...job,phase:'stopping',message:'暂停请求已提交，正在等待后台确认并保存已有成果…'};
  if(!job.active&&pausePending===job.id)pausePending=null;
  current=job;
  $('task').hidden=false;
  $('phase').textContent=phases[job.phase]||'正在处理';
  $('message').textContent=job.message;
  $('expiry').textContent='最晚保留至 '+new Date(job.expires*1000).toLocaleTimeString();
  const hasQR=typeof job.qr==='string'&&job.qr.startsWith('data:image/png;base64,');
  $('qr-area').hidden=!hasQR;
  if(hasQR){$('qr').src=job.qr;$('save-qr').href=job.qr;}else{$('qr').removeAttribute('src');$('save-qr').removeAttribute('href');}
  $('results').hidden=!job.ready;
  $('continue').hidden=!job.can_continue;
  $('html').hidden=!job.inline_ready;
  $('stop').hidden=!job.active;
  $('stop').disabled=['stopping','exporting'].includes(job.phase);
  $('stop').textContent=job.phase==='stopping'?'正在暂停并保存…':job.phase==='exporting'?'正在生成下载文件…':job.phase==='login'?'取消本次扫码':'暂停并生成已有结果';
  $('refresh-qr').hidden=!job.can_refresh;
  $('refresh-qr').disabled=job.active&&!hasQR;
  $('refresh-qr').textContent=job.active?'刷新二维码':'重新扫码';
  $('start').disabled=job.active||!$('consent').checked;
  const p=job.progress||{};
  const collecting=job.active&&['collecting','stopping','exporting'].includes(job.phase);
  $('live-status').hidden=!collecting;
  $('earliest-date').hidden=!collecting&&!job.ready;
  const c=job.counts||{};
  $('live-counts').textContent=Object.hasOwn(c,'posts')?'已取得 '+c.posts+' 条记录 · 图片已保存 '+c.photos_saved+' / 已发现 '+c.photos_found+' 张'+(c.photos_failed?' · 失败 '+c.photos_failed+' 张':'')+(c.details_pending?' · '+c.details_pending+' 条线索的互动待整理':''):'正在请求第一批内容，取得后会显示数量…';
  const formatDate=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value*1000));
  const oldest=c.earliest_published;
  $('earliest-date').textContent=oldest!=null?'已取得说说中最早的发布时间：'+formatDate(oldest)+'（北京时间）':'最早发布时间：暂未取得';
  if(c.earliest_interaction!=null)$('earliest-date').textContent+=' · ≈ 最早已知互动：'+formatDate(c.earliest_interaction)+'（北京时间，不代表发帖时间）';
  let timing='已用 '+duration(p.elapsed);
  if(job.collection_elapsed!=null){
    const left=Math.max(0,job.collection_limit-job.collection_elapsed);
    timing+=job.phase==='exporting'?' · 正在打包，完成后出现下载入口':left?' · 本轮采集时限剩余 '+duration(left)+'，之后还需生成文件':' · 已到本轮采集时限，正在收尾并生成文件';
  }
  if(Array.isArray(p.eta)&&p.eta.length===2)timing+=' · 当前阶段粗估还需 '+duration(p.eta[0])+'—'+duration(p.eta[1]);
  $('live-time').textContent=timing;
  const measured=p.total>0&&p.percent!=null;
  $('stage-meter').hidden=!collecting||!measured||job.phase==='stopping';
  if(measured)$('stage-meter').value=p.percent;
  $('progress').textContent=(p.label||p.stage||'')+(measured?' · '+p.done+' / '+p.total+'（'+p.percent+'%）':'')+(p.stage==='deep'?' · 扫描计划进度，非恢复比例':'');
  if(job.phase==='stopping')$('progress').textContent='停止新采集 → 收尾当前网络请求 → 生成已有结果；此过程仍需一点时间。';
  if(job.ready){
    const base='/jobs/'+encodeURIComponent(job.id);
    $('preview').href=base+'/preview/index.html';$('html').href=base+'/download/html';$('zip').href=base+'/download/zip';
    const parts=job.parts||[]; $('zip').hidden=parts.length!==1;
    $('zip-parts').replaceChildren();
    if(parts.length>1)for(const [i,part] of parts.entries()){const a=document.createElement('a');a.href=base+'/download/'+encodeURIComponent(part.kind);a.textContent=(i===0?'下载第 1 包：HTML + 首批图片':'下载第 '+(i+1)+' 包：后续图片')+' / 共 '+parts.length+' 包'+'（'+(part.size/1024/1024).toFixed(1)+' MiB）';$('zip-parts').appendChild(a);}
    $('stats').textContent='已保存 '+(job.stats.exported_posts||0)+' 条记录、'+(job.stats.exported_photos||0)+' 张照片。'+(job.incomplete?'本轮范围或时间有限，结果可能不完整。':'');
  }
  if(polling)clearTimeout(polling);
  if(job.active)polling=setTimeout(refresh,2000);
}
async function refresh(){
  if(!current||busy)return;
  busy=true;
  try{render(await api('/api/jobs/'+encodeURIComponent(current.id)));$('error').textContent='';}
  catch(error){$('error').textContent=error.message+'；可以刷新本页重新连接。';polling=setTimeout(refresh,5000);}
  finally{busy=false;}
}
$('consent').addEventListener('change',()=>{$('start').disabled=!$('consent').checked||Boolean(current&&current.active);});
$('start').addEventListener('click',async()=>{
  $('start').disabled=true;$('error').textContent='';
  try{render(await api('/api/jobs','POST',{consent:$('consent').checked}));}
  catch(error){$('error').textContent=error.message;$('start').disabled=!$('consent').checked;}
});
$('continue').addEventListener('click',async()=>{
  $('continue').disabled=true;
  try{render(await api('/api/jobs/'+current.id+'/continue','POST',{}));$('error').textContent='';}
  catch(error){$('error').textContent=error.message;}
  finally{$('continue').disabled=false;}
});
$('refresh-qr').addEventListener('click',async()=>{
  $('refresh-qr').disabled=true;
  try{render(await api('/api/jobs/'+current.id+'/refresh','POST',{}));$('error').textContent='';}
  catch(error){$('error').textContent=error.message;$('refresh-qr').disabled=false;}
});
$('stop').addEventListener('click',async()=>{
  const id=current.id;pausePending=id;render(current);
  try{const job=await api('/api/jobs/'+id+'/stop','POST',{});if(current&&current.id===id)render(job);$('error').textContent='';}
  catch(error){pausePending=null;if(current)render(current);$('error').textContent='暂停请求未确认：'+error.message+'。请重试暂停。';}
});
$('delete').addEventListener('click',async()=>{
  if(!current)return;
  if(!window.confirm('删除本次云端数据？正在运行的任务也会停止，此操作无法恢复。'))return;
  try{await api('/api/jobs/'+current.id,'DELETE',{});if(polling)clearTimeout(polling);current=null;$('task').hidden=true;$('start').disabled=!$('consent').checked;$('error').textContent='本次数据已撤销访问；如有正在进行的网络请求，将在退出后完成清理。';}
  catch(error){$('error').textContent=error.message;}
});
(async()=>{try{const data=await api('/api/session');csrf=data.csrf;if(data.jobs.length)render(data.jobs.sort((a,b)=>b.expires-a.expires)[0]);}catch(error){$('error').textContent=error.message;}})();
