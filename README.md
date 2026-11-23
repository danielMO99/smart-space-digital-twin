# smart-space-digital-twin

Gemelo digital 2D con la arquitectura ESPHome → MQTT → FastAPI → WebSocket →
HTML/CSS/JavaScript y SVG. También funciona con un simulador Python, sin ESP32,
radar ni broker. FastAPI sirve la API y el frontend desde el mismo proceso.

## Base reproducible P0

Entorno de referencia: **Windows x64, CPython 3.11.9 y Node.js 22.19.0**.
Node solo es necesario para las pruebas JavaScript; no hay instalación npm ni
compilación del frontend. Usar un Python 3.11 instalado y ejecutable: una carpeta
`.venv` no incluye necesariamente el intérprete base al que apunta.

Las versiones directas están fijadas en `backend/requirements.txt` y
`backend/requirements-dev.txt`. `backend/constraints-py311-windows.txt` fija
también las dependencias transitivas de la instalación de referencia. Las
constraints restringen versiones, pero no instalan paquetes por sí mismas:
la instalación de ejecución no añade pytest ni HTTPX.

Se incluye `paho-mqtt` 2.x para la integración LD2450 local previa, cuyo puente
utiliza `mqtt.CallbackAPIVersion.VERSION2` y se importa también en modo simulador.
Ese puente y su conexión al backend todavía no forman parte de este incremento
P0: en una copia que solo contenga este commit, la adquisición es simulada.
ESPHome se mantiene fuera de estas dependencias: usar un entorno separado para
firmware y conservar su versión instalada. Este incremento no lo actualiza.

La resolución está validada para el entorno Windows indicado. No es un lock
multiplataforma: antes de usar Linux/Raspberry u otra versión de Python hay que
resolver y comprobar sus dependencias específicas, sin desplegar automáticamente.

## Instalar en PowerShell

Ejecutar desde la raíz de este repositorio. Comprobar primero los intérpretes:

```powershell
py -3.11 --version
node --version
```

Para un entorno nuevo:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Para ejecutar sin herramientas de pruebas, instalar solo
`backend\requirements.txt`. No hace falta activar el entorno ni cambiar la
política de ejecución de PowerShell. En VSCode seleccionar su `Scripts\python.exe`.
La primera instalación necesita acceso al índice de paquetes.

Si `py` no encuentra Python o `.venv\Scripts\python.exe --version` falla,
instalar CPython 3.11 o indicar la ruta de un intérprete funcional:

```powershell
# Sustituir la ruta por la del Python 3.11 realmente instalado.
& 'C:\ruta\Python311\python.exe' -m venv .venv-p0
.\.venv-p0\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv-p0\Scripts\python.exe -m pip check
```

Crear `.venv-p0` solo si no existe, conservando el entorno anterior (puede contener
ESPHome). En los comandos siguientes sustituir `.venv` por `.venv-p0` si se usa
esta alternativa. No versionar entornos virtuales ni copiar `site-packages` desde
otro entorno para dar por validada una instalación limpia.

## Ejecutar el simulador y el frontend

```powershell
$env:SMARTSPACE_SOURCE = 'simulator'
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Abrir [el frontend](http://127.0.0.1:8000/) o
[la documentación HTTP](http://127.0.0.1:8000/docs). No abrir el HTML mediante
`file://`. La configuración actual habilita tres objetivos a intervalos de 100 ms.
`simulation.enabled` debe ser `true` para generar medidas en este modo.

El backend inicia el simulador; no hace falta otro productor. Mantener **un solo
worker** porque `StateHub` reside en memoria. `/api/state` entrega la instantánea
y `/ws` distribuye estados; no recibe adquisición ni comandos.

También se puede ejecutar únicamente el generador de JSON:

```powershell
.\.venv\Scripts\python.exe -m simulator.simulate_radar --targets 3 --frames 10
```

## Modo LD2450 local previo (no incluido en P0)

