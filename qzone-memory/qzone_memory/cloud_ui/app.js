'use strict';
const $ = id => document.getElementById(id);
let csrf = '', current = null, polling = null, busy = false;
const phases = {login:'等待 QQ 扫码',collecting:'正在整理回忆',exporting:'正在生成离线文件',done:'归档已生成',partial:'本轮结果已保存',error:'任务未完成',cancelled:'已取消'};
async function api(path, method='GET', body) {
  const response = await fetch(path,{method,credentials:'same-origin',headers:method==='GET'?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})});
  let data; try {data=await response.json();}catch {throw new Error('服务暂时不可用，请稍后重试');}
  if(!response.ok)throw new Error(data.error||'请求未完成，请重试');
  return data;
}
function render(job){
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
  $('stop').textContent=job.phase==='login'?'取消本次扫码':'暂停并生成已有结果';
  $('refresh-qr').hidden=!job.can_refresh;
  $('refresh-qr').disabled=job.active&&!hasQR;
  $('refresh-qr').textContent=job.active?'刷新二维码':'重新扫码';
  $('start').disabled=job.active||!$('consent').checked;
  const p=job.progress||{};
  $('progress').textContent=p.label||p.stage||'';
  if(job.ready){
    const base='/jobs/'+encodeURIComponent(job.id);
    $('preview').href=base+'/preview/index.html';$('html').href=base+'/download/html';$('zip').href=base+'/download/zip';
    const parts=job.parts||[]; $('zip').hidden=parts.length!==1;
    $('zip-parts').replaceChildren();
    if(parts.length>1)for(const [i,part] of parts.entries()){const a=document.createElement('a');a.href=base+'/download/'+encodeURIComponent(part.kind);a.textContent='下载图片包 '+(i+1)+' / '+parts.length+'（'+(part.size/1024/1024).toFixed(1)+' MiB）';$('zip-parts').appendChild(a);}
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
$('stop').addEventListener('click',async()=>{try{await api('/api/jobs/'+current.id+'/stop','POST',{});$('message').textContent='正在停止并收尾，请稍候。';}catch(error){$('error').textContent=error.message;}});
$('delete').addEventListener('click',async()=>{
  if(!current)return;
  if(!window.confirm('删除本次云端数据？正在运行的任务也会停止，此操作无法恢复。'))return;
  try{await api('/api/jobs/'+current.id,'DELETE',{});if(polling)clearTimeout(polling);current=null;$('task').hidden=true;$('start').disabled=!$('consent').checked;$('error').textContent='本次数据已撤销访问；如有正在进行的网络请求，将在退出后完成清理。';}
  catch(error){$('error').textContent=error.message;}
});
(async()=>{try{const data=await api('/api/session');csrf=data.csrf;if(data.jobs.length)render(data.jobs.sort((a,b)=>b.expires-a.expires)[0]);}catch(error){$('error').textContent=error.message;}})();
