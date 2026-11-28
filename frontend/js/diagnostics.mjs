export const states = {initializing:'Esperando datos',observing:'Periodo de observación',normal:'Funcionamiento normal',frequency_degraded:'Frecuencia degradada',stale:'Telemetría caducada',disconnected:'MQTT desconectado',integrity_problem:'Problemas de integridad',diagnostic_limited:'Diagnóstico limitado',unavailable:'Diagnóstico no disponible'};
const labels = {telemetry_stale:'Telemetría caducada',low_acceptance_frequency:'Frecuencia de aceptación baja',mqtt_disconnected:'MQTT backend-broker desconectado',telemetry_waiting:'Esperando telemetría',recent_integrity_issues:'Incidencias recientes de integridad',diagnostic_window_truncated:'Ventana incompleta',no_mqtt_diagnostic_engine:'Sin motor MQTT (simulación o inicio)'};
export const number = (v,unit='') => typeof v==='number' && Number.isFinite(v) ? `${Number(v.toFixed(3))}${unit}` : 'No disponible';
export function validate(d) {
  if(d?.schema_version!==1 || !d.service || !d.acquisition || d.acquisition.schema_version!==1 || !Object.hasOwn(states,d.acquisition.overall) || !Array.isArray(d.acquisition.history) || !Array.isArray(d.acquisition.reasons)) throw Error('Contrato inválido');
  if(d.acquisition.history.length>8192) throw Error('Histórico excesivo');
  return d;
}
export function model(data) {
  const {service:s,acquisition:a}=validate(data),f=a.frequency||{},t=a.freshness||{};
  return {state:a.overall,title:states[a.overall],reasons:a.reasons.map(x=>labels[x]||x).join(' · ')||'Sin motivos de degradación',
    rows:[['Fuente / modo',`${{live:'Directo',replay:'Reproducción',simulation:'Simulación'}[a.source]||a.source} / ${a.mode}`],['Servicio backend',s.status==='ok'?'Operativo':'Error'],['MQTT backend-broker',a.mqtt==null?'No disponible':a.mqtt.connected?'Conectado':'Desconectado'],['Conectividad del dispositivo','No observable por esta conexión'],['MQTT recibida',number(f.received_hz,' Hz')],['MQTT aceptada',number(f.accepted_hz,' Hz')],['Procesamiento ESP32',number(f.esp_processing_hz,' Hz')],['WebSocket observada / configurada',`${number(f.ws_observed_hz,' Hz')} / ${number(f.ws_configured_hz,' Hz')}`],['Edad del último recibido',number(t.last_received_age_s,' s')],['Edad del último válido',number(t.last_valid_age_s,' s')],['Frescura / TTL',`${({fresh:'Vigente',stale:'Caducada',waiting:'Esperando',disconnected:'Desconectada'})[t.state]||'No disponible'} / ${number(t.ttl_s,' s')}`],['Detecciones actuales',a.current_targets==null?'Desconocidas':number(a.current_targets)],['Ocupación física','Desconocida'],['Ventana histórica',a.memory==null?'No disponible':a.memory.window_complete?'Completa':'Incompleta']],
    clock:a.time_basis==='virtual_backend_monotonic'?'Tiempo virtual del ensayo':a.source==='replay'?'Tiempo real del backend durante replay; ESP32 histórico':'Tiempo monotónico del backend',a,s};
}
export function history(a) {
  const end=a.sampled_monotonic_s;
  if(!Number.isFinite(end)) return {segments:[],points:[],threshold:null};
  const rows=a.history.filter(r=>Number.isFinite(r.monotonic_s)&&r.monotonic_s>=end-60&&r.monotonic_s<=end).slice(-8192);
  const threshold=a.mode==='frames'&&Number.isFinite(a.policy?.minimum_hz)?a.policy.minimum_hz:null;
  const max=Math.max(1,threshold||0,...rows.map(r=>Number.isFinite(r.accepted_hz)?r.accepted_hz:0));
  const segments=[],points=[];let segment=[],previous=null;
  for(const r of rows) {
    const valid=typeof r.accepted_hz==='number'&&Number.isFinite(r.accepted_hz)&&r.accepted_hz>=0;
    if(!valid || (previous!==null&&(r.monotonic_s-previous>2||r.monotonic_s<=previous))) {if(segment.length)segments.push(segment);segment=[];}
    if(valid){const point=[40+(r.monotonic_s-end+60)*8,150-r.accepted_hz/max*120];segment.push(point);points.push(point);}
    previous=r.monotonic_s;
  }
  if(segment.length)segments.push(segment);
  return {segments,points,threshold:threshold===null?null:150-threshold/max*120,max};
}
export function poll({fetcher=fetch,onData,onError,onPending=()=>{},schedule=setTimeout,cancel=clearTimeout,timeout=3000}) {
  let stopped=false,timer=null,deadline=null,controller=null;
  async function tick(){
    if(stopped)return;
    controller=new AbortController();onPending();
    deadline=schedule(()=>{controller.abort();if(!stopped)onError();},timeout);
    try {const r=await fetcher('/api/diagnostics',{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('HTTP');const data=validate(await r.json());if(!stopped&&!controller.signal.aborted)onData(data);}
    catch {if(!stopped)onError();}
    finally {cancel(deadline);deadline=null;if(!stopped)timer=schedule(tick,1000);}
  }
  tick();return ()=>{stopped=true;cancel(timer);cancel(deadline);controller?.abort();};
}
export function mount(root) {
  const doc=root.ownerDocument,el=(tag,text,parent=root)=>{const n=doc.createElement(tag);if(text!==undefined)n.textContent=text;parent.append(n);return n;};
  const summary=root.querySelector('summary'),status=el('p','Consultando diagnóstico…');status.setAttribute('role','status');
  const content=el('div');
  const show=data=>{
    const m=model(data);status.textContent='Diagnóstico vigente · consulta HTTP recibida';summary.textContent=`Diagnóstico del sensor · ${m.title}`;root.dataset.state=m.state;
    const technicalOpen=content.querySelector('details')?.open===true;
    const technicalFocus=doc.activeElement===content.querySelector('details summary');
    content.replaceChildren();el('p',m.reasons,content);const grid=el('dl',undefined,content);grid.className='diagnostic-grid';
    for(const [label,value] of m.rows){const cell=el('div',undefined,grid);el('dt',label,cell);el('dd',value,cell);}
    el('p','Edad = tiempo desde recepción, no latencia física extremo a extremo. Cero detecciones no confirma una habitación vacía.',content);
    const h=history(m.a);el('h3','Frecuencia de aceptación · últimos 60 s disponibles',content);el('p',m.clock,content);
    const ns='http://www.w3.org/2000/svg',svg=doc.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 560 185');svg.setAttribute('role','img');svg.setAttribute('aria-label','Histórico de aceptación en Hz. Los huecos no se interpolan.');svg.classList.add('diagnostic-chart');content.append(svg);
    function node(tag,attrs,text){const n=doc.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text)n.textContent=text;svg.append(n);}
    node('path',{d:'M40 25 V150 H520',stroke:'currentColor',fill:'none'});
    if(h.threshold!==null)node('line',{x1:40,x2:520,y1:h.threshold,y2:h.threshold,stroke:'#ffca76','stroke-dasharray':'5 4'});
    for(const points of h.segments)node('polyline',{points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#6ce5cf','stroke-width':2});
    for(const [cx,cy]of h.points)node('circle',{cx,cy,r:2,fill:'#6ce5cf'});
    node('text',{x:3,y:30},`${number(h.max)} Hz`);node('text',{x:10,y:154},'0');node('text',{x:40,y:175},'−60 s');node('text',{x:475,y:175},'ahora');
    el('p',h.points.length?`${h.points.length} muestras disponibles. Umbral del backend: ${number(m.a.mode==='frames'?m.a.policy?.minimum_hz:null,' Hz')}. Huecos >2 s o muestras desconocidas: trazo interrumpido.`:'Sin muestras conocidas disponibles.',content);
    const details=el('details',undefined,content);details.open=technicalOpen;const technicalSummary=el('summary','Contadores y datos técnicos',details);if(technicalFocus)technicalSummary.focus({preventScroll:true});
    const names={received:'Recibidos',accepted:'Aceptados',invalid:'Inválidos',retained:'Retenidos rechazados',duplicate:'Duplicados',conflicting_duplicate:'Conflictos',out_of_order:'Fuera de orden',clock_regression:'Regresiones temporales',sequence_gaps:'Saltos de secuencia',missing_sequences:'Secuencias ausentes',boot_changes:'Cambios de sesión',unexpected:'Topics inesperados',retired_boot:'Sesión retirada'};
    for(const [k,label]of Object.entries(names))el('p',`${label}: ${number(m.a.integrity?.counters?.[k])}`,details);
    el('p',`Mensajes aceptados: ${number(m.a.accepted_messages)} · Errores del callback: ${number(m.s.callback_errors)}`,details);
    el('h3','ESP32: acumulados de origen / incrementos observados',details);
    for(const k of ['invalid_reports','offline_reports','decimated_reports','enqueue_failures','previous_callback_max_us'])el('p',`${k}: ${number(m.a.esp32?.accumulated?.[k])} / ${k==='previous_callback_max_us'?'No aplicable (máximo histórico en µs)':number(m.a.esp32?.observed_increments?.[k])}`,details);
    el('p',`Reinicios de contadores: ${number(m.a.esp32?.counter_resets)}`,details);
    el('p',`boot_id: ${m.a.session?.boot_id??'No disponible'} · Secuencia: ${m.a.session?.last_seq??'No disponible'}`,details);
  };
  return poll({onData:show,onPending:()=>{status.textContent='Consultando · la muestra anterior corresponde a la última respuesta';},onError:()=>{summary.textContent='Diagnóstico del sensor · API no disponible';status.textContent='Diagnóstico no vigente: respuesta ausente o inválida. Se reintentará automáticamente.';root.dataset.state='api-error';content.replaceChildren();}});
}
