# P1.1c.1 — Informes decodificados completos

## Alcance

Solo firmware de adquisición y documentación/pruebas. No se flashea, no se conecta a producción ni se cambia radar, baudios, pines, zonas o modo. Backend, frontend, grabador, reproductor, capturas y fixtures existentes permanecen intactos. El cierre manual de P1.1b está en `normalization-p11b.md`; sus mejoras pendientes no se implementan aquí.

## Evidencia de coherencia

Se contrastó `research/P1.1c-LD2450.md` con ESPHome **2026.6.5 instalado**, sin actualizarlo:

- `ld2450/__init__.py` declara `on_data` y registra `add_on_data_callback`.
- `ld2450.cpp::handle_periodic_data_` actualiza los tres grupos X/Y/velocidad/resolución, cuentas y presencia antes de `data_callback_.call()`.
- `Sensor::publish_state` actualiza raw_state antes de aplicar los filtros. `get_raw_state()` devuelve ese valor.
- `SensorWithDedup`/`Deduplicator` omiten solo valores iguales; una transición a desconocido publica NaN y una recuperación del mismo valor previo vuelve a publicar. Inicialmente raw_state es NaN. Por ello los valores repetidos no son antiguos incorrectos al leer dentro de este callback.
- YAML asigna IDs a las nueve entidades existentes y añade tres resoluciones internas, sin publicaciones individuales nuevas. No toca nombres ni filtros existentes. El generado conserva TimeoutFilterLast(1000) y ThrottleWithPriorityNanFilter(1000), y registra los doce sensores en sus índices 0–2.
- La lambda copia los doce valores a un array local, síncronamente, antes de serializar o encolar. No usa `.state`, intervalos ni callbacks individuales como disparador.

La garantía es **mismo informe aceptado y decodificado por el componente**, no bytes crudos ni instante físico de adquisición. El parser 2026.6.5 tiene las limitaciones documentadas en Work (longitud mínima 29 y delimitadores): no se modifica ni se atribuye una causa al aviso de longitud. La equivalencia con cada trama de 30 bytes del cable queda pendiente de comparación independiente. Tampoco mejora por sí sola la detección física multiobjetivo.

## Contrato definitivo

Topic nuevo: `smartspace/esp32/radar/frame/v1`; UTF-8 JSON, QoS 0, **retain=false**. Los topics previos se conservan. No hay consumidor nuevo en backend ni cambios en grabador/reproductor.

`contracts/ld2450-frame-v1.schema.json` especifica tipos y rangos; `contracts/ld2450-frame-v1.examples.json` contiene cuatro ejemplos **sintéticos**, no capturas. Las reglas entre campos siguientes son obligatorias y se comprueban además con el modelo de pruebas:

- `schema=smartspace.ld2450.frame`, `version=1`, `device=smartspace-esp32`.
- `slots` siempre tiene los slots 1, 2 y 3 en ese orden, cada uno con `x_mm`, `y_mm`, `speed_mm_s`, `resolution_mm`. Son enteros locales del radar o los cuatro valores null. No hay rotación, traducción, identificación persistente ni suavizado.
- `targets` contiene exclusivamente los números de slot presentes. Es una extensión explícita al ejemplo de Work: conserva los tres slots fijos y permite una lista vacía inequívoca. `targets: []` solo se genera por un callback válido cuyos tres slots estén ausentes según el componente. No significa confirmación física de habitación vacía.
- Cuatro NaN del mismo slot representan el desconocido/ausente producido por el componente para distancia cero. Si hay una mezcla parcial, infinito, fracción, fuera de rango o posición (0,0) finita inesperada, se descarta **todo el informe**, aumenta invalid_reports y no se inventa una lista vacía. NaN e infinitos nunca se serializan. Las cotas reflejan los int16 actuales del componente, incluida resolución: no prometen preservar anomalías de bytes que el parser convierta o desborde.
- `boot_id` es UUID aleatorio v4 generado localmente al primer callback; cambia tras reinicio. `seq` uint64 empieza en 1 y avanza por cada callback, también repetido, vacío, inválido, desconectado o no seleccionado. Antes de desbordar se abre otra sesión lógica con boot_id nuevo y contadores reiniciados. UUID aleatorio no implica unicidad matemática absoluta.
- `rx_us` usa `esp_timer_get_time()` de 64 bits desde arranque, tomado al entrar al publicador tras la copia. `time_reference=esp_processing_monotonic`: NO es UTC, primer byte UART ni tiempo físico de medida. No sufre el wrap de micros()/millis() de 32 bits; si el reloj retrocede se abre sesión nueva. El límite firmado de ESP timer es remoto (~292000 años). Los consumidores deben conservar enteros de 64 bits, sin redondearlos a Number de JavaScript cuando excedan 2^53.
- `selected_seq` cuenta intentos seleccionados, incluidos fallos de encolado. `min_interval_us` declara el perfil. `diagnostics` contiene invalid_reports, offline_reports, decimated_reports, enqueue_failures y previous_callback_max_us. Diagnósticos de envío reflejan intentos anteriores; no son ACK de entrega. La duración medida empieza después de la copia, incluye selección/serialización/encolado de informes seleccionados y no todo el parser.

