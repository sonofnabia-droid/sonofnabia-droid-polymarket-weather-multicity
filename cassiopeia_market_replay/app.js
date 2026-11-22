'use strict';
// Cassiopeia Market Replay v0.2 — local, read-only, causal display.
const $ = id => document.getElementById(id);
const palette = ['#629afa','#7158ec','#e9b629','#f18d41','#25a6b7','#ce65b2','#279c7f'];
const app = {
  catalog: null, dates: [], data: null, epoch: 0, speed: '3', playing: false,
  lastFrame: 0, selected: null, outcome: 'YES', sourceIndex: 0,
  sort: 'bracket'
};
const fmt = (n, d=2) => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toFixed(d).replace('.', ',');
const cents = n => n == null || !Number.isFinite(Number(n)) ? '—' : `${Math.round(Number(n)*100)}¢`;
const percent = n => n == null ? '—' : `${Math.round(Number(n)*100)}%`;
const dur = sec => sec < 60 ? 'agora' : sec < 3600 ? `${Math.floor(sec/60)} min` : `${Math.floor(sec/3600)}h ${Math.floor(sec%3600/60)}m`;
function localTime(epoch, tz, seconds=false) {
  if (!Number.isFinite(epoch)) return '—';
  return new Intl.DateTimeFormat('pt-PT', {timeZone:tz, hour:'2-digit', minute:'2-digit', ...(seconds?{second:'2-digit'}:{}), hourCycle:'h23'}).format(new Date(epoch*1000));
}
function dateLabel(date) {
  const d = new Date(`${date}T12:00:00Z`);
  return new Intl.DateTimeFormat('pt-PT',{day:'numeric',month:'short',timeZone:'UTC'}).format(d);
}
function marketTitle(city, day) {
  const place = city.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
  const date = new Date(day+'T12:00:00Z');
  const label = new Intl.DateTimeFormat('en-US',{month:'long',day:'numeric',timeZone:'UTC'}).format(date);
  return `Highest temperature in ${place} on ${label}?`;
}
function lastAt(points, timestamp) {
  if (!points?.length) return null;
  let lo=0,hi=points.length;
  while(lo<hi) {const m=(lo+hi)>>1;if(points[m][0]<=timestamp)lo=m+1;else hi=m;}
  return lo?points[lo-1]:null;
}
function showMessage(msg) { $('message').hidden = !msg; $('message').textContent=msg||''; }
async function api(path) {
  const res = await fetch(path);
  const json = await res.json();
  if(!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}
async function loadCatalog() {
  try {
    const c=await api('/api/catalog'); app.catalog=c;
    $('city').replaceChildren(...c.cities.map(x=>new Option(`${x.city.replaceAll('_',' ').toUpperCase()} · ${x.n} dias`,x.city)));
    if(!c.cities.length) {showMessage('Nenhum mercado encontrado na SQLite.'); return;}
    $('city').value=c.cities.some(x=>x.city==='munich')?'munich':c.cities[0].city;
    await loadDates(); await loadMarket();
  } catch (err) {showMessage(`Erro ao carregar o catálogo: ${err.message}`);}
}
async function loadDates(preferred=null) {
  if(!$('city').value)return;
  const d=await api('/api/dates?city='+encodeURIComponent($('city').value));
  app.dates=d.dates;
  const current=preferred&&app.dates.includes(preferred)?preferred:app.dates.includes('2026-11-14')?'2026-11-14':app.dates[0];
  $('date').replaceChildren(...app.dates.map(day=>new Option(day,day)));
  if(current)$('date').value=current;
  renderDatePills();
}
function renderDatePills() {
  const date=$('date').value,i=app.dates.indexOf(date), wrap=$('datePills');
  if(i<0){wrap.replaceChildren();return;}
  const days=app.dates.slice(Math.max(0,i-2),Math.min(app.dates.length,i+3));
  const frag=document.createDocumentFragment();
  for(const day of days){
    const btn=document.createElement('button');btn.className='date-pill'+(day===date?' active':'');
    btn.type='button';btn.textContent=dateLabel(day);
    btn.addEventListener('click',async()=>{$('date').value=day;renderDatePills();await loadMarket();});frag.append(btn);
  }
  wrap.replaceChildren(frag);
}
async function loadMarket() {
  app.playing=false; app.lastFrame=0; $('play').textContent='▶';
  const city=$('city').value,day=$('date').value;if(!city||!day)return;
  $('load').disabled=true;showMessage('A carregar preços, brackets e observações meteorológicas da SQLite local…');
  try {
    const data=await api(`/api/replay?city=${encodeURIComponent(city)}&date=${encodeURIComponent(day)}`);
    app.data=data; app.epoch=data.start;
    if(!data.markets.some(m=>m.market_id===app.selected))app.selected=data.markets[Math.floor(data.markets.length/2)]?.market_id||null;
    app.outcome='YES'; app.sourceIndex=0;
    $('marketTitle').textContent=data.title||marketTitle(city,day);
    $('subtitle').textContent=`${data.markets.length} brackets · ${data.statistics.price_points.toLocaleString('pt-PT')} preços arquivados · ${data.statistics.book_snapshots.toLocaleString('pt-PT')} snapshots · ${data.timezone}`;
    $('tzlabel').textContent=data.timezone;
    $('timeEnd').textContent=localTime(data.end-60,data.timezone);
    $('coverage').textContent=`${data.statistics.brackets} brackets`;
    $('dataPoints').textContent=`${data.statistics.price_points.toLocaleString('pt-PT')} preços históricos`;
    setWeatherOptions();renderDatePills();showMessage(null);render();
  } catch(err) {showMessage('Não foi possível carregar o mercado: '+err.message);}
  finally {$('load').disabled=false;}
}
function setWeatherOptions() {
  const w=app.data.weather, s=$('weatherSource');
  s.replaceChildren(...w.map((x,i)=>new Option(x.name,String(i))));
  if(w.length>1)s.add(new Option('Sobrepor fontes','all'));
  if(!w.length)s.add(new Option('Sem dados','0'));
  s.disabled=!w.length; s.value='0';
  $('weatherOrigin').textContent=w[0]?.source||'Não disponível';
}
const mainWeather=()=>app.data?.weather[app.sourceIndex>=0?app.sourceIndex:0]?.points||[];
const selectedMarket=()=>app.data?.markets.find(m=>m.market_id===app.selected)||null;
function tokenOf(m, outcome='YES') {return m?.tokens?.[outcome]||null;}
function state(m, outcome='YES', t=app.epoch) {
  const token=tokenOf(m,outcome),h=lastAt(token?.prices,t),b=lastAt(token?.books,t);
  const pAge=h?t-h[0]:null,bAge=b?t-b[0]:null;
  return {h, pAge, b:b&&bAge<=900?b:null, bAge,
    freshPrice:h&&pAge<=1800?Number(h[1]):null};
}
function observationsNow() {
  const pts=mainWeather(), last=lastAt(pts,app.epoch);
  let max=-Infinity;
  for(const [ts,v] of pts){if(ts>app.epoch)break;max=Math.max(max,v);}
  return {last,max:Number.isFinite(max)?max:null};
}
function candidateId() {
  const {max}=observationsNow();if(max==null)return null;
  const rounded=Math.floor(max+.5);
  const market=app.data.markets.find(m=>new RegExp(`^\\s*${rounded}\\s*°\\s*C\\s*$`,'i').test(m.bracket));
  return market?.market_id||null;
}
function marketColor(m){let i=app.data.markets.findIndex(x=>x.market_id===m.market_id);return palette[Math.abs(i)%palette.length];}
function selection(m, outcome=app.outcome) {
  app.selected=m.market_id; app.outcome=outcome; render();
}
function updateStats() {
  const d=app.data,t=app.epoch,{last,max}=observationsNow(),m=selectedMarket(),q=state(m,app.outcome);
  $('clock').textContent=localTime(t,d.timezone,true);
  $('timeCurrent').textContent=localTime(t,d.timezone);
  $('seek').value=Math.max(0,Math.min(1000,Math.round(1000*(t-d.start)/(d.end-d.start))));
  $('currentTemp').textContent=last?`${fmt(last[1],1)}°C`:'—';
  $('currentTempMeta').textContent=last?`Último reporte ${localTime(last[0],d.timezone)} · há ${dur(t-last[0])}`:'Sem reporte até agora';
  $('maxTemp').textContent=max==null?'—':`${fmt(max,1)}°C`;
  $('maxTempMeta').textContent=max==null?'Sem máximo observado':'Máximo nesta fonte, até agora';
  $('currentBracket').textContent=m?.bracket||'—';
  $('currentPriceMeta').textContent=q.h?`${app.outcome} histórico ${cents(q.h[1])} · há ${dur(q.pAge)}${q.freshPrice==null?' · antigo':''}`:'Sem histórico até este instante';
  $('currentAsk').textContent=q.b?.[3]!=null?cents(q.b[3]):'—';
  $('currentAskMeta').textContent=q.b?.[3]!=null?`Book observado há ${dur(q.bAge)} · size ${fmt(q.b[4],1)}`:'Sem ask recente (≤ 15 min)';
  $('priceSubtitle').textContent=`${app.outcome} · ${m?.bracket||'—'} · a cor ciano assinala a seleção`;
}
function renderRows() {
  const rows=$('bracketRows'), markets=[...app.data.markets],candidate=candidateId();
  if(app.sort==='price')markets.sort((a,b)=>(state(b,'YES').h?.[1]??-1)-(state(a,'YES').h?.[1]??-1));
  const fragment=document.createDocumentFragment();
  for(const m of markets) {
    const yes=state(m,'YES'),no=state(m,'NO'),isSel=m.market_id===app.selected,isCand=m.market_id===candidate;
    const row=document.createElement('div');row.className='bracket-row'+(isSel?' selected':'')+(isCand?' candidate':'');
    row.tabIndex=0;row.setAttribute('role','button');row.setAttribute('aria-label',`Selecionar ${m.bracket}`);
    row.addEventListener('click',()=>selection(m));
    row.addEventListener('keydown',e=>{if(e.target!==row)return;if(e.key==='Enter'||e.key===' '){e.preventDefault();selection(m);}});
    const label=document.createElement('div'),name=document.createElement('div'),flags=document.createElement('div');
    name.className='bracket-name';name.textContent=m.bracket;flags.className='bracket-flags';
    if(isSel){const tag=document.createElement('span');tag.className='small-tag';tag.textContent='SELECIONADA';flags.append(tag);}
    if(isCand){const tag=document.createElement('span');tag.className='small-tag gold';tag.textContent='MÁX. OBS. ≈';tag.title='Apenas correspondência aproximada com arredondamento inteiro; confirmar regras do contrato';flags.append(tag);}
    if(!yes.h){const tag=document.createElement('span');tag.className='small-tag muted';tag.textContent='SEM PREÇO';flags.append(tag);}
    label.append(name,flags);
    const price=document.createElement('div');price.className='yes-price';
    const val=document.createElement('strong');val.textContent=yes.h?percent(yes.h[1]):'—';
    if(yes.h&&yes.freshPrice==null)val.style.color='#9aa4af';
    const delta=document.createElement('span');delta.className='price-change';
    const old=lastAt(tokenOf(m,'YES')?.prices,app.epoch-3600);
    if(yes.h&&old){const d=100*(yes.h[1]-old[1]);delta.textContent=`${d>=0?'▲':'▼'} ${Math.abs(d).toFixed(1).replace('.',',')} pp`;delta.classList.add(d>0?'up':d<0?'down':'');}
    else delta.textContent='—';price.append(val,delta);
    const makeQuote=(out,q)=>{
      const btn=document.createElement('button');btn.className='quote-btn '+(out==='NO'?'no':'yes')+(isSel&&app.outcome===out?' selected':'');btn.type='button';
      const real=q.b?.[3]!=null?Number(q.b[3]):null;
      const historical=q.freshPrice;
      const v=real??historical;
      const big=document.createElement('span');big.textContent=`${out} ${cents(v)}`;
      const mini=document.createElement('small');mini.textContent=real!=null?'ASK OBSERVADO':historical!=null?'HISTÓRICO':'SEM COTAÇÃO';
      btn.append(big,mini);btn.disabled=v==null;
      btn.title=real!=null?'Ask real arquivado; clique apenas seleciona para análise':historical!=null?'Preço histórico, NÃO executável; clique apenas seleciona':'Preço indisponível';
      btn.addEventListener('click',e=>{e.stopPropagation();selection(m,out);});return btn;
    };
    row.append(label,price,makeQuote('YES',yes),makeQuote('NO',no));fragment.append(row);
  }
  rows.replaceChildren(fragment);
}
function pickChartMarkets() {
  const ranked=[...app.data.markets].sort((a,b)=>(state(b,app.outcome).h?.[1]??-1)-(state(a,app.outcome).h?.[1]??-1));
  const shown=ranked.filter(m=>state(m,app.outcome).h).slice(0,4);
  const sel=selectedMarket();if(sel&&!shown.some(m=>m.market_id===sel.market_id)) {
    if(shown.length===4)shown.pop();shown.push(sel);
  }
  return shown;
}
function renderLegend(markets) {
  const fragment=document.createDocumentFragment();
  for(const m of markets){
    const q=state(m,app.outcome),b=document.createElement('button');b.className='legend-btn'+(app.selected===m.market_id?' selected':'');
    b.type='button';const dot=document.createElement('i');dot.className='legend-dot';dot.style.background=marketColor(m);
    const name=document.createElement('span');name.textContent=m.bracket;
    const value=document.createElement('span');value.className='legend-value';value.textContent=q.h?percent(q.h[1]):'—';
    b.append(dot,name,value);b.title=`Selecionar bracket ${m.bracket}`;b.addEventListener('click',()=>selection(m));fragment.append(b);
  }
  $('priceLegend').replaceChildren(fragment);
}
function sizeCanvas(id) {
  const canvas=$(id),bounds=canvas.getBoundingClientRect(),dpr=Math.min(2,window.devicePixelRatio||1);
  const w=Math.max(320,Math.round(bounds.width)),h=Math.max(160,Math.round(bounds.height));
  canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);return {ctx,w,h};
}
function drawAxes(ctx,box,min,max,unit,shade=true) {
  const {left,top,pw,ph,w,h}=box,{start,end,timezone}=app.data;
  const xx=epoch=>left+(epoch-start)/(end-start)*pw;
  const yy=v=>top+(max-v)/(max-min)*ph;
  ctx.font='11px system-ui';ctx.textBaseline='middle';ctx.textAlign='right';
  for(let i=0;i<=4;i++){
    const v=min+i*(max-min)/4,y=yy(v);
    ctx.strokeStyle='#edf0f4';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-14,y);ctx.stroke();
    ctx.fillStyle='#929dac';ctx.fillText(unit==='%'?Math.round(v*100)+'%':v.toFixed(1)+'°',left-12,y);
  }
  ctx.textBaseline='top';ctx.textAlign='center';
  for(let i=0;i<=4;i++){
    const ts=start+(end-start)*i/4;
    ctx.fillStyle='#929dac';ctx.fillText(localTime(ts,timezone),xx(ts),h-22);
  }
  if(shade&&app.epoch<end){
    ctx.fillStyle='rgba(246,249,253,.66)';ctx.fillRect(xx(app.epoch),top,xx(end)-xx(app.epoch),ph);
  }
  ctx.strokeStyle='#b7c3d1';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(xx(app.epoch),top);ctx.lineTo(xx(app.epoch),top+ph);ctx.stroke();ctx.setLineDash([]);
  return {xx,yy};
}
function drawStep(ctx,points,map,{color,width=2,maxGap=1800,extend=false,marker=true}) {
  const filtered=points.filter(p=>p[0]>=app.data.start&&p[0]<=app.epoch&&p[1]!=null&&Number.isFinite(Number(p[1])));
  if(!filtered.length)return;
  const {xx,yy}=map;ctx.lineJoin='round';ctx.strokeStyle=color;ctx.lineWidth=width;
  ctx.beginPath();
  let last=null;
  for(const p of filtered){
    if(!last||p[0]-last[0]>maxGap)ctx.moveTo(xx(p[0]),yy(p[1]));
    else {ctx.lineTo(xx(p[0]),yy(last[1]));ctx.lineTo(xx(p[0]),yy(p[1]));}
    last=p;
  }
  if(extend&&last&&app.epoch-last[0]<=maxGap)ctx.lineTo(xx(app.epoch),yy(last[1]));
  ctx.stroke();
  if(marker&&last){ctx.beginPath();ctx.fillStyle=color;ctx.arc(xx(last[0]),yy(last[1]),3.5,0,Math.PI*2);ctx.fill();}
}
function drawPrice() {
  const series=pickChartMarkets();renderLegend(series);
  const canvas=sizeCanvas('priceChart'),{ctx,w,h}=canvas,t=app.epoch;
  ctx.clearRect(0,0,w,h);
  const visible=series.flatMap(m=>(tokenOf(m,app.outcome)?.prices||[]).filter(p=>p[0]<=t&&p[0]>=app.data.start).map(p=>p[1]));
  $('priceEmpty').hidden=visible.length>0;
  const mx=visible.length?Math.max(...visible):0.5,mi=visible.length?Math.min(...visible):0;
  const min=Math.max(0,Math.floor((mi-.05)*10)/10),max=Math.min(1,Math.max(min+.1,Math.ceil((mx+.05)*10)/10));
  const box={w,h,left:50,top:10,pw:w-64,ph:h-44};
  const map=drawAxes(ctx,box,min,max,'%',true);
  ctx.save();ctx.beginPath();ctx.rect(box.left,box.top,box.pw,box.ph);ctx.clip();
  const ordered=[...series].sort((a,b)=>(a.market_id===app.selected?1:0)-(b.market_id===app.selected?1:0));
  for(const m of ordered){
    const pts=tokenOf(m,app.outcome)?.prices||[],selected=m.market_id===app.selected;
    drawStep(ctx,pts,map,{color:selected?'#0aa6b6':marketColor(m),width:selected?3.6:2.1,maxGap:1200,extend:true});
  }
  ctx.restore();
}
function drawWeather() {
  const {ctx,w,h}=sizeCanvas('weatherChart'),full=app.data.weather,idx=app.sourceIndex;
  const sources=idx===-1?full:full[idx]?[full[idx]]:[],observations=sources.flatMap(s=>s.points.filter(p=>p[0]<=app.epoch));
  $('weatherEmpty').hidden=observations.length>0;
  const values=observations.map(x=>x[1]);let min=values.length?Math.floor(Math.min(...values)-1):0,max=values.length?Math.ceil(Math.max(...values)+1):20;
  if(max-min<4){const mid=(min+max)/2;min=mid-2;max=mid+2;}
  ctx.clearRect(0,0,w,h);
  const box={w,h,left:50,top:10,pw:w-64,ph:h-43},map=drawAxes(ctx,box,min,max,'°C',true);
  ctx.save();ctx.beginPath();ctx.rect(box.left,box.top,box.pw,box.ph);ctx.clip();
  const colors=['#0ca9a1','#609afa','#8a65e8','#ee8b42','#cb6fae'];
  for(let i=0;i<sources.length;i++){
    const s=sources[i];let maxSoFar=-Infinity;const running=[];
    for(const [t,v] of s.points){maxSoFar=Math.max(maxSoFar,v);running.push([t,maxSoFar]);}
    drawStep(ctx,s.points,map,{color:idx===-1?colors[i%colors.length]:'#00a69a',maxGap:5400,extend:true,width:2.5});
    if(i===0)drawStep(ctx,running,map,{color:'#d6a12e',maxGap:5400,extend:true,width:1.8,marker:false});
  }
  ctx.restore();
}
function render() {if(!app.data)return;updateStats();renderRows();drawPrice();drawWeather();}
function seek(t) {if(!app.data)return;app.epoch=Math.max(app.data.start,Math.min(app.data.end-1,t));render();}
function playPause() {
  if(!app.data)return;
  if(app.playing)app.playing=false;
  else {if(app.epoch>=app.data.end-1)app.epoch=app.data.start;app.playing=true;}
  app.lastFrame=0;$('play').textContent=app.playing?'Ⅱ':'▶';
}
function adaptiveSpeed() {
  if(app.speed!=='auto')return Number(app.speed);
  // Look only at observation timestamps for replay navigation; do not expose future values.
  const points=mainWeather();let closest=Infinity;
  for(const [ts] of points)closest=Math.min(closest,Math.abs(ts-app.epoch));
  return closest<=420?2:10;
}
let lastPaint=0;
function animate(now) {
  if(app.playing&&app.data){
    if(!app.lastFrame)app.lastFrame=now;
    const elapsed=Math.max(0,Math.min(.2,(now-app.lastFrame)/1000));
    app.lastFrame=now;app.epoch=Math.min(app.data.end-1,app.epoch+elapsed*adaptiveSpeed()*60);
    if(app.epoch>=app.data.end-1){app.playing=false;$('play').textContent='▶';}
    if(now-lastPaint>130||!app.playing){render();lastPaint=now;}
  }
  requestAnimationFrame(animate);
}
$('city').addEventListener('change',async()=>{await loadDates();await loadMarket();});
$('date').addEventListener('change',()=>{renderDatePills();loadMarket();});
$('load').addEventListener('click',loadMarket);
$('play').addEventListener('click',playPause);
$('speed').addEventListener('change',e=>app.speed=e.target.value);
$('restart').addEventListener('click',()=>{app.playing=false;$('play').textContent='▶';seek(app.data?.start||0);});
$('back').addEventListener('click',()=>seek(app.epoch-300));
$('forward').addEventListener('click',()=>seek(app.epoch+300));
$('nextWeather').addEventListener('click',()=>{const p=mainWeather().find(x=>x[0]>app.epoch+1);if(p)seek(p[0]);});
$('seek').addEventListener('input',e=>{if(app.data)seek(app.data.start+Number(e.target.value)/1000*(app.data.end-app.data.start));});
$('weatherSource').addEventListener('change',e=>{app.sourceIndex=e.target.value==='all'?-1:Number(e.target.value);$('weatherOrigin').textContent=app.sourceIndex===-1?'Múltiplas fontes':app.data.weather[app.sourceIndex]?.source||'—';render();});
$('sort').addEventListener('change',e=>{app.sort=e.target.value;renderRows();});
window.addEventListener('resize',()=>{if(app.data){drawPrice();drawWeather();}});
window.addEventListener('keydown',e=>{const name=document.activeElement?.tagName;if(['INPUT','SELECT','BUTTON','TEXTAREA'].includes(name))return;if(e.code==='Space'){e.preventDefault();playPause();}if(e.code==='ArrowLeft')seek(app.epoch-300);if(e.code==='ArrowRight')seek(app.epoch+300);});
requestAnimationFrame(animate);loadCatalog();
