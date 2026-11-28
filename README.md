# Smart Space Digital Twin

Gemelo digital 2D: LD2450 → ESP32/ESPHome → MQTT → FastAPI → WebSocket → SVG.
Estado consolidado hasta **P1.2a**. Funciona también con simulación y replay aislado,
sin radar, ESP32 ni Raspberry Pi. Un productor y un worker por instancia.

## Qué está implementado

- Grabación MQTT con bytes originales, importación de informes y replay determinista.
- Adquisición `legacy` por campos y `frames` por informes completos, sin mezcla automática.
- Validación, normalización, transformación de coordenadas únicamente en backend.
- Diagnóstico independiente de conexión, frescura, integridad y frecuencia en `/api/diagnostics`.
- Frontend SVG y contexto de reproducción; `/health` conserva su contrato anterior.

La precisión física multiobjetivo, comparación UART independiente y calibración siguen
pendientes. Los controles/textos de simulador que aparecen en modo directo son una
incidencia de P1.3; no significa que los datos directos se conviertan en simulación.
No se incluyen P1.2b, P1.3 ni P2.

## Instalación reproducible en Windows

Referencia validada: CPython **3.11.9 x64**, Node.js **22.19.0** y Mosquitto **2.1.4 x64**
para integración MQTT. Node solo ejecuta pruebas; no se necesita npm ni compilar frontend.
Versiones Python directas fijadas en `backend/requirements*.txt`; constraints transitivas
para Windows/Python 3.11. No es un lock certificado para Linux/Raspberry u otro Python.

Desde la raíz del clon, con Python y Node instalados:

```powershell
py -3.11 --version
node --version
py -3.11 -m venv .venv
$python = Join-Path $PWD '.venv\Scripts\python.exe'
& $python -m pip install -r backend\requirements-dev.txt
& $python -m pip check
```

No sobrescribir un entorno existente: elegir otro nombre si ya se utiliza para ESPHome.
No copiar entornos virtuales de otra máquina. Solo ejecución: instalar
`backend/requirements.txt`. ESPHome utiliza un entorno independiente; no forma parte de
los requisitos del backend. La instalación inicial necesita acceso al índice de paquetes.

## Simulación segura, sin broker

```powershell
$env:SMARTSPACE_SOURCE = 'simulator'
& $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Abrir http://127.0.0.1:8000/; API en `/docs`, instantánea en `/api/state`, estados en
`/ws`, diagnóstico en `/api/diagnostics`. No abrir el HTML con `file://`.
`config/room.json` habilita el simulador por defecto. No iniciar otro productor.

```powershell
& $python -m simulator.simulate_radar --targets 3 --frames 10
```

## Replay completo sin capturas privadas

Instalar o extraer Mosquitto localmente **sin crear un servicio**. Se requieren
`mosquitto.exe`, `mosquitto_passwd.exe` y las DLL de la distribución; ver
[preparación del broker](docs/mqtt-replay.md). Establecer la ruta de esa instalación,
no una carpeta de trabajo de otra persona:

```powershell
$mosquitto = Read-Host 'Ruta completa a mosquitto.exe'
if (-not (Test-Path -LiteralPath $mosquitto -PathType Leaf)) { throw 'Mosquitto no encontrado' }
$run = Join-Path $PWD ('outputs\replay-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $run | Out-Null
& $python -m mqtt_capture.import_frames --input tests/fixtures/frame_reports/display.synthetic.jsonl --output "$run/display.import.jsonl" --evidence-kind synthetic
& $python -m mqtt_capture.diagnose --input "$run/display.import.jsonl"
& $python -m mqtt_capture.replay_app --input "$run/display.import.jsonl" --mosquitto $mosquitto --acquisition frames --allow-unknown-retain --speed 0.5 --field-ttl 5 --ws-hz 10 --manual-start --http-port 8001
```

