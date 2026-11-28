# P0.2 — Captura de evidencia MQTT

Grabador independiente de FastAPI: `mqtt_capture/record.py`. Usa exclusivamente
la biblioteca estándar y `paho-mqtt==2.2.0`, con callbacks VERSION2 y MQTT 3.1.1.
No importa el backend, no genera estados normalizados, no publica mensajes y no
incluye un reproductor. Suscribir y confirmar paquetes MQTT no envía comandos al
ESP32. Puede observar la telemetría mientras funciona el consumidor existente.

## Preparar Windows

Desde PowerShell, en la raíz del repositorio, usar el entorno creado en P0.1:

```powershell
cd C:\Users\danie\Desktop\smart-space-digital-twin
.\.venv-p0\Scripts\python.exe -m mqtt_capture.record --help
```

Si se usa otro entorno funcional, sustituir `.venv-p0` por su ruta. La instalación
general está en el README. Para un entorno destinado solamente al grabador basta
con instalar `paho-mqtt==2.2.0`; no se necesita FastAPI, ESPHome ni Node.js.

El broker y el ESP32/radar deben estar operativos antes de la captura real. Este
programa no los configura ni arranca servicios. El valor por defecto del broker
es el existente en el proyecto (`192.168.1.200:1883`). No se ha comprobado aquí su
disponibilidad ni se ha realizado una captura del radar real.

## Iniciar una captura real de cinco minutos

```powershell
cd C:\Users\danie\Desktop\smart-space-digital-twin
.\.venv-p0\Scripts\python.exe -m mqtt_capture.record --broker 192.168.1.200 --port 1883 --duration 300 --output .\captures\ld2450-2026-11-24-01.mqtt.jsonl
$LASTEXITCODE
```

El directorio de salida se crea si falta. El archivo debe ser nuevo: si existe,
se rechaza sin modificarlo ni conectar al broker. Cambiar el sufijo `01` para
otra sesión. No se solicita confirmación antes de conectar al ejecutar este comando.

`--broker` admite host o IP, no URL ni credenciales. `--port` admite 1–65535;
`--duration` es un número positivo y finito de segundos (por defecto 60), contado
desde el inicio de la sesión, incluyendo intentos de conexión y reconexiones.
`--output` es obligatorio. No hay opción para ampliar o cambiar topics.

**Ctrl+C** solicita una parada ordenada: termina la escritura actual, desconecta,
escribe el resumen final y cierra el archivo. El manejador SIGINT no interrumpe
una línea JSON a mitad. Las esperas normales del bucle son de hasta 100 ms; una
conexión TCP puede tardar hasta 2 s. La resolución DNS depende del sistema y puede
retrasar tanto la parada como el límite de duración. Usar la IP evita esa resolución.
Cerrar la terminal o matar el proceso no equivale a Ctrl+C y puede truncar el archivo.

## Topics existentes que se capturan

Se utilizan los nombres que reconoce `backend/app/mqtt_consumer.py` y las entidades
numéricas de `firmware/esp32_base.yaml`. ESPHome forma sus topics por defecto como
`topic_prefix/sensor/object_id/state`. No se modifica ninguno de esos archivos.

- `smartspace/esp32/sensor/n__mero_de_objetivos/state`
- `smartspace/esp32/sensor/objetivo_1_x/state`
- `smartspace/esp32/sensor/objetivo_1_y/state`
- `smartspace/esp32/sensor/objetivo_1_velocidad/state`
- `smartspace/esp32/sensor/objetivo_2_x/state`
- `smartspace/esp32/sensor/objetivo_2_y/state`
- `smartspace/esp32/sensor/objetivo_2_velocidad/state`
- `smartspace/esp32/sensor/objetivo_3_x/state`
- `smartspace/esp32/sensor/objetivo_3_y/state`
- `smartspace/esp32/sensor/objetivo_3_velocidad/state`

`n__mero` conserva literalmente el identificador usado por el consumidor actual.
La suscripción es a esos diez topics exactos, sin comodines. La lista se limita a
las medidas numéricas del consumidor existente; no incluye presencia binaria,
heartbeat, diagnósticos, discovery ni estados/comandos de interruptores. Mensajes
de otros topics se descartan sin guardar su contenido y se cuentan como ignorados.
Si el firmware instalado publica nombres diferentes, esta captura puede quedar
sin datos: se debe contrastar la configuración instalada, no inventar alias.

Se solicita QoS 2 para no reducir el QoS del publicador cuando el broker lo admite.
El SUBACK registra el QoS concedido por topic; el QoS de cada mensaje es el recibido,
no una garantía de la configuración original. Un SUBACK rechazado o incompleto
produce una captura incompleta. La sesión MQTT es limpia y utiliza un client ID
único para no expulsar al consumidor existente.

## Formato JSONL, versión 1

Cada línea es un objeto JSON UTF-8 independiente con estos campos comunes:

| Campo | Significado |
| --- | --- |
| `format` | `smartspace.mqtt.capture` |
| `schema_version` | `1` |
| `session_id` | UUID único de la sesión |
| `sequence` | Índice desde cero; orden de escritura de todos los registros |
| `record_type` | `session_start`, `message`, `event` o `session_end` |
| `timestamp_utc` | Hora UTC de recepción/registro, ISO 8601 con `Z` |
| `monotonic_ns` | Nanosegundos relativos al inicio; no cambian con ajustes del reloj UTC |

