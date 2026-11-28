# P1.1c.3 — Captura, importación y replay de informes completos

Estado: implementación de herramientas sin cambios de firmware, backend o frontend. [Validación física parcial P1.1c.2](physical-validation-p11c2.md). No implementa la recepción del nuevo topic en FastAPI/SVG (P1.1c.4), ni P1.2.

## Compatibilidad y grabación

El grabador P0.2 conserva su envolvente `smartspace.mqtt.capture`, schema_version 1: bytes Base64, UTC y monotónico de recepción, flags MQTT, secuencia del grabador y eventos de conexión. Se amplía la allowlist explícita, no se usa una suscripción de comandos. `TELEMETRY_TOPICS` continúa siendo los diez topics antiguos para no cambiar consumidores previos; `ALL_TELEMETRY_TOPICS` añade solo `smartspace/esp32/radar/frame/v1`.

`record --topics legacy` (por defecto) conserva la selección anterior. `--topics frames` selecciona únicamente informes; `--topics both` suscribe simultáneamente los once. Metadata.topics declara la selección y SUBACK se valida contra su tamaño. El loader acepta esos tres conjuntos; los archivos antiguos y eventos siguen siendo válidos. Los payloads de informes se validan sin reemplazarlos: bytes inválidos se guardan con diagnóstico. Un rechazo de contrato no es un error de E/S ni provoca pérdida voluntaria de evidencia. Los fallos de red/disco/cierre siguen las reglas P0.2.

El nuevo validador stdlib no importa FastAPI ni Pydantic ni añade dependencias. Verifica versión/tipos estrictos (bool no es entero), UUID canónico, rangos, tres slots ordenados, grupo completo de enteros o cuatro null, ausencia de NaN/inf, referencias targets y diagnósticos. Rechaza claves JSON duplicadas. Conserva velocidad cero y valores desconocidos según el contrato de P1.1c.1.

Analyzer registra saltos/regresiones de seq, duplicados idénticos o conflictivos, cambio/retorno de boot_id, reloj decreciente/igual, regresión de selected_seq/diagnósticos e intervalos ESP >500000 us. La clasificación usa contenido JSON para duplicados, pero nunca reserializa el payload publicado. Un boot_id nuevo indica sesión nueva, no prueba exclusivamente un reinicio físico (también existe rotación lógica). Un salto de seq NO demuestra pérdida MQTT: puede haber invalidación, desconexión, selección o pérdidas posteriores. Consultar selected_seq y contadores; no asignar causalidad sin evidencia. Retenidos se validan, pero no inicializan continuidad actual.

## Importación de mosquitto_sub

Formato derivado distinto: `smartspace.mqtt.payload_import`, versión 1. Contiene encabezado de procedencia, SHA256 del archivo original, clasificación de evidencia, cada línea original en Base64 con terminador/BOM y cierre de la **importación**, no de la captura física. Loader verifica orden, Base64 canónico, hash y cierre antes de reproducir. Se puede reconstruir exactamente el archivo original concatenando las líneas decodificadas. Nunca sobrescribe un archivo.

Se exige un payload JSON por línea, UTF-8 (con o sin BOM inicial); no se acepta UTF-16 ni se inventan conversiones. Se separa únicamente el terminador añadido por la salida por líneas y, si existe, el BOM inicial. Los espacios y bytes restantes del payload se conservan. No se afirma recuperar información que mosquitto_sub/PowerShell no guardó (por ejemplo un salto de línea que perteneciera al payload original). Este importador no sirve para logs `-v`, `-F` con prefijos ni JSON con múltiples líneas.

Topic declarado por el importador: frame/v1; no se presenta como topic observado en el archivo. Recepción UTC, monotónico MQTT, QoS, retain, dup, mid y conexión son **null/desconocidos**. Un identificador derivado del hash distingue la importación, sin suplantar boot_id ni una sesión MQTT real. `source_completeness=unknown`: aun con JSON final válido no se conoce el cierre físico ni la duración de captura exacta. `source_incomplete=false` en el resumen solo indica que el archivo derivado tiene estructura/cierre válidos; no anula esta limitación.