Este apartado describe los cambios locales de integración anteriores a P0.
Solo se aplica si están presentes `backend/app/mqtt_consumer.py`,
`backend/app/radar_bridge.py` y la selección de fuente en `backend/app/main.py`.
Esos cambios se conservan fuera del commit P0. En un clon que solo contenga P0,
`SMARTSPACE_SOURCE=ld2450` no habilita adquisición física y se sigue simulando.

Parar primero el servidor del simulador. El modo físico requiere el ESP32/radar
ya configurado y el broker accesible en la dirección actualmente definida en el
consumidor MQTT; no se inicia ni configura un broker desde este proyecto.

```powershell
$env:SMARTSPACE_SOURCE = 'ld2450'
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

La dirección, el puerto y los topics siguen definidos en el código existente.
No hay carga automática de `.env`; `.env.example` y `docker-compose.yml` siguen
siendo archivos vacíos, no procedimientos de instalación. Este P0 no certifica
la coherencia de medidas, la detección múltiple ni la salud del sensor real.

## Pruebas sin broker ni hardware (por defecto)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.mjs
git diff --check
```

La suite Python local se fuerza a `SMARTSPACE_SOURCE=simulator`, aunque la terminal
tenga exportado `ld2450`. Además, cualquier intento de conexión Paho MQTT desde
una prueba local falla inmediatamente. No se arranca Uvicorn ni un servidor
externo: las pruebas HTTP/WebSocket usan `TestClient` en memoria.

| Marca pytest | Alcance | Selección |
| --- | --- | --- |
| `unit` | Transformaciones, validación y StateHub en memoria | `python -m pytest -q -m unit` |
| `integration` | API, WebSocket y recursos frontend en proceso | `python -m pytest -q -m integration` |
| `mqtt` | Futuras pruebas con broker aislado | `python -m pytest -q -m "mqtt and not hardware"` |
| `hardware` | Futuras pruebas con ESP32/radar real | `python -m pytest -q -m hardware` |

`pytest.ini` excluye `mqtt` y `hardware` por defecto y rechaza marcas desconocidas.
Actualmente hay 14 casos unitarios y 3 de integración local, más 4 JavaScript.
**Todavía no existen pruebas MQTT o de hardware**: sus selecciones no recogen
casos y pytest devuelve código 5; esto no equivale a una validación satisfactoria.

Con la base fijada, Starlette emite un aviso de deprecación por el uso de HTTPX
en `TestClient`. Las pruebas pasan; el aviso no se oculta. La migración de ese
cliente de pruebas queda pendiente de una actualización de dependencias separada.

Al añadir pruebas externas, marcarlas explícitamente (`mqtt`, `hardware`, o ambas)
y adquirir conexiones/dispositivos en fixtures, nunca al importar un módulo.
Configurar un broker aislado antes de seleccionarlas. No mezclar los marcadores
locales `unit`/`integration` con los externos. Las pruebas JavaScript existentes
solo cubren funciones puras, no interacciones de navegador.

Para comprobar el aislamiento frente a una terminal configurada para el radar:

```powershell
$env:SMARTSPACE_SOURCE = 'ld2450'
.\.venv\Scripts\python.exe -m pytest -q
$env:SMARTSPACE_SOURCE = 'simulator'
```

## Actualizar la base de dependencias

Actualizar las versiones directas de forma deliberada. Resolverlas en un entorno
Windows/Python 3.11 limpio y regenerar las constraints a partir de `python -m pip
freeze` de ese entorno, sin incorporar ESPHome ni herramientas ajenas al backend.
Al cambiar versiones, retirar temporalmente la referencia a las constraints
anteriores para resolver las nuevas y restaurarla después de regenerarlas.

Comprobar `pip check`, instalar de nuevo desde los archivos resultantes en un
segundo entorno limpio y ejecutar las pruebas locales antes de aceptar el cambio.
Un resultado local correcto no valida broker, radar, temporización física ni
despliegue. Las guías de fases en `docs/` conservan contexto histórico; este README
es la referencia de instalación y selección de pruebas para P0.