`session_start.metadata` guarda host, puerto, duración, topics, QoS solicitado,
protocolo, sesión limpia, versión de Paho y codificación. No guarda argumentos
completos de la terminal, variables de entorno, contraseñas ni credenciales.
Esta versión no ofrece autenticación ni TLS; no pasar contraseñas dentro de
`--broker`. Si el broker exige autenticación, esta versión necesita una ampliación
explícita antes de utilizarlo. No importa secretos de ESPHome ni archivos `.env`.

Un registro `message` añade `topic`, `payload_base64`, `qos`, `retain`, `dup`, `mid`
y `connection` (ordinal de conexión confirmada). El timestamp se toma al entrar
en la captura del mensaje, antes de codificar los bytes. No se decodifica como
texto ni se eliminan espacios, saltos de línea, valores no válidos, payloads
vacíos, duplicados o mensajes retenidos. Por tanto, las capturas preservan el
contenido original de las medidas; no son archivos anonimizados ni normalizados.

Los tiempos son los de recepción por el callback del grabador, no los de medida
en el radar ni los de llegada del paquete a la tarjeta de red. `mid` es un ID MQTT
que puede reutilizarse, no una secuencia del sensor. `retain` y `dup` son los flags
que entrega el broker al cliente, no reconstrucciones de la publicación original.

Eventos registrados:

- `connection_attempt` y `reconnection_attempt` (incluidos reintentos iniciales).
- `connected`, `reconnected`, `subscription_requested` y `subscribed`.
- `disconnected` con `expected`, y `possible_loss` para huecos observados.
- `error` con etapa, código numérico o clase de excepción; nunca texto libre de
  excepciones ni propiedades arbitrarias del broker que puedan incluir secretos.
- `disconnect_requested` al terminar.

El grabador gestiona un único bucle de red Paho y reintentos separados por un
segundo; espera hasta cinco segundos por CONNACK/SUBACK. No usa el StateHub ni
su cola de último estado. Escribe y hace `flush` por registro, sin una cola local
que descarte mensajes. Al finalizar sincroniza el archivo con `fsync`.

## Cierre, errores y pérdidas

`session_end` indica `finalized: true`, motivo de parada, estado, mensajes
recibidos/escritos/ignorados, conexiones, desconexiones inesperadas y errores.

- Código de salida **0**, resumen `complete`: hubo telemetría y suscripción
  confirmada, sin errores ni desconexiones inesperadas observadas, y cierre por
  duración o Ctrl+C. **No demuestra ausencia de pérdidas del radar o broker**.
- Código **1**: captura incompleta o error de archivo. Puede haber un resumen
  `incomplete` y medidas útiles. Conservarlo como evidencia del fallo.
- Código **2**: argumentos inválidos; no comienza una captura.

Una sesión sin mensajes es incompleta; no se transforma en cero objetivos. Un
mensaje real cuyo payload sea `0` sí se conserva como medida válida. Una caída y
posterior reconexión mantiene la sesión y sus mensajes, repite la suscripción y
deja el resultado como incompleto por el hueco observado.

`lost_messages` es siempre `null`: sin secuencia emitida por el sensor no se pueden
contar pérdidas. QoS 0, publicación detenida, red, broker o escritura lenta pueden
provocar pérdidas no detectables. No se promete captura sin pérdidas ni se elimina
telemetría por ser antigua o retenida. Las entidades separadas tampoco pasan a ser
una trama temporalmente coherente por estar juntas en el archivo.

Si falla la escritura, se detiene la captura y se informa por stderr con código 1.
No se intenta añadir registros a una línea posiblemente truncada. Un disco que no
admite escritura tampoco puede guardar su propio evento de error. Un archivo sin
`session_end`, con JSON inválido o secuencias interrumpidas es incompleto. Exigir
tanto el resumen como código de salida 0: un error final de sincronización/cierre
puede ocurrir después de escribir el resumen. Ningún marcador garantiza durabilidad
frente a un fallo de alimentación.

## Pruebas y conservación

```powershell
.\.venv-p0\Scripts\python.exe -m pytest -q tests\test_mqtt_capture.py
.\.venv-p0\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.mjs
git diff --check
```

Las pruebas nuevas son unitarias (`unit`), con cliente y relojes inyectados, sin
broker ni esperas de red. Comprueban bytes, orden, relojes, sesiones, selección de
topics, reconexión, errores, Ctrl+C, archivos existentes y fallos de disco. Las
pruebas MQTT/hardware siguen siendo categorías separadas: estos tests no validan
el broker, los nombres realmente publicados por el dispositivo ni la detección
de varias personas. No se ha desplegado ni ejecutado nada en Raspberry.

`captures/` y los archivos `*.mqtt.jsonl` se excluyen de Git. Solo se permiten
futuras fixtures pequeñas y revisadas bajo `tests/fixtures/`. No versionar capturas
reales sin revisión. Conservar el original separado de cualquier normalización o
análisis posterior; el reproductor queda fuera de P0.2.