Temporización derivada: primer informe válido a offset 0; dentro de una sesión se conservan diferencias no negativas de rx_us. No se transforma rx_us en UTC ni en recepción. Cambio de boot_id o retroceso del reloj conserva el orden y colapsa la separación desconocida a cero, etiquetada `collapsed_unknown_boundary`. Una línea inválida se archiva, se sitúa en el último offset conocido con `unknown_invalid_report` y se omite de publicación por defecto. Los offsets son un convenio de replay explícito, no tiempos reconstruidos. Tras un inválido, el siguiente informe válido conserva el intervalo desde el anterior válido. No se añaden conexión/desconexión o informes vacíos imaginarios.

## Replay y análisis

El mismo `mqtt_capture.replay` carga capturas P0.2 o importaciones. Las primeras usan sus tiempos de recepción; las segundas `esp_processing_derived`. Reloj inyectable, velocidades y orden de empates siguen P0.3. Eventos de conexión del grabador conservan su alcance recorder_to_broker; no prueban desconexión del ESP32.

- Retain=True: omitido siempre.
- Retain desconocido de importados: omitido por defecto; `--allow-unknown-retain` permite publicarlo explícitamente en el broker de pruebas.
- Informe inválido: omitido por defecto, preservado en evidencia y eventos. `--include-invalid-frames` permite reproducir sus bytes para diagnósticos aislados; en importados requiere también el permiso anterior.
- Publicación siempre QoS1 y retain=False, como P0.3; QoS original permanece separado, null si no existe. Ni el QoS1 del replay ni su flag retain prueban cómo se recibió el original.
- Broker temporal propio en loopback, ACL solo para los once topics. Sin parámetro de broker externo ni comandos.

El resumen añade validación/continuidad y omisiones. `source_sha256` identifica el archivo entregado al reproductor; `original_sha256` identifica el original mosquitto_sub cuando es importado. `normalized_sha256` incluye eventos, bytes Base64, identidad/orden, metadatos originales disponibles, validación y offsets escalados por velocidad; dos ejecuciones con iguales opciones generan los mismos eventos. Cambiar velocidad cambia el hash temporal; no implica cambiar los bytes. El hash no depende de si se publica o se hace dry-run.

`analyze_frames` informa sesiones, contadores, rangos de diagnósticos, tasa `(N−1)/span` y mayor tramo de igual número de slots, cortando al detectar salto/regresión o intervalo ESP >500 ms. Interpretar tasas de sesión solo si no hay anomalías de orden/reloj; no son precisión de detección ni tiempo de ocupación física. El umbral 500 ms es un indicador de huecos configurable en Analyzer, no una política de TTL ni de ocupación.

## Comandos Windows

Desde la raíz. No se han ejecutado capturas contra producción. Para grabación futura, sustituir el host de ejemplo únicamente por un broker de banco autorizado:

```powershell
Set-Location 'C:\Users\danie\Desktop\smart-space-digital-twin'
$py = '.\.venv-p0\Scripts\python.exe'
# Captura de banco; el archivo debe ser nuevo. Ctrl+C cierra ordenadamente.
& $py -m mqtt_capture.record --broker 192.168.50.1 --port 1883 --duration 60 --topics frames --output .\captures\frames-session-01.mqtt.jsonl
# Para diagnóstico simultáneo, usar --topics both; legacy mantiene P0.2.
```

Importar sin modificar originales (cada salida debe ser nueva):

```powershell
$derivados = Join-Path $env:TEMP ('smartspace-p11c3-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $derivados | Out-Null
$names = 'ld2450-frequency-v1', 'ld2450-two-persons-v1', 'ld2450-controlled-test-v1'
foreach ($name in $names) {
    & $py -m mqtt_capture.import_frames --input ".\captures\$name.jsonl" --output "$derivados\$name.import.jsonl" --evidence-kind physical_capture
}
$inputFile = Join-Path $derivados 'ld2450-controlled-test-v1.import.jsonl'
& $py -m mqtt_capture.analyze_frames --input $inputFile
& $py -m mqtt_capture.replay --input $inputFile --dry-run --virtual-clock --allow-unknown-retain --events-output "$derivados\virtual-a.jsonl"
& $py -m mqtt_capture.replay --input $inputFile --dry-run --virtual-clock --allow-unknown-retain --events-output "$derivados\virtual-b.jsonl"
(Get-FileHash "$derivados\virtual-a.jsonl").Hash -eq (Get-FileHash "$derivados\virtual-b.jsonl").Hash

$mosquitto = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto\mosquitto.exe'
& $py -m mqtt_capture.replay --input $inputFile --mosquitto $mosquitto --speed 1 --allow-unknown-retain
```

