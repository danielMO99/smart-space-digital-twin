# P0.3 - Reproducción determinista MQTT

Reproductor independiente: `python -m mqtt_capture.replay`. Usa la biblioteca
estándar y el `paho-mqtt==2.2.0` ya fijado en P0.1. Conserva P0.2; no importa
FastAPI, no llama a StateHub y no cambia frontend, firmware ni topics.

## Instalación Windows

Desde PowerShell, usar el entorno P0.1 existente:

```powershell
cd C:\Users\danie\Desktop\smart-space-digital-twin
.\.venv-p0\Scripts\python.exe -m pip check
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --help
```

La ejecución virtual no necesita broker ni herramientas nuevas. Para publicación
MQTT se necesita **Mosquitto 2.1.4 x64**, validado en Windows, junto a
`mosquitto_passwd.exe` y las DLL de su distribución. Es una herramienta externa
necesaria para la integración MQTT real, no una nueva dependencia Python.

Obtener la distribución de la [web oficial de Mosquitto](https://mosquitto.org/download/).
Puede instalarse sin registrar un servicio, o extraerse con 7-Zip en una carpeta
local. No ejecutar el instalador con sus opciones por defecto para esta prueba.
Si se dispone de 7-Zip, este procedimiento extrae los binarios sin instalar ni
arrancar servicios (no sobrescribir una carpeta existente):

```powershell
Invoke-WebRequest 'https://mosquitto.org/files/binary/win64/mosquitto-2.1.4-install-windows-x64.exe' -OutFile "$env:TEMP\mosquitto-2.1.4.exe"
& 'C:\Program Files\7-Zip\7z.exe' x "$env:TEMP\mosquitto-2.1.4.exe" "-o$env:LOCALAPPDATA\SmartSpaceTestTools\mosquitto-2.1.4"
$mosquitto = "$env:LOCALAPPDATA\SmartSpaceTestTools\mosquitto-2.1.4\mosquitto.exe"
& $mosquitto -h
```

La ruta debe contener también `mosquitto_passwd.exe` y las DLL extraídas. Si ya
hay una distribución local, basta con asignar su ruta a `$mosquitto`. El programa
no descarga, instala ni modifica servicios por sí mismo.

## Inspección determinista sin red

```powershell
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --input .\captures\ld2450-2026-11-24-01.mqtt.jsonl --dry-run --virtual-clock --events-output .\captures\replay-virtual-01.jsonl
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --input .\captures\ld2450-2026-11-24-01.mqtt.jsonl --dry-run --virtual-clock --events-output .\captures\replay-virtual-02.jsonl
(Get-FileHash .\captures\replay-virtual-01.jsonl).Hash -eq (Get-FileHash .\captures\replay-virtual-02.jsonl).Hash
```

El resultado esperado es `True`. Las salidas deben ser nuevas; no se sobrescriben
archivos existentes ni se crean directorios de salida implícitos. La opción
`--dry-run` no abre sockets. `--virtual-clock` avanza un reloj inyectable sin
esperas reales y solo se admite junto a `--dry-run` en la CLI. Sin reloj virtual,
el dry-run respeta las esperas de la velocidad elegida.

## Publicación exclusivamente aislada

```powershell
# Velocidad real: la captura de referencia dura 300 s.
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --input .\captures\ld2450-2026-11-24-01.mqtt.jsonl --speed 1 --mosquitto $mosquitto
# Diez veces más rápido: 30 s de calendario nominal.
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --input .\captures\ld2450-2026-11-24-01.mqtt.jsonl --speed 10 --mosquitto $mosquitto
# Mitad de velocidad: 600 s nominales.
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --input .\captures\ld2450-2026-11-24-01.mqtt.jsonl --speed 0.5 --mosquitto $mosquitto
```

No se admiten `--broker`, `--port`, URLs, credenciales de producción ni opciones
de bridge. Los metadatos de conexión del archivo original **nunca se usan para
conectar**. Cada ejecución arranca su propio proceso Mosquitto con:

- Listener únicamente en `127.0.0.1`, puerto efímero distinto de 1883.
- Configuración temporal explícita, sin configuración global, bridges o persistencia.
- Una publicación QoS en vuelo por suscriptor (`max_inflight_messages 1`).
- Usuario y contraseña aleatorios, autenticación obligatoria y ACL limitada a los
  diez topics numéricos existentes. Ningún topic de comandos está permitido.
- Credenciales fuera de argumentos, consola y evidencias. Un archivo temporal se
  convierte a hash con `mosquitto_passwd -U`; todo se elimina al cerrar normalmente.
- Proceso propio comprobado antes de conectar y publicar; no se reutiliza un
  listener existente. Al terminar, fallar o pulsar Ctrl+C, se cierra el cliente y
  se termina únicamente el proceso hijo. No se usa `taskkill` ni servicios.

El comando publica en esa instancia efímera y la cierra. La integración automática
añade un suscriptor de verificación dentro de la misma instancia. Esta fase no
conecta la aplicación al replay ni expone un broker para el backend de producción.
La interfaz operativa del reproductor se identifica como `mode=replay`; no se
modifica el frontend. La identificación del origen en la interfaz 2D queda pendiente
de una integración explícita posterior.

## Semántica y temporización

Se valida el archivo entero antes de iniciar el broker: JSON UTF-8 sin claves
duplicadas ni constantes JSON NaN, formato/version 1, UUID de sesión único,
secuencias contiguas desde cero, UTC válido y tiempos monotónicos no decrecientes,
cabecera/cierre, topics exactos, flags, QoS y Base64 canónico. El texto `nan` dentro
de un payload Base64 sí es válido y se reproduce literalmente. No se decodifican
payloads como números, no se interpolan coordenadas y no se normalizan personas.

Cada registro se programa respecto al origen monotónico del archivo:
`scheduled_ns = floor(monotonic_ns / speed)`. La velocidad se representa como
fracción para evitar acumulación de redondeos. Se usan plazos absolutos, no una
cadena de esperas relativas. Los empates se mantienen en orden `sequence`, nunca
se ordenan por UTC ni por topic. Se conserva también el tiempo hasta el cierre.

El reloj real depende del planificador Windows, red y confirmaciones MQTT. El
reproductor espera cada publicación antes de la siguiente; conserva orden y el QoS
recibido original como metadato, pero a velocidades extremas puede llegar tarde. No descarta ni
reordena para compensarlo. Determinismo significa igualdad de bytes, secuencia y
plazos previstos; no garantiza timestamps de recepción idénticos en una red real.

**Retenidos:** se conservan en memoria y en la traza con `original_retain=true` y
`action=omit_retained`. Se excluyen de MQTT, también después de una reconexión
registrada. Esta fase no ofrece una opción para publicarlos como datos nuevos.
Todos los mensajes publicables usan `retain=False` y **QoS 1 uniforme**. Se conserva
el QoS 0/1/2 del archivo en `original_qos`, pero no se reutiliza como QoS de salida.
La prueba con QoS mezclados detectó adelantamientos de mensajes QoS 0 frente al
handshake QoS 2 en el suscriptor. La política uniforme y un único mensaje en vuelo
en Mosquitto evitan esa mezcla y permiten comprobar la secuencia de recepción.
Se cambia deliberadamente la clase de entrega, no los bytes ni los topics.
No se reproduce `mid` ni se fuerza DUP, que pertenecen al transporte de
la sesión original. `original_dup` se mantiene como metadato.

Los eventos `connected`, `disconnected`, `reconnected`, errores y posibles pérdidas
se mantienen en la traza con `action=observe` y `scope=recorder_to_broker`. No son
publicaciones MQTT y **no fuerzan cortes del broker de pruebas**. Describen el
enlace del grabador, no demuestran desconexión del ESP32. Los huecos temporales
permanecen aunque no se publique ningún mensaje en ellos.

`--events-output` produce JSONL derivado `smartspace.mqtt.replay.event`, versión 1,
con secuencia, tiempos fuente/previsto, acción, bytes Base64, QoS de salida y
`original_qos`/`original_retain`.
No copia broker, contraseñas o metadatos arbitrarios de la cabecera. No es una
captura física ni un estado normalizado de FastAPI. `normalized_sha256` resume
la representación JSON canónica de esos eventos (puede diferir del hash del archivo
de salida, que lleva espacios de formato).

## Incompletos y errores

Por defecto se rechazan sesiones sin cierre o marcadas con errores/pérdidas. Para
una sesión íntegramente parseable con huecos conocidos o sin footer:

```powershell
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay --input .\tests\fixtures\mqtt_replay\reconnection.synthetic.mqtt.jsonl --allow-incomplete --dry-run --virtual-clock
```

Se conserva `source_incomplete=true`; el permiso no convierte la evidencia en
completa. JSON truncado, Base64 incorrecto, versión desconocida, secuencias rotas,
topics ajenos y registros posteriores al cierre siempre bloquean la ejecución.
No se saltan líneas defectuosas ni se repara el original.

Una pérdida de la conexión real del replay, un error de publicación o de escritura
detiene el proceso y conserva los recuentos parciales. No se reintenta enviar un
mensaje de entrega incierta: podrían aparecer duplicados. `Ctrl+C` devuelve 130;
éxito devuelve 0; error de datos/ejecución devuelve 1; argumentos inválidos, 2.
La parada de red puede tardar hasta los timeouts configurados, normalmente 5 s.
Si se mata el proceso o Windows termina abruptamente, no se garantiza la limpieza
del proceso hijo/directorio temporal ni el cierre de la traza derivada.

Resumen JSON: `records_read`, `messages_read`, `published`, `planned` (dry-run),
`omitted_retained`, `not_replayed`, `events_observed`, `errors`, `source_errors`,
`source_incomplete`, estado y hashes. `messages_read = published + planned +
omitted_retained + not_replayed`. `published` significa envío completado según Paho:
la confirmación QoS 1 es del broker, no de cada suscriptor. La prueba con suscriptor sí contrasta
la entrega. Errores del archivo original y errores del replay se cuentan por separado.

## Pruebas

```powershell
# Independientes de broker, radar y ESP32.
.\.venv-p0\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.mjs
git diff --check

# Broker temporal propio; selección explícita de pruebas externas.
$env:SMARTSPACE_TEST_MOSQUITTO = $mosquitto
$env:SMARTSPACE_REPLAY_CAPTURE = (Resolve-Path .\captures\ld2450-2026-11-24-01.mqtt.jsonl).Path
.\.venv-p0\Scripts\python.exe -m pytest -q -m mqtt tests\test_mqtt_replay_integration.py
Remove-Item Env:\SMARTSPACE_TEST_MOSQUITTO
Remove-Item Env:\SMARTSPACE_REPLAY_CAPTURE
```

Sin `SMARTSPACE_REPLAY_CAPTURE`, se omite solamente el caso opcional de evidencia
física; la fixture sintética y la caída del broker siguen probándose. Seleccionar
`mqtt` sin indicar Mosquitto falla explícitamente. El entorno solo acepta la ruta
al ejecutable y al archivo, nunca un host o puerto de broker.

Las [fixtures sintéticas](../tests/fixtures/mqtt_replay/README.md) cubren 0/1/2/3,
slots no consecutivos, ejes parciales/asíncronos, NaN, retenidos, huecos y reconexión.
La integración compara orden, bytes y QoS de salida 1 y abre un suscriptor tardío para comprobar
que no quedó ningún mensaje retenido. También comprueba parada ante caída real
del broker. Los originales locales permanecen excluidos de Git.

## Límites y siguiente fase

La captura física de referencia solo contiene novedades del slot 1. Reproducirla
no valida múltiples personas ni recupera información ausente. Las fixtures de
tres slots validan transporte/temporización, no el radar. Antes de validar P1 hacen
falta capturas físicas con 0→1→2→3→0, marcas de presencia independientes, cambios
finito/NaN y diagnóstico por etapa. La normalización de medidas asíncronas, TTL,
unidades, asociación de slots y presentación de origen replay siguen pendientes.
El lector mantiene la captura completa en memoria; no se plantea streaming de
archivos de tamaño ilimitado en P0.3. No se implementa ni inicia P1.

Referencias: [Paho Client y confirmaciones de publicación](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html),
[configuración Mosquitto](https://mosquitto.org/man/mosquitto-conf-5.html),
[mosquitto_passwd](https://mosquitto.org/man/mosquitto_passwd-1.html).