Abrir http://127.0.0.1:8001/ e iniciar la reproducción. Fixture **sintética**:
0→1→slots 1+3→3→0→silencio→1. TTL 5 y velocidad 0,5 facilitan la inspección;
el TTL funcional predeterminado sigue siendo 2 s. El lanzador crea su propio broker
en loopback, con credenciales efímeras y puerto aleatorio; publica sin retain.
Ctrl+C cierra la aplicación y el broker. En otra terminal:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/api/diagnostics' | ConvertTo-Json -Depth 12
```

Para legacy se puede usar `tests/fixtures/mqtt_replay/display_hold.synthetic.mqtt.jsonl`
con `--acquisition legacy`. Los generadores, tests y fixtures necesarias se incluyen;
las capturas físicas y los resultados locales se excluyen deliberadamente.

## Pruebas

```powershell
& $python -m pytest -q
node --test tests/frontend.test.mjs
$env:SMARTSPACE_TEST_MOSQUITTO = $mosquitto
& $python -m pytest -m mqtt -q
git diff --check
```

Por defecto pytest excluye `mqtt` y `hardware`, fuerza simulación y prohíbe conectar
Paho en pruebas locales. HTTP/WebSocket usan TestClient en memoria. La compilación
C++ opcional usa `SMARTSPACE_XTENSA_CXX`; los tests de capturas reales usan
`SMARTSPACE_REPLAY_CAPTURE` y `SMARTSPACE_FRAME_CAPTURES`. En un clon público sin
esos recursos se omiten explícitamente; no es una regresión ni una validación física.
No hay pruebas de hardware implementadas: seleccionar solo esa marca devuelve código 5.
El aviso Starlette/httpx es conocido; no se oculta ni cambia dependencias en esta auditoría.

## Hardware y configuración privada

El modo directo existe (`SMARTSPACE_SOURCE=ld2450`, `SMARTSPACE_ACQUISITION=frames|legacy`),
pero **no es portátil sin configurar**: el consumidor y el YAML actual contienen
la dirección del banco original. No arrancarlo para comprobar una instalación nueva.
No hay carga automática de `.env`; `.env.example` y `docker-compose.yml` son placeholders
vacíos, no un despliegue funcional.

`firmware/esp32_base.yaml` requiere ambos headers `ld2450_report*.h` y un archivo local
`firmware/secrets.yaml`. Se ofrece `firmware/secrets.example.yaml` con placeholders;
copiarlo solo si el destino no existe y rellenarlo localmente. ESPHome validado en el
incremento de firmware: **2026.6.5**. No se garantiza compilar con otra versión.

El YAML actual habilita OTA sin contraseña configurada y MQTT sin autenticación/TLS
configurados. Es configuración de laboratorio, **no una plantilla segura para desplegar**.
La publicación del código no corrige esto. No flashear, desplegar ni modificar seguridad
como parte de una comprobación de instalación. Véase la auditoría para riesgos pendientes.

## Documentación actual e histórica

- [Contrato y normalización legacy P1.1b](docs/normalization-p11b.md).
- [Ensayos físicos y sus limitaciones](docs/physical-validation-p11c2.md).
- [Grabación/importación/replay de informes](docs/frame-capture-replay-p11c3.md).
- [Backend frames P1.1c.4](docs/frame-backend-p11c4.md).
- [Diagnóstico P1.2a, contrato y ejemplos](docs/sensor-health-p12a.md).
- [Auditoría y preparación para GitHub](docs/repository-audit.md).

Las guías por incremento conservan resultados y comandos del banco original, incluidas
rutas locales que **no deben copiarse literalmente** a otra máquina. Este README es la
entrada portable actual. `docs/architecture.md`, requisitos y guías de fases tempranas
incluyen diseño objetivo e historia, no acreditan despliegues o funcionalidades futuras.
No publicar `captures/`, `outputs/`, entornos, backups ni secretos. Las fixtures sintéticas
sí se versionan. Consultar AGENTS.md antes de continuar el desarrollo.
