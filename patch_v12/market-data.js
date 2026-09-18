(function () {
  'use strict';
  const root = document.getElementById('market-data-root'), meta = document.getElementById('md-meta');
  if (!root || !meta) return;
  let packet, view = 'Watchlist', horizon = '5D', scope = 'All markets', query = '';
  const views = ['Watchlist', 'Curves & rates', 'Cross-asset', 'Carry', 'All data'];
  const num = v => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v,d=1) => num(v) ? v.toFixed(d) : '—';
  const signed = (v,d=1) => num(v) ? (v>0?'+':'')+v.toFixed(d) : '—';
  const esc = v => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const badge = (s,kind='') => `<span class="md-badge ${kind}">${esc(s)}</span>`;
  const age = d => d ? Math.floor((Date.now()-Date.parse(d+'T23:59:59Z'))/86400000) : Infinity;
  const status = s => s.status==='ok' && age(s.as_of) > (s.max_age_days || s.lag || packet.cross_assets?.series?.[s.id]?.lag || 4) ? 'stale' : s.status;
  const series = () => packet.opportunities.series;
  const matches = s => (scope === 'All markets' || /CAD|AUD|NZD|CA\b|AU\b|NZ\b/.test(s.label || s.pair || '')) && (!query || (s.label || s.pair || '').toLowerCase().includes(query.toLowerCase()));
  function spark(history, large=false, label='History') {
    const items=(history||[]).filter(p=>num(p[1]));
    if(items.length<2)return '<span class="md-muted">History unavailable</span>';
    const vals=items.map(p=>p[1]), lo=Math.min(...vals), hi=Math.max(...vals), h=large?160:35,w=large?700:130;
    const points=vals.map((v,i)=>`${(i/(vals.length-1)*(w-8)+4).toFixed(1)},${(h-4-(v-lo)/(hi-lo||1)*(h-8)).toFixed(1)}`).join(' ');
    return `<svg class="md-spark ${large?'large':''}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}"><title>${esc(label)}: ${esc(items[0][0])} to ${esc(items.at(-1)[0])}; low ${fmt(lo,3)}, high ${fmt(hi,3)}</title><polyline fill="none" stroke="currentColor" stroke-width="${large?2:1.6}" points="${points}" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function percentile(s){
    return num(s.percentile)?`<div class="md-range"><span style="left:${Math.min(100,Math.max(0,s.percentile))}%"></span></div><small>${fmt(s.percentile,0)}th percentile</small>`:'<small>Insufficient history</small>';
  }
  function move(s){const m=s.moves?.[horizon]||{};return `${signed(m.value,2)} ${esc(m.unit||'')}`;}
  function evidence(s){
    const rel=s.category==='Divergence';
    const chartLabel=rel?'Daily residual history':`${s.label} history (${s.unit})`;
    const body=rel?`<div class="md-facts"><span>Actual move <b>${signed(s.actual,2)} ${esc(s.unit)}</b></span><span>Model-implied <b>${signed(s.expected,2)} ${esc(s.unit)}</b></span><span>126D correlation <b>${fmt(s.correlation,2)}</b></span><span>20D correlation <b>${fmt(s.correlation_20d,2)}</b></span><span>R² <b>${fmt(s.r_squared,2)}</b></span></div>`:
      `<div class="md-facts"><span>Observation <b>${fmt(s.value,3)} ${esc(s.unit)}</b></span><span>Historical z <b>${signed(s.z,2)}σ</b></span><span>${horizon} move <b>${move(s)}</b></span><span>Move z <b>${signed(s.moves?.[horizon]?.z,2)}σ</b></span><span>Baseline <b>${s.n||0} observations</b></span></div>`;
    return `<div class="md-evidence">${body}<div class="md-chart-label">${esc(chartLabel)} · ${esc(s.history?.[0]?.[0]||'')} → ${esc(s.as_of||'')}</div>${spark(s.history,true,chartLabel)}<p>${esc(s.note||s.reason)}</p><p class="md-muted">${rel?'OLS of aligned daily changes, fitted on 126 prior observations; latest observation excluded. A weak or sign-unstable relationship does not qualify for an alert.':'Prior 252 observations; at least 200 needed for level screens. The latest observation is excluded from its baseline. Move z uses at least 60 prior same-horizon changes; overlapping windows are descriptive, not independent tests.'}</p><p class="md-check"><b>Before expressing it:</b> ${rel?'Check the common observation date and close-time mismatch, recent catalysts, and whether the relationship still has economic justification.':s.category==='Curves'?'Check the live curve, instruments and DV01 weights; an unusual yield shape alone does not establish an arbitrage.':s.category==='Relative rates'?'Check policy-path expectations, hedge ratios and funding; nominal spread history alone does not determine fair value.':'Check current pricing, catalysts and positioning. A trend can stay at an extreme.'}</p></div>`;
  }
  function alertFor(s){
    if(status(s)!=='ok')return null;
    const m=s.moves?.[horizon]||{}, z=s.z, p=s.percentile;
    const stretch=num(z)&&Math.abs(z)>=1.5 || num(p)&&(p<=5||p>=95);
    const unusual=num(m.z)&&Math.abs(m.z)>=2;
    if(!stretch&&!unusual)return null;
    const strength=Math.max(stretch&&num(z)?Math.abs(z):0,stretch&&num(p)?Math.abs(p-50)/25:0,unusual?Math.abs(m.z):0);
    const reason=unusual?`${horizon} move ${move(s)} · ${signed(m.z,1)}σ versus prior ${horizon} moves`:`${fmt(p,0)}th percentile · ${signed(z,1)}σ versus prior observations`;
    let question = unusual ? 'Is a new catalyst repricing this market?' : 'Does the macro case justify this stretch?';
    if(s.category==='Curves') question = s.id.includes('2s5s10s')?'Is the 5Y belly out of line with the wings?':'Does the policy path justify this curve shape?';
    if(s.category==='Relative rates')question='Is the policy divergence already priced too far?';
    return {...s,strength,reason,question,flag:unusual?'Unusual move':'Historical stretch'};
  }
  function alertRows(){
    let rows=series().filter(matches).map(alertFor).filter(Boolean);
    packet.opportunities.relationships.filter(matches).forEach(r=>{
      if(status(r)==='ok'&&num(r.z)&&Math.abs(r.z)>=2) rows.push({...r,category:'Divergence',strength:Math.abs(r.z),flag:'Relationship gap',reason:`Daily move residual ${signed(r.z,1)}σ · correlation ${fmt(r.correlation,2)}`,question:'Has the relationship changed, or is one market lagging?'});
    });
    rows.sort((a,b)=>b.strength-a.strength);
    // Limit repeated tenors/curve legs so one move cannot occupy the whole list.
    const counts={};return rows.filter(r=>{let group=r.category==='FX'?r.id.slice(3):r.category==='Rates'||r.category==='Curves'||r.category==='Relative rates'?r.id.split('_')[0]:r.id;group=r.category+group;counts[group]=(counts[group]||0)+1;return counts[group]<=2;});
  }
  function watchlist(){
    const rows=alertRows(); const body=rows.slice(0,10).map((s,i)=>`<details class="md-alert"><summary><span class="md-rank">${String(i+1).padStart(2,'0')}</span><span class="md-alert-copy"><span class="md-alert-title">${esc(s.label)} ${badge(s.flag,s.strength>=2?'hot':'')}</span><span class="md-reason">${esc(s.reason)}</span><span class="md-question">${esc(s.question)}</span></span><span class="md-mini">${spark(s.history)}<small>${esc(s.as_of)}</small></span><span class="md-open">+</span></summary>${evidence(s)}</details>`).join('');
    return `<div class="md-section-head"><div><h3>Worth your attention</h3><p>Ranked by statistical extremeness; related tenors are capped. Click a row to inspect the evidence.</p></div>${badge(rows.length+' qualifying screens')}</div>${body||'<div class="md-empty">No fresh signals meet these thresholds. Try another scope or inspect All data.</div>'}<p class="md-muted md-bottom">Level alerts: |z| ≥ 1.5 or outer 5% of the sample. Move and divergence alerts: |z| ≥ 2. These thresholds prioritize review; they are not trade conviction or win probabilities.</p>`;
  }
  function table(rows){
    return `<div class="md-table-wrap"><table class="md-table"><thead><tr><th>Market / expression</th><th>${horizon} change</th><th>Move z</th><th>Historical position</th><th>Level z</th><th>Observed</th></tr></thead><tbody>${rows.map(s=>`<tr><td><details><summary>${esc(s.label)} ${status(s)!=='ok'?badge(status(s)) : ''}</summary>${evidence(s)}</details></td><td>${move(s)}</td><td class="${Math.abs(s.moves?.[horizon]?.z)>=2?'md-extreme':''}">${signed(s.moves?.[horizon]?.z,1)}σ</td><td>${percentile(s)}</td><td class="${Math.abs(s.z)>=1.5?'md-extreme':''}">${signed(s.z,1)}σ</td><td>${esc(s.as_of||'Unavailable')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function curves(){
    const rows=series().filter(s=>['Curves','Relative rates','Rates'].includes(s.category)&&matches(s));
    return ['Curves','Relative rates','Rates'].map(cat=>`<div class="md-section-head"><div><h3>${cat==='Curves'?'Curve shape & belly':cat==='Rates'?'Outright yield stretches':'Cross-market spreads'}</h3><p>${cat==='Curves'?'Slopes and 2s5s10s flies. A positive fly means the 5Y yield is above the average of its wings.':cat==='Relative rates'?'First country minus second, on exact common observation dates.':'Yield history provides context; it is not a fair-value estimate.'}</p></div></div>${table(rows.filter(s=>s.category===cat))}`).join('');
  }
  function crossAssets(){
    const rels=packet.opportunities.relationships.filter(matches);
    return `<div class="md-section-head"><div><h3>Relationships under pressure</h3><p>Observed daily move versus a 126-observation regression. Weak fits stay visible but cannot trigger alerts.</p></div></div><div class="md-rels">${rels.map(r=>`<details class="md-rel"><summary><span><b>${esc(r.label)}</b><small>Common date ${esc(r.as_of||'unavailable')} · n=${r.n||0}</small></span><span>${badge(status(r)==='ok'?(Math.abs(r.z)>=2?'Divergence':'In line'):status(r),status(r)==='ok'&&Math.abs(r.z)>=2?'hot':'')}<b class="md-rel-score">${signed(r.z,1)}σ</b></span></summary>${evidence({...r,category:'Divergence'})}</details>`).join('')}</div><div class="md-section-head"><div><h3>Macro drivers</h3><p>Changes and stretches across risk, energy, metals, credit and real rates.</p></div></div>${table(series().filter(s=>s.category==='Macro drivers'&&(!query||s.label.toLowerCase().includes(query.toLowerCase()))))}`;
  }
  function carry(){
    return `<div class="md-section-head"><div><h3>Yield advantage versus FX risk</h3><p>A carry shortlist for checking in Bloomberg. The ratio uses a 2Y sovereign yield differential, not executable forward carry.</p></div></div><div class="md-carry-grid">${packet.opportunities.carry.filter(matches).map(r=>`<article class="md-carry"><div>${badge(status(r))}<small>${esc(r.as_of||'No common observation')}</small></div><h4>${r.long?`${esc(r.long)} over ${esc(r.short)}`:esc(r.pair)}</h4><div class="md-carry-ratio">${fmt(r.ratio,2)}<span>yield / FX vol</span></div><div class="md-facts"><span>Yield advantage <b>${fmt(r.differential_bps)}bp</b></span><span>60D realized vol <b>${fmt(r.vol)}%</b></span></div></article>`).join('')}</div><div class="md-note"><b>What is still needed for a trade:</b> forward points or OIS funding, cross-currency basis, transaction costs and roll-down. Those inputs are not in this feed. This screen cannot calculate net carry or tell you a trade is attractive after hedging.</div>`;
  }
  function health(){
    const base=Object.entries(packet.sources||{}).map(([id,s])=>({id,label:id,as_of:s.observation_date,status:s.status,max_age_days:id==='AU_rates'?12:4,url:s.url,note:s.note,error:s.error}));
    const extra=Object.entries(packet.cross_assets?.series||{}).map(([id,s])=>({...s,id}));
    return `<details class="md-health"><summary>Data coverage & methodology <span>${base.concat(extra).filter(s=>status(s)!=='ok').length} sources need attention</span></summary><div class="md-health-grid">${base.concat(extra).map(s=>`<div><b>${esc(s.label)}</b>${badge(status(s))}<small>${esc(s.as_of||'No observation')}</small><a href="${esc(/^https:\/\//.test(s.url)?s.url:'#')}" target="_blank" rel="noopener noreferrer">Source ↗</a><p>${esc(s.note||'')}${s.error?' '+esc(s.error):''}</p></div>`).join('')}</div><p>${esc(packet.opportunities.method.note)} Daily reference data, with different fixing and close times. Gold and copper use vendor continuous futures history, including rolls. Brent and WTI are EIA spot assessments via FRED. Source failures remain unavailable; no substitute prices are invented.</p></details>`;
  }
  function render(){
    const stale=series().filter(s=>status(s)!=='ok').length;
    meta.innerHTML=badge('Daily research snapshot')+`<span>Built ${esc(packet.generated_at.replace('T',' ').replace('Z',' UTC'))}</span>`;
    root.innerHTML=`<div class="md-toolbar"><nav aria-label="Market data views">${views.map(v=>`<button type="button" data-view="${v}" aria-pressed="${v===view}" class="${v===view?'active':''}">${v}</button>`).join('')}</nav><div class="md-filters"><label>Horizon <select id="md-horizon">${['1D','5D','1M','3M'].map(h=>`<option ${h===horizon?'selected':''}>${h}</option>`).join('')}</select></label><label>Scope <select id="md-scope">${['All markets','CAD / AUD / NZD'].map(s=>`<option ${s===scope?'selected':''}>${s}</option>`).join('')}</select></label><label class="md-search">Find <input id="md-search" type="search" value="${esc(query)}" placeholder="Market or expression" /></label></div></div><div class="md-context"><span>${badge('DAILY · NOT LIVE')} Fixings and closing data. ${stale?`${stale} screens have stale or missing inputs.`:'All screen inputs within source publication lags.'}</span><span>Default move window: ${horizon} · Level baseline: up to 252 prior observations</span></div><div class="md-content">${view==='Watchlist'?watchlist():view==='Curves & rates'?curves():view==='Cross-asset'?crossAssets():view==='Carry'?carry():table(series().filter(matches))}</div>${health()}`;
    root.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;render();}));
    root.querySelector('#md-horizon').addEventListener('change',e=>{horizon=e.target.value;render();});
    root.querySelector('#md-scope').addEventListener('change',e=>{scope=e.target.value;render();});
    root.querySelector('#md-search').addEventListener('change',e=>{query=e.target.value;render();root.querySelector('#md-search').focus();});
  }
  fetch('market-state.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('Market packet HTTP '+r.status);return r.json();}).then(p=>{
    if(p.opportunities?.version!==1)throw new Error('The opportunity packet is not available in this build.');packet=p;render();
  }).catch(e=>{meta.textContent='Data unavailable';root.innerHTML=`<div class="md-empty"><h3>Market screens could not load</h3><p>${esc(e.message)}</p><p>No signals can be evaluated without the market packet.</p><button type="button" id="md-retry">Retry</button></div>`;root.querySelector('#md-retry').addEventListener('click',()=>location.reload());});
})();
