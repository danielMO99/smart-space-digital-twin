// -------------------------------------
// Control de simulación desde el frontend
// -------------------------------------

const pauseBtn = document.getElementById("pause-btn");
const resumeBtn = document.getElementById("resume-btn");
const simulationStatus = document.getElementById("simulation-status");

function updateSimulationControls(paused) {
  simulationStatus.textContent = paused
    ? "Simulación pausada"
    : "Simulación en ejecución";

  pauseBtn.disabled = paused;
  resumeBtn.disabled = !paused;
}

let controlBusy = false;

async function loadSimulationStatus() {
  controlBusy = true;
  pauseBtn.disabled = resumeBtn.disabled = true;
  targetCountSelect.disabled = true;
  try {
    const response = await fetch("/api/simulation", {cache: "no-store", signal: AbortSignal.timeout(10000)});

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const state = await response.json();
    updateSimulationControls(state.paused);
    targetCountSelect.value = String(state.target_count);
    confirmSpeed(state.speed_factor);
    speedControlStatus.textContent = "Velocidad confirmada";

  } catch (error) {
    simulationStatus.textContent =
      `No se pudo consultar el estado: ${error.message}`;
    pauseBtn.disabled = resumeBtn.disabled = false;
    speedControlStatus.textContent = `No se pudo consultar la velocidad: ${error.message}. Selecciona un valor para reintentar.`;
    speedControlStatus.dataset.state = "error";
  } finally {
    controlBusy = false;
    targetCountSelect.disabled = false;
    speedSlider.disabled = false;
  }
}

async function controlSimulation(action) {
  if (controlBusy) return;
  controlBusy = true;
  pauseBtn.disabled = true;
  resumeBtn.disabled = true;
  simulationStatus.textContent = "Enviando orden...";

  try {
    const response = await fetch(
      `/api/simulation/${action}`,
      {
        method: "POST", signal: AbortSignal.timeout(10000)
      }
    );

    if (!response.ok) {
      throw new Error(`Error HTTP ${response.status}`);
    }

    const result = await response.json();

    updateSimulationControls(result.paused);

  } catch (error) {
    simulationStatus.textContent =
      `Error al controlar la simulación: ${error.message}`;

    pauseBtn.disabled = false;
    resumeBtn.disabled = false;
  } finally {
    controlBusy = false;
  }
}

pauseBtn.addEventListener("click", () => {
  controlSimulation("pause");
});

resumeBtn.addEventListener("click", () => {
  controlSimulation("resume");
});
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

// Slots que queremos visualizar
const visibleTargets = new Set([1, 2, 3]);

document.querySelectorAll(".target-visibility")
  .forEach(checkbox => {
    checkbox.addEventListener("change", () => {
      const slot = Number(checkbox.value);

      if (checkbox.checked) {
        visibleTargets.add(slot);
      } else {
        visibleTargets.delete(slot);
      }
    });
  });
  
function render(frame) {
  const targets = new Map(frame.targets.map(target => [target.slot, target]));
  slots.forEach(({marker, card, values, note}, index) => {
    const t = targets.get(index+1);
    card.classList.toggle('absent', !t);
    card.hidden = !visibleTargets.has(index + 1);
    const isVisible =
    t?.inside_room && visibleTargets.has(index + 1);

  marker.setAttribute(
    "display",
    isVisible ? "inline" : "none"
  );
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

// --------------------------------------
// Control del número de objetivos
// --------------------------------------

const targetCountSelect =
  document.getElementById("target-count");

const targetControlStatus =
  document.getElementById("target-control-status");

let targetBusy = false;
async function setTargetCount(count) {
  if (targetBusy) return;
  targetBusy = true;
  targetCountSelect.disabled = true;
  targetControlStatus.textContent = "Actualizando objetivos...";

  try {
    const response = await fetch("/api/simulation/targets", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        count: count
      })
    });

    if (!response.ok) {
      throw new Error(`Error HTTP ${response.status}`);
    }

    const result = await response.json();

    targetCountSelect.value = String(result.target_count);

    targetControlStatus.textContent =
      `${result.target_count} objetivos configurados`;

  } catch (error) {
    targetControlStatus.textContent =
      `Error: ${error.message}`;

    // Recuperar el valor real del backend
    try { await loadTargetCount(); }
    catch { targetControlStatus.textContent += " No se pudo recuperar el número actual."; }

  } finally {
    targetBusy = false;
    targetCountSelect.disabled = false;
  }
}

async function loadTargetCount() {
  const response = await fetch("/api/simulation", {cache: "no-store", signal: AbortSignal.timeout(10000)});

  if (!response.ok) {
    throw new Error(`Error HTTP ${response.status}`);
  }

  const state = await response.json();

  targetCountSelect.value = String(state.target_count);
}

targetCountSelect.addEventListener("change", () => {
  const count = Number(targetCountSelect.value);
  setTargetCount(count);
});

// Mostrar la selección al arrastrar; enviar solo al confirmar el cambio.
const speedSlider = document.getElementById("simulation-speed");
const speedValue = document.getElementById("simulation-speed-value");
const speedControlStatus = document.getElementById("speed-control-status");
let speedBusy = false;
let confirmedSpeed = null;

function confirmSpeed(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0 || value > 3) {
    throw new Error("Velocidad recibida no válida");
  }
  confirmedSpeed = value;
  speedSlider.value = String(value);
  // El backend también admite factores intermedios: mostrar el valor real.
  speedValue.textContent = `${value}×`;
}

speedSlider.addEventListener("input", () => {
  if (speedBusy) return;
  speedValue.textContent = `${Number(speedSlider.value)}×`;
  speedControlStatus.textContent = "Pendiente de aplicar";
  speedControlStatus.dataset.state = "pending";
});

async function setSimulationSpeed() {
  if (speedBusy || speedSlider.disabled) return;
  const value = Number(speedSlider.value);
  if (!Number.isFinite(value) || value < 0.5 || value > 3 || !Number.isInteger(value * 2)) return;
  speedBusy = true;
  speedSlider.disabled = true;
  speedControlStatus.textContent = "Actualizando velocidad…";
  speedControlStatus.dataset.state = "pending";
  try {
    const response = await fetch("/api/simulation/speed", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({speed_factor: value}),
      signal: AbortSignal.timeout(10000)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    confirmSpeed(result.speed_factor);
    speedControlStatus.textContent = "Velocidad confirmada";
    speedControlStatus.dataset.state = "success";
  } catch (error) {
    // Una respuesta perdida puede ocultar un cambio aplicado: consultar de nuevo.
    let recovered = false;
    try {
      const response = await fetch("/api/simulation", {
        cache: "no-store", signal: AbortSignal.timeout(10000)
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      confirmSpeed((await response.json()).speed_factor);
      recovered = true;
    } catch {
      if (confirmedSpeed !== null) speedSlider.value = String(confirmedSpeed);
      speedValue.textContent = confirmedSpeed === null ? "—" : `${confirmedSpeed}× (última confirmada)`;
    }
    speedControlStatus.textContent = `Error al actualizar la velocidad: ${error.message}. ${recovered ? "Valor actual recuperado." : "Estado actual sin confirmar."} Puedes reintentar.`;
    speedControlStatus.dataset.state = "error";
  } finally {
    speedBusy = false;
    speedSlider.disabled = false;
  }
}

speedSlider.addEventListener("change", setSimulationSpeed);

start();
loadSimulationStatus();