El caso de velocidad cero conserva 0. El slot completamente desconocido usa null; una velocidad desconocida aislada hace que el informe parcial se rechace, conforme al contrato de Work, sin sustituirla por cero.

## Frecuencia, silencio y carga

`frame_min_interval_us: "0"` publica cada callback, incluidos informes idénticos. El objetivo nominal es 10 Hz si UART entrega 10 Hz; no hay generador de diez informes artificiales por segundo. Valores `200000` y `1000000` limitan a como máximo 5 y 1 Hz. Se elige el primer informe nuevo elegible tras el intervalo, no se acumulan datos para temporizadores. Con jitter, un límite temporal de 100000 us no garantiza diez publicaciones/s; por eso la adquisición nativa usa 0.

Sin on_data no se incrementa seq ni se publica, aunque continúe el heartbeat antiguo. Los filtros/timeout de sensores individuales no activan on_data. Desconectado se descartan informes nuevos sin serializar ni mantener una cola propia, y el siguiente callback conectado puede seleccionarse inmediatamente tras haber observado la desconexión.

`idf_send_async: true` usa la cola acotada del backend MQTT IDF instalado, compartida con los topics anteriores. Este cambio afecta al envío de todas las entidades, pero no sus topics/payloads/filtros. El código local dispone de pool de 29 elementos y cola de 30; descarta al llenarse y durante desconexión. La llamada copia los datos antes de retornar. El callback no espera ACK, no usa delay ni reintenta. Serialización/asignación de memoria sí consumen CPU y no tienen garantía de tiempo real duro. True indica aceptación en cola, no entrega: fallos posteriores del worker no se reflejan en enqueue_failures. Puede existir una carrera entre desconexión y drenaje; no se promete entrega exactamente una vez ni ausencia absoluta de un mensaje ya en tránsito. Identificar datos por boot_id/seq/rx_us.

Los informes con todos los campos y diagnósticos son mayores que la estimación de 450 bytes de Work. Medir payload real, duración del callback, heap mínimo, watchdog, cola y tasa UART/MQTT. No se ha medido impacto físico ni garantizado 10 Hz en hardware. DEBUG y publicaciones antiguas continúan aportando carga. La transformación sigue reservada al backend futuro.

## Validación local y Windows

Entornos instalados: `.venv` ESPHome 2026.6.5; `.venv-p0` backend/pruebas. Se reparó únicamente `home` de `.venv/pyvenv.cfg` y del entorno `.platformio/penv/pyvenv.cfg` para apuntar al Python 3.11.9 operativo. Copias previas en la carpeta local de trabajo `work/p11c1`. PlatformIO regeneró su entorno de dependencias Python IDF 5.5.4; no se actualizó ESPHome, ESP-IDF ni el firmware del radar. El sandbox bloqueó DLL/caché; compilación y aserciones Xtensa se ejecutaron fuera de él con autorización de la herramienta.

