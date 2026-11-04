const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let me=null,site=null,signup=false,timer=null;
async function api(p,body){
  let r;
  try{r=await fetch(p,{method:body===undefined?"GET":"POST",headers:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body)})}
  catch{throw new Error("Cannot reach the MineSight server. Check that it is running, then open "+(location.protocol==="file:"?"http://localhost:8000":location.origin)+" in your browser.")}
  const d=await r.json().catch(()=>({}));
  if(!r.ok){if(r.status===401&&p!=="/api/login")showAuth();throw new Error(typeof d.detail==="string"?d.detail:r.status>=500?"Server error ("+r.status+"). Look at the terminal window running MineSight for details.":"Check the details and try again.")}
  return d}
function showAuth(){clearInterval(timer);me=null;$("#auth").classList.remove("hide");$("#appv").classList.add("hide")}
function mode(s){signup=s;$("#at").textContent=s?"Create your account":"Sign in";$("#ab").textContent=s?"Create account":"Sign in";
  $("#orgW").classList.toggle("hide",!s);$("#swap").textContent=s?"Have an account? Sign in":"New here? Create an account";$("#msg").textContent=""}
$("#swap").onclick=()=>mode(!signup);
let resetTok=(location.hash.match(/^#reset=([\w-]+)$/)||[])[1];
const emField=()=>[document.querySelector('label[for="em"]'),$("#em")];
function resetMode(){$("#at").textContent="Set a new password";$("#ab").textContent="Update password";["#orgW","#codeW","#swap"].forEach(i=>$(i).classList.add("hide"));emField().forEach(x=>x.classList.add("hide"));$("#em").required=false;$("#pw").autocomplete="new-password"}
function leaveReset(){resetTok=null;history.replaceState(null,"",location.pathname);emField().forEach(x=>x.classList.remove("hide"));$("#em").required=true;$("#pw").autocomplete="current-password";$("#swap").classList.remove("hide");mode(false)}
$("#af").onsubmit=async e=>{e.preventDefault();const m=$("#msg");m.style.color="";m.textContent="";
  try{
    if(resetTok){await api("/api/reset",{token:resetTok,password:$("#pw").value});$("#pw").value="";leaveReset();m.style.color="var(--ok)";m.textContent="Password updated. You can sign in now.";return}
    await api(signup?"/api/signup":"/api/login",signup?{org:$("#org").value,email:$("#em").value,password:$("#pw").value}:{email:$("#em").value,password:$("#pw").value,code:$("#code").value});
    $("#pw").value="";$("#code").value="";$("#codeW").classList.add("hide");boot()}
  catch(x){if(x.message==="code_required"){$("#codeW").classList.remove("hide");$("#code").focus();m.textContent="Enter the 6-digit code from your authenticator app, or a recovery code."}else m.textContent=x.message}};
$("#out").onclick=async()=>{await api("/api/logout",{});showAuth()};
async function boot(){
  try{me=await api("/api/me")}catch(x){showAuth();if(/Cannot reach/.test(x.message))$("#msg").textContent=x.message;return}
  $("#auth").classList.add("hide");$("#appv").classList.remove("hide");
  $("#who").textContent=me.org+" · "+me.email;$("#inf").classList.toggle("hide",!rw());
  const keep=site;$("#siteSel").innerHTML=me.sites.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join("");
  site=me.sites.some(s=>s.id==keep)?keep:me.sites[0].id;$("#siteSel").value=site;
  renderAdmin();renderAcct();clearInterval(timer);tick();timer=setInterval(tick,1000)}
$("#siteSel").onchange=e=>{site=+e.target.value;$("#tiles").innerHTML="";shown=0;woKey=inKey="";$("#wolist").innerHTML="";$("#inlist").innerHTML="";renderAdmin();tick()};
function renderAdmin(){
  const a=$("#admin");if(me.role!=="admin"){a.classList.add("hide");return}
  const s=me.sites.find(x=>x.id==site);a.classList.remove("hide");
  a.innerHTML=`<h2>Admin</h2>
  ${s.simulated?"<small>This site uses simulated data.</small>":`<small>Send readings for this site:</small><pre>curl -X POST ${esc(location.origin)}/ingest \\
 -H "X-API-Key: ${esc(s.api_key)}" \\
 -H "Content-Type: application/json" \\
 -d '{"asset":"CV-02","vib":3.4,"temp":71.2}'</pre>`}
  <form id="sf"><label for="sn">Add a site</label><input id="sn" required minlength="2" placeholder="e.g. Rustenburg shaft 4">
  <label><input type="checkbox" id="ss"> Simulated demo data</label><button class="btn">Add site</button></form>
  <form id="uf"><label for="ue">Add a team member</label><input id="ue" type="email" required placeholder="name@company.co.za">
  <label for="up">Temporary password (10+ characters)</label><input id="up" type="password" minlength="10" required autocomplete="new-password">
  <label for="ur">Role</label><select id="ur"><option value="viewer">Viewer (read-only)</option><option value="planner">Planner (work orders, incidents)</option><option value="admin">Admin</option></select><button class="btn">Add member</button></form>
  ${s.simulated?"":`<form id="tf"><label for="mf">Prediction model</label><small id="mstat" style="color:var(--mute)">Checking…</small>
  <small style="color:var(--mute)">Upload your history as a CSV with columns: asset, ts, vib, temp, failed (1 on the row where a breakdown happened). At least 5 recorded failures are needed.</small>
  <input id="mf" type="file" accept=".csv,text/csv"><button class="btn" id="tb">Train on this file</button><button type="button" class="link" id="tr">Go back to the standard model</button></form>`}
  <form id="wf"><label for="wu">Alert webhook (https)</label><input id="wu" type="url" placeholder="https://hooks.slack.com/..." value="${esc(s.webhook||"")}">
  <small style="color:var(--mute)">Sent as JSON when a machine gets worse. Works with Slack, Teams, Zapier, Make or a WhatsApp gateway.</small><button class="btn">Save webhook</button><button type="button" class="link" id="wt">Send a test message</button></form>
  <div id="amsg" role="status" style="font-size:13.5px;min-height:1.3em"></div>
  <h2 style="margin-top:22px">Team</h2><div id="team"></div><pre id="linkbox" class="hide"></pre>
  <h2 style="margin-top:22px">Activity log</h2><ul id="auditlist"></ul>`;
  const loadTeam=()=>api("/api/users").then(r=>{$("#team").innerHTML=r.map(m=>`<div class="wo"><div><b>${esc(m.email)}</b><div class="rd">${esc(m.role)} · two-step ${m.totp?"on":"off"}</div></div><div class="act"><button class="ghost" data-rl="${m.id}">Reset link</button>${m.totp?`<button class="ghost" data-r2="${m.id}">Reset two-step</button>`:""}</div></div>`).join("")}).catch(()=>{});loadTeam();
  $("#team").onclick=async e=>{const b=e.target.closest("button");if(!b)return;try{
    if(b.dataset.rl){const r=await api(`/api/users/${b.dataset.rl}/reset-link`,{});const L=$("#linkbox");L.classList.remove("hide");L.textContent=location.origin+r.path;say("One-time link ready. Share it with that person only. It works once and expires in an hour.")}
    else if(b.dataset.r2){await api(`/api/users/${b.dataset.r2}/2fa-reset`,{});say("Two-step sign-in removed for that person.");loadTeam()}}catch(x){say(x.message,1)}};
  api("/api/audit").then(r=>{$("#auditlist").innerHTML=r.map(x=>`<li><time>${new Date(x.ts*1000).toLocaleString([],{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})}</time><b>${esc(x.actor)}</b> ${esc(x.action.replace(/_/g," "))} ${esc(x.detail||"")}</li>`).join("")||"<li>Nothing yet.</li>"}).catch(()=>{});
  const say=(t,bad)=>{$("#amsg").style.color=bad?"var(--crit)":"var(--ok)";$("#amsg").textContent=t};
  $("#sf").onsubmit=async e=>{e.preventDefault();try{const r=await api("/api/sites",{name:$("#sn").value,simulated:$("#ss").checked});site=r.id;await boot();say("Site added.")}catch(x){say(x.message,1)}};
  if($("#tf")){
    api(`/api/sites/${site}/model`).then(m=>{$("#mstat").textContent=m.source==="default"?"Using the standard model.":`Custom model trained ${new Date(m.trained*1000).toLocaleDateString()} on ${m.rows.toLocaleString("en-ZA")} readings and ${m.failures} failures. Typical error in the last 150 h before failure: ${Math.round(m.mae_near)} h.`}).catch(()=>{});
    $("#tf").onsubmit=async e=>{e.preventDefault();const f=$("#mf").files[0];if(!f)return say("Choose a CSV file first.",1);if(f.size>5e6)return say("File is over 5 MB. Send a shorter period or fewer assets.",1);
      const b=$("#tb");b.disabled=true;say("Training. This can take a minute…");
      try{const r=await api(`/api/sites/${site}/train`,{csv:await f.text()});say(`Done. Trained on ${r.rows.toLocaleString("en-ZA")} readings and ${r.failures} failures. Error in the last 150 h before failure: ${Math.round(r.mae_near)} h (a constant guess is off by ${Math.round(r.base_near)} h).`);$("#mstat").textContent="Custom model active."}catch(x){say(x.message,1)}b.disabled=false};
    $("#tr").onclick=async()=>{try{await api(`/api/sites/${site}/model/reset`,{});say("Back on the standard model.");$("#mstat").textContent="Using the standard model."}catch(x){say(x.message,1)}}}
  $("#wf").onsubmit=async e=>{e.preventDefault();try{await api(`/api/sites/${site}/webhook`,{url:$("#wu").value});s.webhook=$("#wu").value;say("Webhook saved.")}catch(x){say(x.message,1)}};
  $("#wt").onclick=async()=>{try{await api(`/api/sites/${site}/webhook/test`,{});say("Test message sent.")}catch(x){say(x.message,1)}};
  $("#uf").onsubmit=async e=>{e.preventDefault();try{await api("/api/users",{email:$("#ue").value,password:$("#up").value,role:$("#ur").value});$("#uf").reset();say("Member added.");loadTeam()}catch(x){say(x.message,1)}}}
const C=2*Math.PI*46,HC=2*Math.PI*70,LV={ok:"Healthy",warning:"Plan maintenance",critical:"Urgent"};
const fmt=v=>"R "+Math.round(v).toLocaleString("en-ZA");let shown=0;
function countTo(v){const from=shown;shown=v;const t0=performance.now();
  if(matchMedia("(prefers-reduced-motion:reduce)").matches){$("#saved").textContent=fmt(v);return}
  (function f(t){const k=Math.min(1,(t-t0)/700);$("#saved").textContent=fmt(from+(v-from)*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(f)})(t0)}
const spark=t=>{if(t.length<2)return"";const lo=Math.min(...t),hi=Math.max(...t,lo+.5);return"M"+t.map((v,i)=>`${(i/39*200).toFixed(1)} ${(38-(v-lo)/(hi-lo)*36).toFixed(1)}`).join("L")};
function tile(a,i,sim){
  let el=document.getElementById("t-"+a.id);
  if(!el){el=document.createElement("article");el.id="t-"+a.id;
    el.innerHTML='<div class="rw"><svg class="ring" viewBox="0 0 110 110" aria-hidden="true"><circle class="tick" cx="55" cy="55" r="52"/><circle class="trk" cx="55" cy="55" r="46"/><circle class="val" cx="55" cy="55" r="46"/></svg><div class="num"><b></b><span>hours left</span></div></div><div class="meta"><h3></h3><span class="st"></span><p class="rd"></p></div><svg class="sp" viewBox="0 0 200 40" preserveAspectRatio="none" aria-hidden="true"><path class="area"/><path class="line"/></svg><button class="ghost">Inject fault</button>';
    $("#tiles").append(el)}
  const h=a.rul>=399?"400+":String(Math.round(a.rul));
  el.className="tile "+a.level;el.style.order=i;
  el.setAttribute("aria-label",`${a.name}: ${h} hours to failure, ${LV[a.level]}`);
  el.querySelector(".val").style.strokeDasharray=`${C*Math.min(1,a.rul/400)} ${C}`;
  el.querySelector(".num b").textContent=h;el.querySelector("h3").textContent=a.name;
  el.querySelector(".st").textContent=LV[a.level];
  el.querySelector(".rd").textContent=`${a.vib.toFixed(1)} mm/s · ${a.temp.toFixed(0)} °C`;
  const sd=spark(a.trend);el.querySelector(".line").setAttribute("d",sd);el.querySelector(".area").setAttribute("d",sd?sd+"L200 40L0 40Z":"");
  const b=el.querySelector("button");b.hidden=!sim;b.dataset.f=a.id}
async function tick(){
  if(!site)return;
  $("#rep").href="/api/report?site="+site;
  const so=$("#siteSel").selectedOptions[0];$("#sitetitle").textContent=so?so.textContent:"";
  document.querySelectorAll("[data-x]").forEach(a=>a.href=`/api/export/${a.dataset.x}?site=${site}`);
  if(tk++%4===0)extras();
  try{
    const d=await api("/api/state?site="+site),A=d.assets.sort((x,y)=>x.rul-y.rul),sim=d.mode==="simulated";
    $("#mode").textContent=sim?"Simulated data":"Live data";
    const n=A.length,c=l=>A.filter(a=>a.level===l).length;
    $("#n-ok").textContent=c("ok");$("#n-warn").textContent=c("warning");$("#n-crit").textContent=c("critical");
    $("#heroVal").style.strokeDasharray=`${HC*(n?c("ok")/n:0)} ${HC}`;
    $("#heroPct").textContent=n?Math.round(100*c("ok")/n)+"%":"–";
    document.querySelector(".fleet").dataset.l=c("critical")?"critical":c("warning")?"warning":"ok";
    if(Math.round(d.saved)!==Math.round(shown))countTo(d.saved);
    const ids=new Set(A.map(a=>"t-"+a.id));
    document.querySelectorAll("#tiles>.tile").forEach(t=>{if(!ids.has(t.id))t.remove()});
    A.forEach((a,i)=>tile(a,i,sim));$("#empty").classList.toggle("hide",n>0);
    $("#log").innerHTML=d.alerts.map(a=>`<li class="${esc(a.level)}"><time>${new Date(a.ts*1000).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}</time><b>${esc(a.asset)}</b> ${esc(a.msg)}</li>`).join("")||"<li>No alerts yet.</li>";
  }catch(e){}}
$("#tiles").addEventListener("click",e=>{const b=e.target.closest("[data-f]");if(b)api(`/api/fault/${site}/${b.dataset.f}`,{})});
if(location.protocol==="file:")$("#msg").textContent="Open http://localhost:8000 in your browser. This page cannot work when opened as a file.";
let tk=0,woKey="",inKey="";
const PL={urgent:"Urgent",planned:"Planned"},SL={open:"Open",in_progress:"In progress",done:"Done"};
const rw=()=>me&&me.role!=="viewer";
async function extras(){
  try{
    const[w,n]=await Promise.all([api("/api/workorders?site="+site),api("/api/incidents?site="+site)]),wk=JSON.stringify(w);
    if(wk!==woKey&&!$("#wolist").contains(document.activeElement)){woKey=wk;
      $("#wolist").innerHTML=w.length?w.map(o=>`<div class="wo ${esc(o.status)}"><div><b>${esc(o.title)}</b><div class="rd">${esc(o.asset)} · opened ${new Date(o.created*1000).toLocaleString([],{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})}</div></div>
      <div class="act"><span class="pr ${esc(o.priority)}">${PL[o.priority]||""}</span>
      <select data-w="${o.id}" aria-label="Status" ${rw()?"":"disabled"}>${Object.keys(SL).map(k=>`<option value="${k}" ${k===o.status?"selected":""}>${SL[k]}</option>`).join("")}</select>
      <input data-a="${o.id}" value="${esc(o.assignee||"")}" placeholder="Assign to" maxlength="60" aria-label="Assigned to" ${rw()?"":"disabled"}></div></div>`).join(""):'<p class="empty">No work orders yet. They are raised automatically when a machine is flagged.</p>'}
    const ik=JSON.stringify(n);
    if(ik!==inKey){inKey=ik;$("#inlist").innerHTML=n.map(i=>`<li class="${i.severity==="high"?"critical":i.severity==="medium"?"warning":"ok"}"><time>${new Date(i.ts*1000).toLocaleDateString([],{day:"numeric",month:"short"})}</time><b>${esc(i.kind)}</b> ${esc(i.location)}: ${esc(i.description)}</li>`).join("")||"<li>No incidents reported.</li>"}
  }catch(e){}}
$("#wolist").addEventListener("change",async e=>{const t=e.target;$("#womsg").textContent="";
  try{if(t.dataset.w)await api("/api/workorders/"+t.dataset.w,{status:t.value});else if(t.dataset.a)await api("/api/workorders/"+t.dataset.a,{assignee:t.value});woKey="";extras()}
  catch(x){$("#womsg").textContent=x.message}});
$("#inf").onsubmit=async e=>{e.preventDefault();$("#imsg").textContent="";
  try{await api("/api/incidents",{site,kind:$("#ik").value,severity:$("#is").value,location:$("#il").value,description:$("#idesc").value});$("#inf").reset();inKey="";extras()}
  catch(x){$("#imsg").textContent=x.message}};
$("#tiles").addEventListener("pointermove",e=>{const t=e.target.closest(".tile");if(t){const r=t.getBoundingClientRect();t.style.setProperty("--mx",e.clientX-r.left+"px");t.style.setProperty("--my",e.clientY-r.top+"px")}});
function renderAcct(){
  const a=$("#acct");a.innerHTML=`<h2>Account security</h2>
  <form id="pf"><label for="pc">Change password</label><input id="pc" type="password" placeholder="Current password" autocomplete="current-password" required><input id="pn" type="password" placeholder="New password (10+ characters)" minlength="10" autocomplete="new-password" required><button class="btn">Update password</button></form>
  <div id="tfa"></div><div id="acmsg" role="status" style="font-size:14px;min-height:1.4em;margin-top:10px"></div>`;
  const say=(t,bad)=>{$("#acmsg").style.color=bad?"var(--crit)":"var(--ok)";$("#acmsg").textContent=t};
  $("#pf").onsubmit=async e=>{e.preventDefault();try{await api("/api/me/password",{current:$("#pc").value,new:$("#pn").value});$("#pf").reset();say("Password updated. Other devices were signed out.")}catch(x){say(x.message,1)}};
  const draw=()=>{
    $("#tfa").innerHTML=me.totp?`<label>Two-step sign-in is on</label><form id="t0"><input id="t0p" type="password" placeholder="Password" autocomplete="current-password" required><input id="t0c" placeholder="Code or recovery code" required><button class="btn">Turn off</button></form>`
      :`<label>Two-step sign-in is off</label><button class="btn" id="t1">Set up with an authenticator app</button><div id="t1box"></div>`;
    if(me.totp)$("#t0").onsubmit=async e=>{e.preventDefault();try{await api("/api/me/2fa/disable",{password:$("#t0p").value,code:$("#t0c").value});me.totp=false;draw();say("Two-step sign-in is off.")}catch(x){say(x.message,1)}};
    else $("#t1").onclick=async()=>{try{const r=await api("/api/me/2fa/start",{});
      $("#t1box").innerHTML=`<p class="rd">Scan with Google Authenticator, Microsoft Authenticator or Authy, or type the key.</p>${r.qr?`<img alt="QR code for your authenticator app" width="168" height="168" style="background:#fff;border-radius:8px" src="data:image/svg+xml;utf8,${encodeURIComponent(r.qr)}">`:""}<pre>${esc(r.secret)}</pre><form id="t2"><input id="t2c" inputmode="numeric" autocomplete="one-time-code" placeholder="6-digit code" required><button class="btn">Turn on</button></form>`;
      $("#t2").onsubmit=async e=>{e.preventDefault();try{const k=await api("/api/me/2fa/enable",{code:$("#t2c").value});me.totp=true;draw();
        $("#tfa").insertAdjacentHTML("beforeend",`<p class="rd"><b>Save these recovery codes now.</b> Each works once if you lose your phone. They will not be shown again.</p><pre>${k.recovery.map(esc).join("\n")}</pre>`);say("Two-step sign-in is on.")}catch(x){say(x.message,1)}}}catch(x){say(x.message,1)}}};
  draw()}
/*SW*/if("serviceWorker"in navigator&&(location.protocol==="https:"||location.hostname==="localhost"))navigator.serviceWorker.register("/sw.js").catch(()=>{});/*ENDSW*/
if(resetTok){resetMode();showAuth()}else boot();
