import { project, signedSpeed, socketUrl, validFrame } from './geometry.mjs';
const $ = id => document.getElementById(id);
const colors = ['#6ce5cf', '#ffca76', '#b7a0ff'];
const svg = $('floor');
const slots = [];
let config, socket, retry, stopped = false, delay = 1000, lastArrival = 0;
function status(text, state) { $('connection').textContent = text; $('connection').dataset.state = state; document.body.classList.toggle('stale', state !== 'live'); }
function node(tag, attrs, parent = svg, text) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (text !== undefined) element.textContent = text;
  parent.append(element); return element;
}
function setup() {
  const { room, radar } = config;
  const w = room.width_m * 100, h = room.length_m * 100;
  svg.setAttribute('viewBox', `-45 -30 ${w + 75} ${h + 75}`);
  $('room-name').textContent = room.name;
  $('dimensions').textContent = `${room.width_m} × ${room.length_m} m`;
  $('radar-info').textContent = `Radar ${radar.model} · (${radar.position.x_m}, ${radar.position.y_m}) m`;
  $('source').textContent = config.simulation.enabled ? 'FUENTE / SIMULADOR' : 'FUENTE / EN ESPERA';
  node('rect', {width:w, height:h, fill:'#0b1625', stroke:'#68819a', 'stroke-width':2});
  for (let x = 0; x <= room.width_m; x++) {
    node('line', {x1:x*100, x2:x*100, y1:0, y2:h, stroke:'#263b51'});
    node('text', {x:x*100, y:h+25, 'text-anchor':'middle', 'font-size':12}, svg, x);
  }
  for (let y = 0; y <= room.length_m; y++) {
    const sy = project(0,y,room)[1];
    node('line', {x1:0, x2:w, y1:sy, y2:sy, stroke:'#263b51'});
    node('text', {x:-14, y:sy+4, 'text-anchor':'end', 'font-size':12}, svg, y);
  }
  const [rx, ry] = project(radar.position.x_m, radar.position.y_m, room);
  node('path', {d:`M ${rx} ${ry-9} l 9 9 -9 9 -9 -9 Z`, fill:'#d4e3f4'});
  node('text', {x:rx+15,y:ry+4,'font-size':12},svg,'Radar');
  const markers = node('g', {id:'markers'});
  for (let i = 1; i <= 3; i++) {
    const marker = node('g', {display:'none'}, markers);
    node('circle', {r:12, fill:colors[i-1], stroke:'#0b1220','stroke-width':2}, marker);
    const label = node('text', {'text-anchor':'middle', y:4,'font-size':12,'font-weight':700}, marker, i);
    label.style.fill = '#0b1220';
    const card = document.createElement('article'); card.className = `target t${i} absent`;
    card.innerHTML = `<h3>Objetivo ${i}</h3><div class="metrics"><span>X: <b>—</b></span><span>Y: <b>—</b></span><span>vᵣ: <b>—</b></span></div><p class="muted">Sin detección</p>`;
    $('targets').append(card);
    slots.push({marker, card, values:card.querySelectorAll('b'), note:card.querySelector('p')});
  }
}
function render(frame) {
  const targets = new Map(frame.targets.map(target => [target.slot, target]));
  slots.forEach(({marker, card, values, note}, index) => {
    const t = targets.get(index+1);
    card.classList.toggle('absent', !t);
    marker.setAttribute('display', t?.inside_room ? 'inline' : 'none');
    if (t) {
      const [x,y] = project(t.x_m,t.y_m,config.room);
      marker.setAttribute('transform', `translate(${x} ${y})`);
      values[0].textContent = `${t.x_m.toFixed(2)} m`; values[1].textContent = `${t.y_m.toFixed(2)} m`; values[2].textContent = signedSpeed(t.speed_m_s);
      note.textContent = t.inside_room ? 'Dentro de la habitación' : 'Fuera de la habitación · no representado';
    } else { values.forEach(v => v.textContent = '—'); note.textContent = 'Sin detección'; }
  });
  $('count').textContent = `${frame.targets.length} / 3`;
  $('timestamp').textContent = frame.timestamp;
  $('timestamp').dateTime = frame.timestamp;
}
function connect() {
  if (stopped) return;
  status('Conectando…', 'waiting'); lastArrival = 0;
  socket = new WebSocket(socketUrl(window.location));
  socket.onopen = () => status('Conectado · esperando datos', 'waiting');
  socket.onmessage = event => {
    try {
      const frame = JSON.parse(event.data);
      if (!validFrame(frame) || frame.radar_id !== config.radar.id) throw new Error('Trama inválida');
      render(frame); lastArrival = performance.now(); delay = 1000;
      $('notice').textContent = ''; status('Conectado · en directo', 'live');
    } catch { $('notice').textContent = 'Mensaje inválido descartado.'; }
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    status('Desconectado · reintentando', 'error');
    if (!stopped) { retry = setTimeout(connect, delay); delay = Math.min(delay*2, 10000); }
  };
}
const watchdog = setInterval(() => {
  if (lastArrival && socket?.readyState === WebSocket.OPEN && performance.now()-lastArrival > Math.max(2000, config.simulation.update_interval_ms*5)) status('Sin datos recientes', 'stale');
}, 500);
window.addEventListener('pagehide', () => { stopped=true; clearTimeout(retry); clearInterval(watchdog); socket?.close(); });
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
async function start() {
  try {
    const response = await fetch('/api/room', {signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('Configuración no disponible');
    config = await response.json(); setup(); connect();
  } catch { status('Error al cargar la habitación', 'error'); $('notice').textContent = 'Comprueba FastAPI y recarga la página.'; }
}
start();