```powershell
Set-Location 'C:\Users\danie\Desktop\smart-space-digital-twin'
.\.venv\Scripts\python.exe -m esphome version
.\.venv\Scripts\python.exe -m esphome config firmware\esp32_base.yaml
.\.venv\Scripts\python.exe -m esphome compile firmware\esp32_base.yaml
$env:SMARTSPACE_XTENSA_CXX = 'C:\Users\danie\.platformio\packages\toolchain-xtensa-esp-elf\bin\xtensa-esp32-elf-g++.exe'
$env:SMARTSPACE_REPLAY_CAPTURE = (Resolve-Path captures\ld2450-2026-11-24-01.mqtt.jsonl).Path
.\.venv-p0\Scripts\python.exe -m pytest -q
node --test tests/frontend.test.mjs
$env:SMARTSPACE_TEST_MOSQUITTO = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto\mosquitto.exe'
.\.venv-p0\Scripts\python.exe -m pytest -q -m mqtt
```

Las aserciones constexpr del archivo C++ se evalúan con el compilador Xtensa sobre **la política realmente incluida en firmware**, sin ejecutar ESP32. Cubren cero/uno/dos/tres, 1+3, X=0 válido, NaN/parcial/infinito/fracción, repetidos, silencio sin llamadas, selección, desconexión/reconexión, reinicio y paso de 2^32. Los ejemplos JSON se validan con Pydantic existente, sin dependencias nuevas de aplicación. No se ejecuta el parser UART ni el publicador IDF en hardware; compilación e inspección no equivalen a un ensayo físico.

## Carga y reversión — instrucciones futuras, NO ejecutadas

No cargar directamente el binario base en la red habitual: conserva el broker anterior. Tras revisar los resultados y autorizar P1.1c.2, usar una LAN de banco sin ruta a producción. Ejemplo concreto: PC/broker `192.168.50.1`, SSID dedicado `SmartSpaceBench`, puerto USB identificado como COM5 (confirmar el puerto real). No cambiar UART, radar ni modo.

1. Antes de flashear, guardar de forma privada el binario previo conocido y hash. Si no existe, leer la flash completa original **solo con autorización de hardware**, sin borrar. El build anterior no acredita cuál está instalado. La configuración previa exacta se conservó localmente en `work/p11c1/esp32_base.before.yaml`; el backup antiguo del repositorio no se presume equivalente.
2. Crear, únicamente en esa fase, `firmware/esp32_bench.yaml` como paquete de prueba:

```yaml
packages:
  base: !include esp32_base.yaml
wifi:
  ssid: !secret bench_wifi_ssid
  password: !secret bench_wifi_password
mqtt:
  broker: 192.168.50.1
```

Añadir credenciales de banco a secrets.yaml local no versionado. El fichero bench también debe permanecer local. Compilarlo y guardar binarios/hash antes de cargar; no usar el binario base con dirección de producción.

```powershell
# SOLO tras aprobación futura; COM5 debe ser el puerto identificado.
.\.venv\Scripts\python.exe -m esptool --chip esp32 --port COM5 read-flash 0 ALL "$env:USERPROFILE\Desktop\smartspace-before.bin"
Get-FileHash "$env:USERPROFILE\Desktop\smartspace-before.bin" -Algorithm SHA256
.\.venv\Scripts\python.exe -m esphome config firmware\esp32_bench.yaml
.\.venv\Scripts\python.exe -m esphome compile firmware\esp32_bench.yaml
.\.venv\Scripts\python.exe -m esphome upload firmware\esp32_bench.yaml --device COM5
```

Si `.venv` no contiene esptool, usar el esptool de PlatformIO con su entorno penv: `& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" -m esptool ...`. No instalar/actualizar herramientas silenciosamente. El procedimiento es USB; no OTA ni Raspberry.

