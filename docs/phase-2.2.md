# Fase 2.2: backend local

## Arquitectura paso a paso

1. FastAPI carga y valida `config/room.json` al arrancar. Una configuración inválida impide el arranque.
2. Reutiliza `make_frame` de `simulator/simulate_radar.py`. No es necesario ejecutar el simulador en otra terminal. Una única tarea genera una trama cada `update_interval_ms` (100 ms = 10 Hz), independientemente del número de navegadores.
3. `process_frame` valida esquema, radar, fecha con zona horaria, slots únicos (1–3), número de objetivos y valores finitos. Una trama rechazada no sustituye el último estado válido.
4. Convierte mm a m y cm/s a m/s. Aplica la rotación antihoraria configurada y después la traslación del radar:

   `X = radar_x + cos(theta)*x - sin(theta)*y`

   `Y = radar_y + sin(theta)*x + cos(theta)*y`

   Con 0 grados, (1200, 2400) mm se convierte en (3.2, 3.0) m. La velocidad sigue siendo radial; no es una velocidad sobre los ejes X/Y.
5. Marca `inside_room` incluyendo los bordes. Conserva los puntos exteriores sin recortarlos. Solo tolera 1e-9 m por redondeo numérico; no corrige el ruido físico del radar.
6. Guarda el último estado y lo distribuye por `/ws`. Cada cliente tiene una cola de tamaño uno: se sustituye un estado pendiente por el más reciente si el cliente va lento. Las desconexiones liberan sus tareas y colas.

`/ws` es una salida de datos, no una entrada de medidas. La adquisición en esta fase usa la interfaz Python `StateHub.publish`. MQTT y hardware quedan para las fases posteriores. Usar un solo worker: varios procesos tendrían simuladores y estados independientes.

## Ejecutar en Windows y VSCode

Abrir la carpeta del repositorio en VSCode y una terminal PowerShell desde su raíz:

```powershell
cd C:\Users\danie\Desktop\smart-space-digital-twin
# Solo si todavía no existe el entorno:
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Se llama directamente al Python del entorno; no es necesario cambiar la política de ejecución de PowerShell. En VSCode, seleccionar `.venv\Scripts\python.exe` con «Python: Select Interpreter».

## Comprobar HTTP

En otra terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/room | ConvertTo-Json -Depth 6
Invoke-RestMethod http://127.0.0.1:8000/api/state | ConvertTo-Json -Depth 6
```

`/health` devuelve `status: ok` y `simulation_enabled: true`. Devuelve HTTP 503 si la tarea productora termina inesperadamente. `/api/room` devuelve la configuración. `/api/state` devuelve la última trama procesada con coordenadas globales. Repetir la petición para ver cómo cambia. La documentación HTTP está en http://127.0.0.1:8000/docs.

## Comprobar WebSocket

Abrir `/docs` en el navegador, abrir sus herramientas de desarrollo (F12) y ejecutar en la consola:

```javascript
const socket = new WebSocket('ws://127.0.0.1:8000/ws');
let frames = 0;
socket.onmessage = event => {
  const state = JSON.parse(event.data);
  frames++;
  if (frames % 10 === 0) console.log(frames, state);
};
// Al terminar:
// socket.close();
```

El primer mensaje contiene el estado disponible y después llegan aproximadamente diez por segundo. El ejemplo imprime uno de cada diez. Dos pestañas reciben el mismo flujo. Cerrar una no interrumpe la otra. Detener el servidor con Ctrl+C.

Si `simulation.enabled` es `false`, no se inicia el generador, `/api/state` devuelve `null` y el WebSocket espera sin inventar datos. Reiniciar el servidor después de cambiar el JSON: `--reload` no garantiza detectar cambios en archivos JSON.

## Pruebas y alcance

Las pruebas comprueban transformación inversa del simulador con cuatro rotaciones, unidades, bordes y puntos exteriores, rechazo de mensajes inválidos, slots duplicados, ausencia de objetivos, cola acotada, endpoints, dos clientes simultáneos, cadencia aproximada y cierre de tareas. Son pruebas locales; no validan el radar físico ni la red de Raspberry.

Las dependencias de ejecución están en `backend/requirements.txt`; las de pruebas, en `backend/requirements-dev.txt`. No se modifica firmware, Docker Compose, servicios Raspberry ni secretos. Este servidor de desarrollo escucha en localhost.

## Revisar y publicar

Desde la raíz, revisar e incluir únicamente los archivos de esta fase:

```powershell
git diff --check
git diff -- backend/app/main.py backend/requirements.txt
git status --short
git add backend/app/main.py backend/requirements.txt backend/requirements-dev.txt tests/test_backend.py docs/phase-2.2.md
git diff --cached --stat
git commit -m "feat: add phase 2.2 realtime FastAPI backend"
git push
```

Revisar el contenido preparado antes del commit. No usar `git add .`, para evitar incluir cambios ajenos o archivos sensibles.