El último comando conserva intervalos del ESP, no recepción MQTT inexistente. No usar replay_app/normalize para afirmar que el backend ya entiende frame/v1: su adaptación pertenece a P1.1c.4. Para las capturas nuevas del grabador no hace falta `--allow-unknown-retain`, pues sí se conoce ese flag.

Pruebas:

```powershell
$env:SMARTSPACE_REPLAY_CAPTURE = (Resolve-Path captures\ld2450-2026-11-24-01.mqtt.jsonl).Path
$env:SMARTSPACE_XTENSA_CXX = 'C:\Users\danie\.platformio\packages\toolchain-xtensa-esp-elf\bin\xtensa-esp32-elf-g++.exe'
& $py -m pytest -q
node --test tests/frontend.test.mjs
$env:SMARTSPACE_TEST_MOSQUITTO = $mosquitto
& $py -m pytest -q -m mqtt
```

El compilador solo se utiliza para las aserciones existentes de P1.1c.1: no recompila ni modifica el firmware. Sin esa variable se omite la prueba opcional; sin captura local se omite su prueba real. Las fixtures nuevas se identifican como sintéticas y no se mezclan con evidencia física.

## Resultados y límites

Se importaron sin cambios y validaron 2529 informes reales: 675 + 674 + 1180. Dos ejecuciones virtuales de cada captura produjeron eventos y hashes idénticos. Reproducción adicional con reloj virtual y **broker real aislado**: 2529 publicados y recibidos, comparación exacta topic/bytes/orden/QoS1/retain=False; un suscriptor posterior no recibió mensajes retenidos. Esto prueba transporte, no planificación a velocidad real ni latencia física.

| Original | SHA256 de eventos normalizados (1x) |
|---|---|
| frequency | d5fc69dc85457d6d82a7099ee649e4ed8ae768814768038d67ce3508e8492103 |
| two-persons | af2bdc2b49953b2bb3c1b5c9627408c37f9d222ac64fad85cfa7323e1ccfc3b7 |
| controlled-test | ad8d0e64893d9caa8bf43ffd3c1ec7140cf186d1de77886cb14c2b92520d8990 |

Regresión local: 182 pruebas correctas; MQTT aislado: 10 correctas, incluida grabación simultánea de informes y topic antiguo; JavaScript: 5 correctas. Una primera ejecución local falló al cerrar el WebSocket en `test_disabled_simulation` con CancelledError; la repetición completa pasó sin cambios en backend ni en esa prueba. Se registra como comportamiento intermitente pendiente, sin ocultarlo ni corregirlo fuera de alcance. Permanece el aviso previo de Starlette/TestClient sobre httpx.

Los lectores/replay cargan archivos completos y el analizador conserva un índice de secuencias; uso de memoria crece con la duración. No se certifican sesiones ilimitadas. La importación conserva incluso líneas inválidas, no sana archivos ni inventa tiempos. Un archivo vacío/UTF-16 o un derivado truncado/hash incorrecto se rechaza. No se puede demostrar completitud de las capturas directas, medir su latencia MQTT ni reconstruir pausas entre reinicios. Los cambios de sesión no certifican reinicio físico. Un hueco no implica habitación vacía.

Archivos: nuevos frames.py, import_frames.py, analyze_frames.py; cambios acotados en record.py, replay.py e isolated_broker.py; dos módulos de pruebas y una fixture sintética nueva; esta guía, informe parcial P1.1c.2 y enlaces README. No se han alterado firmware, lógica backend/frontend, originales ni fixtures anteriores. Fin de P1.1c.3; no se implementan P1.1c.4 ni P1.2.