Reversión completa, con flash de respaldo verificada, sin erase-flash previo:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\python.exe" -m esptool --chip esp32 --port COM5 write-flash 0x0 "$env:USERPROFILE\Desktop\smartspace-before.bin"
```

Solo válido para backup completo del mismo ESP32 y condiciones compatibles de cifrado/secure boot; si están habilitados, detenerse y usar el procedimiento específico del dispositivo. Mantener la red de producción inaccesible al probar la reversión, pues restaura sus credenciales/broker. Un firmware recompilado de YAML anterior no es una copia exacta de flash/NVS ni garantiza restaurar el estado del radar.

## P1.1c.2 preparada, no ejecutada

Broker de banco independiente en PC 192.168.50.1, sin puente a producción. Configuración mínima `mosquitto-bench.conf`: `listener 1883 192.168.50.1`, `allow_anonymous true`, `persistence false`; solo en esa LAN aislada. No reutilizar credenciales de producción.

```powershell
# En consolas separadas; rutas de herramientas previamente instaladas.
$tools = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto'
& "$tools\mosquitto.exe" -c .\mosquitto-bench.conf -v
& "$tools\mosquitto_sub.exe" -h 192.168.50.1 -p 1883 -t 'smartspace/esp32/radar/frame/v1' -q 0 -R -F '%I %t %p' | Out-File -Encoding utf8 .\frames-bench.log
& "$tools\mosquitto_sub.exe" -h 192.168.50.1 -p 1883 -t 'smartspace/esp32/switch/multi_target_tracking/state' -q 0 -R -v
```

El último topic debe cotejarse con el object_id generado antes del banco; no es un comando y un estado MQTT por sí solo no acredita ACK UART. El log MQTT con timestamp ISO y payload no es formato P0.2: **no se entrega al reproductor existente**. No se modifica el grabador ni su allowlist. Verificar instalación de mosquitto_sub antes de empezar.

Captura UART pasiva simultánea: analizador lógico con dos canales, RX del ESP/TX del radar y TX del ESP/RX del radar, GND común, entradas de alta impedancia y niveles compatibles. Un adaptador USB-UART alternativo solo RX+GND sobre TX del radar, TX desconectado; no permite observar consultas ESP→radar sin segundo canal. No conectar dos transmisores. Muestrear suficientemente por encima de 256000 baudios, decodificar 8N1, exportar bytes/timestamps originales y conservarlos sin normalizar. Usar longitud exacta 30, cabecera AA FF 03 00 y footer 55 CC; separar ACK FD FC FB FA. No escribir parser nuevo en esta fase.

Confirmación de multiobjetivo: capturar bidireccionalmente el arranque autorizado del ESP. El componente existente `read_all_info()` entra en configuración, consulta versión/MAC/modo/zonas y sale; no se añade ninguna orden de cambio. Identificar consulta `FD FC FB FA 02 00 91 00 04 03 02 01` y su ACK correspondiente, respuesta 0x0091 con bit de respuesta (0x0191), estado de éxito 0x0000 y modo 0x0002, según protocolo Work. Guardar bytes completos, comparar longitudes/endian con protocolo. El código local usa byte 10 para publicar el switch; no sustituye comprobar éxito/longitud del ACK. Si no se observa consulta-respuesta, marcar modo no confirmado; no enviar ON, comandos 0x0090/0x0080, restauración de fábrica ni cambiar baudios/zonas. Repetir lectura tras reinicio autorizado; no usar el segundo adaptador como transmisor.

Plan físico:

| Escena | Evidencia y criterio |
|---|---|
| Vacío, 1, 2 y 3 personas | Tres repeticiones de 60 s; registrar posiciones/separación/movimiento y etiquetas temporales; conservar slots tal como vienen. No equiparar slots a identidades. |
| Entradas/salidas, cruce, oclusión y quietud | Comparar conteo UART, campos JSON y duración de pérdidas; cambiar un factor cada vez. |
| Cadencia nativa | Contar UART válida, callbacks inferidos por seq, seleccionadas por selected_seq y recibidas. Medir intervalos p50/p95/p99 y huecos; objetivo nominal 10 Hz pendiente de medición. |
| Coherencia | Alinear UART/JSON por orden y contenido; incluir repetidos, vacíos y slots 1+3. No fingir alineación unívoca de tramas idénticas ni comparar relojes sin sincronización. |
| Silencio UART frente a vacío | Vacío produce informes con targets []; cortar recepción autorizado debe producir silencio del topic de frames, no listas vacías periódicas. Heartbeat puede continuar. |
| Red/cola/reinicio | Registrar huecos, diagnostics, boot_id nuevo, secuencias y posibles mensajes en tránsito. Comparar encolado con recepción; QoS0 admite pérdidas. |
| Estabilidad | 30 min por perfil, luego 2 h elegido; medir heap mínimo, reinicios/watchdog, duración del callback, avisos de cola y Max command length exceeded; no atribuir causa sin UART simultánea. |

No se ha realizado ninguna de estas actuaciones sobre hardware. El nuevo topic todavía no alimenta el gemelo digital: integración y salud posteriores están fuera de P1.1c.1.


## Resultados de aceptación de P1.1c.1

- YAML validado con ESPHome 2026.6.5.
- Compilación completa SUCCESS (108,63 s), ESP-IDF 5.5.4 / plataforma 55.03.39 / Xtensa GCC 14.2.0+20260121; sin actualizar ESPHome ni ESP-IDF. RAM estática 50.880/327.680 bytes (15,5 %), flash 838.915/1.835.008 (45,7 %). Estas cifras no miden heap mínimo en ejecución.
- Código generado inspeccionado: un registro add_on_data_callback, doce lecturas crudas en la lambda ejecutable, tres resoluciones asociadas a índices originales y USE_MQTT_IDF_ENQUEUE activo. Los fuentes LD2450, deduplicador y sensor copiados al build coinciden byte a byte con los instalados. LD2450 SHA256 `b64ff271275f434420b43add799f633906b76a0252aa858fa9f51665acf3fa84`, igual al informe Work.
- 157 pruebas Python locales correctas, incluidas 11 nuevas y compilación de aserciones C++; 7 MQTT aisladas correctas; 5 JavaScript correctas. Permanece el aviso previo de Starlette/TestClient sobre httpx. Sin SMARTSPACE_XTENSA_CXX se omite únicamente la prueba opcional de compilador; sin captura local se omite su caso físico.
- `git diff --check` correcto; avisos CRLF de archivos previos no cambiados aquí. Hashes de backend, frontend, grabador/reproductor, capturas y fixtures existentes idénticos al inicio de este incremento.
- Firmware generado localmente: `firmware/.esphome/build/smartspace-esp32/.pioenvs/smartspace-esp32/firmware.bin`, 839.312 bytes, SHA256 `3cfdacc46fd82f3c72c543237d19f9fb58b6e3b35ee8830763e77efe5bddb5bd`. Factory: 904.848 bytes, SHA256 `7bf223241417f3ea0df767628f1e1d378d65c3d2314d553b03571341eaf94e2e`. Son artefactos locales ignorados, pueden contener configuración privada y no se versionan. El binario base conserva el broker original: no cargarlo en producción ni confundirlo con la futura variante de banco.

Archivos del incremento: esp32_base.yaml (on_data, IDs, resoluciones internas y MQTT asíncrono), ld2450_report_core.h (política pura), ld2450_report.h (sesión/JSON/envío), tests/test_ld2450_report_core.cpp y tests/test_ld2450_report.py, dos contratos JSON en docs/contracts, esta guía, cierre en normalization-p11b.md y enlace README. Los cambios previos del árbol Git se conservan.

P1.1c.1 queda implementado y validado por compilación y pruebas sin hardware. Pendientes: ejecutar y cotejar JSON real/UART pasiva, confirmar modos por ACK, medir memoria/carga/latencia y entrega, evaluar parser ante delimitadores anómalos y detección física multiobjetivo. El contrato no archiva bytes crudos ni garantiza ausencia física. Las pruebas C++ evalúan la política en compilación; la serialización ArduinoJson queda compilada e inspeccionada, pero todavía no capturada en ejecución real. No se implementa ni ejecuta P1.1c.2, P1.1c.3, P1.1c.4 o P1.2.
