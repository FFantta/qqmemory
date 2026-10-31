// Offline UI contract: account navigation and progress use synthetic archives only.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag='div'){this.tag=tag;this.dataset={};this.style={};this.children=[];this.attrs={};this.classList={toggle(){},add(){},remove(){}};this.open=false;this.value='collect';this.textContent=''}
 set id(value){this._id=value;elements.set(value,this)} get id(){return this._id}
 append(...values){this.children.push(...values)} prepend(...values){this.children.unshift(...values)}
 replaceChildren(...values){this.children=values} setAttribute(k,v){this.attrs[k]=v} removeAttribute(k){delete this.attrs[k]}
 addEventListener(){} querySelector(){return null} showModal(){this.open=true} close(){this.open=false}
 getBoundingClientRect(){return {left:0,top:0,bottom:30}} contains(v){return v===this}
}
const html=fs.readFileSync('qqmemory/qqmemory/ui/index.html','utf8'),elements=new Map();
for(const [,id] of html.matchAll(/id="([^"]+)"/g))elements.set(id,new Element());
elements.get('workers').value='6';
const calls=[];let selected='123',active=false,intent;
const posts=()=>[{id:'post-'+selected,author:{uin:selected,nickname:selected},media:[],likes:[],comments:[],content:'archive-'+selected,year:'2020',date:'2020',category:'posts'}];
const state=()=>({account:selected,nickname:selected,active,phase:active?'login':'ready',mode:'collect',task_account:active&&intent!=='add'?selected:null,qr:active?'data:image/png;base64,example':null,posts:posts(),total:1,years:['2020'],category_counts:{posts:1},stats:{posts:1},events:[],message:'saved',progress:{stage:'login',elapsed:0}});
const context=vm.createContext({URLSearchParams,AbortController,Date,console,location:{search:''},clearTimeout(){},setTimeout(){return 1},
 window:{addEventListener(){},innerWidth:1200,innerHeight:800,scrollBy(){},scrollTo(){}},
 document:{hidden:false,body:new Element(),getElementById(id){return elements.get(id)||null},createElement(tag){return new Element(tag)},createDocumentFragment(){return new Element()},createTextNode(text){return {textContent:text}},addEventListener(){}},
 async fetch(path,options={}){calls.push({path,body:options.body&&JSON.parse(options.body)});let data;
 if(path.startsWith('api/state'))data=state();
 else if(path==='api/accounts')data={selected,accounts:[{uin:'123',nickname:'First',posts:1,photos:0,modified:1},{uin:'456',nickname:'Second',posts:2,photos:3,modified:2}]};
 else if(path==='api/accounts/select'){selected=JSON.parse(options.body).uin;data={ok:true}}
 else if(path==='api/start'){intent=JSON.parse(options.body).intent;active=true;data={ok:true}}
 else throw Error('Unexpected request '+path);
 return {ok:true,json:async()=>data};
 }});
vm.runInContext(fs.readFileSync('qqmemory/qqmemory/ui/app.js','utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await flush();assert.equal(calls.some(c=>c.path==='api/start'),false,'Opening local archives must not start QR login');
 await elements.get('account-switch').onclick();
 assert.equal(elements.get('accounts-dialog').open,true);
 await elements.get('account-list').children[1].onclick();
 assert.equal(selected,'456');assert.equal(elements.get('profile-name').textContent,'456');assert.equal(calls.some(c=>c.path==='api/start'),false);
 await vm.runInContext("startLogin('update')",context);await flush();
 assert.equal(calls.find(c=>c.path==='api/start').body.intent,'update');
 assert.match(elements.get('login-description').textContent,/456/);
 vm.runInContext("renderTask({active:true,phase:'collecting',task_account:'123',account:'456',mode:'deep',events:[],message:'working',progress:{stage:'deep',label:'深度扫描',done:10,total:100,percent:10,elapsed:30,eta:[100,400]}})",context);
 assert.equal(elements.get('scan-progress').value,10);assert.match(elements.get('scan-estimate').textContent,/不代表历史内容找回比例/);assert.match(elements.get('task-message').textContent,/123/);
 console.log('本地切换、无自动扫码、更新账号提示、任务归属和分阶段进度检查通过');
})().catch(e=>{console.error(e);process.exitCode=1});
