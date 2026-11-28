# P1.1c.4 — Backend de informes completos

## Arquitectura y decisiones

Un productor y un worker. `MQTTConsumer(mode="frames")` suscribe únicamente `smartspace/esp32/radar/frame/v1`; `legacy` conserva la suscripción y normalización anteriores. No hay fallback ni mezcla. En el servicio existente, `SMARTSPACE_ACQUISITION=frames|legacy` selecciona el modo (default legacy); `SMARTSPACE_WS_HZ=10` configura la salida frames. Para validar localmente usar exclusivamente el lanzador aislado descrito abajo, nunca el servicio configurado para producción.

`FrameAcquisition` reutiliza `mqtt_capture.frames.validate`, mantiene estado por instancia y reemplaza los tres slots bajo RLock. Cada informe aceptado entra por `StateHub.publish` desde el hilo MQTT, con `notify=False`. La transformación mm → m, rotación y traslación permanece exclusivamente en backend. El bucle asyncio distribuye el último estado a los clientes, inicialmente a 10 Hz; nunca toca colas asyncio desde el hilo MQTT. Cada suscriptor tiene una cola de tamaño 1. Se conservan todos los informes aceptados en el procesamiento, pero no se promete enviar cada uno al navegador. No hay cola ni historial de informes en adquisición, ni escrituras persistentes ordinarias. `--evidence-dir` es diagnóstico explícito y opcional.

El contrato WebSocket conserva `schema_version=1`, `targets` y `observation`. Añade `resolution_mm` a los targets frames y `acquisition` con el informe original validado, `backend_received_ns`, `backend_received_utc` y `telemetry_status`. `report.rx_us` sigue siendo procesamiento monotónico ESP32, no recepción MQTT ni UTC. Coordenadas, velocidad original, resolución, boot_id, secuencias y diagnósticos permanecen en `acquisition.report`. El estado global se calcula de ese mismo informe: no combina X/Y entre informes. `association=decoded_report` describe el informe decodificado; no promete simultaneidad física de mediciones UART. Slots 1–3 no son identidades persistentes.

Frescura: TTL del informe entero de 2 s desde recepción backend (configurable con `--field-ttl` en replay). A unos 11,24 Hz equivale a aproximadamente 22 intervalos; es un margen conservador compatible con P1.1b, no una medida de latencia física. No se usa `xy-skew` en frames. La edad exactamente igual al TTL sigue vigente; se invalida al superarlo. La comprobación se distribuye en el siguiente ciclo WebSocket, con hasta un periodo adicional más retraso del planificador.

- `fresh`, informe con targets vacíos: ausencia de objetivos en ese informe; limpia inmediatamente los tres slots.
- `fresh`, slots presentes: únicamente mediciones proporcionadas. El contrato v1 exige velocidad finita para slots presentes; velocidad parcial/null invalida el informe entero. Legacy sigue representando velocidad desconocida como null, distinta de cero.
- `waiting`, `stale` o `disconnected`: cero posiciones actuales, ocupación desconocida. El informe anterior se conserva como procedencia, no como medición vigente. No equivale a habitación vacía.
- Desconexión del consumidor: invalida vigencia. Reconexión necesita un informe nuevo aceptable. Los eventos históricos de captura no desconectan el consumidor ni prueban desconexión del ESP32.

## Integridad y límites

Mismo boot_id: seq idéntica e informe igual se cuenta como duplicado; seq idéntica con contenido diferente como conflicto; seq inferior como fuera de orden. Se rechazan sin refrescar TTL. Seq mayor con rx_us decreciente se rechaza como regresión; tiempos iguales mantienen orden de seq. Saltos se aceptan y cuentan secuencias ausentes, sin inventar muestras. Un boot_id nuevo inicia otra sesión; los ya retirados se rechazan. El conjunto de boot_ids retirados crece por reinicio, no por informe; se borra al reiniciar el backend. No existe orden universal entre UUID nunca vistos: un boot_id antiguo desconocido no puede distinguirse de un reinicio legítimo. Esta limitación no se resuelve comparando relojes de dispositivos.

Inválidos y retenidos no sustituyen estado ni refrescan TTL. Los contadores de rechazo están en adquisición/runtime; el snapshot ya publicado conserva los contadores que tenía al generarse hasta el siguiente informe o transición de estado. Las excepciones inesperadas siguen contabilizadas en callback_errors y /health; un payload inválido aislado no mata el hilo ni degrada por sí solo /health. No se implementa P1.2.

El cierre WebSocket usa el grupo de tareas de AnyIO, dependencia ya presente: emisor y receptor se cancelan conjuntamente y se retira el suscriptor incluso sin estado inicial. Pasan 100 ciclos de dos conexiones simultáneas (200 conexiones) y la regresión MQTT. El fallo histórico de P1.1c.3 no se ha reproducido de manera controlada antes del cambio; la mezcla anterior de cancelación asyncio/portal AnyIO es una hipótesis, no una causa demostrada.

Frontend: solo textos de compatibilidad para informe completo, ausencia de telemetría y replay; geometría, controles y estilos sin rediseño. Los puntos exteriores siguen conservados en backend y ocultos en el plano con su indicación en tarjeta.

## Resultados medidos

Capturas reales sin modificar. Referencia virtual repetida dos veces y reproducción por broker aislado a velocidad 10:

| Captura | Informes aceptados | 1 slot | 2 slots | 3 slots | Rechazos inesperados |
|---|---:|---:|---:|---:|---:|
| frequency | 675 | 612 | 63 | 0 | 0 |
| two-persons | 674 | 535 | 139 | 0 | 0 |
| controlled-test | 1180 | 954 | 192 | 34 | 0 |
| Total | 2529 | 2101 | 394 | 34 | 0 |

Cero errores del consumidor, saltos internos, duplicados o regresiones en estas sesiones. Cada referencia virtual genera un estado por informe aceptado, con igualdad completa entre ambas ejecuciones. SHA256 de estados:

- frequency: `9c6d9c09a130ba02da75f2533cec087871ca1554af963f1657791108f200833e`
- two-persons: `a5f8ed3c8688d5b0b23d3d9f818bf926d4e28ddd04a60a0d20e463084edca8e1`
- controlled-test: `a17c31bdd398d944960fec13554ea697b9728c052067fb58fd418ceadf3093ab`

El helper virtual usa recepción virtual con época fija 2000, claramente etiquetada; NO inventa tiempos de recepción física. Las importaciones conservan las limitaciones de P1.1c.3: intervalos derivados de rx_us, retain/QoS/UTC originales desconocidos. Igualdad virtual no significa igualdad de timestamps de recepción reales entre ejecuciones MQTT.

Carga sostenida: frequency a velocidad 1 (~60 s), 675/675 aceptados, cero errores, cierre ordenado. La salida configurada 10 Hz produjo 577 ciclos de distribución incluyendo cola final; es un objetivo de cadencia, no una garantía de tiempo real de Windows. Integración adicional a 11,25 Hz y 100 Hz sin pérdidas de aceptación, hilo vivo y colas limitadas. No es una certificación de capacidad de Raspberry ni una prueba de resistencia de días.

Comparación controlada local con los mismos 1180 informes: para legacy se proyecta cada informe en diez payloads existentes, todos con el mismo tiempo virtual. Es una carga sintética derivada en memoria, NO una captura legacy ni sus publicaciones asíncronas reales. Se mide ingestión + un procesamiento StateHub por informe, sin red, serialización previa fuera del intervalo; legacy de producción continúa publicando a 1 Hz.

| Modo | Payloads | Media ms/informe | p95 ms | p99 ms | Máximo ms |
|---|---:|---:|---:|---:|---:|
| frames | 1180 | 0,1603 | 0,1756 | 0,2593 | 0,4887 |
| legacy proyectado | 11800 | 0,0505 | 0,0551 | 0,0903 | 0,3474 |

Frames valida más estructura y metadatos, por lo que este procesamiento cuesta más CPU, aunque necesita un mensaje en lugar de diez y garantiza atomicidad. No inferir una mejora universal de rendimiento ni equivalencia semántica entre modos a partir de este microbenchmark.

Pruebas: 188 locales correctas, compilación opcional omitida en esa ejecución y posteriormente ejecutada correctamente por separado (1/1); 12 MQTT correctas; 5 JavaScript correctas. Advertencia existente de Starlette sobre httpx, sin fallo ni nueva dependencia. `git diff --check` correcto. Firmware, capturas y fixtures anteriores verificados contra hashes previos.

## Windows: reproducción y validación

PowerShell desde el repositorio. El broker se crea en loopback con puerto y credenciales efímeras; el lanzador no acepta broker externo. No ejecutar el consumidor standalone apuntando a producción.

```powershell
Set-Location 'C:\Users\danie\Desktop\smart-space-digital-twin'
$python = '.\.venv-p0\Scripts\python.exe'
$mosquitto = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto\mosquitto.exe'
$run = Join-Path $PWD ('outputs\p11c4-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $run | Out-Null
foreach ($name in @('frequency','two-persons','controlled-test')) {
  & $python -m mqtt_capture.import_frames --input "captures/ld2450-$name-v1.jsonl" --output "$run/$name.import.jsonl" --evidence-kind physical_capture
  & $python -m mqtt_capture.normalize_frames --input "$run/$name.import.jsonl"
}
& $python -m mqtt_capture.normalize_frames --input "$run/controlled-test.import.jsonl" --benchmark
& $python -m mqtt_capture.import_frames --input tests/fixtures/frame_reports/display.synthetic.jsonl --output "$run/display.import.jsonl" --evidence-kind synthetic
```

Primero validar captura real. Abrir http://127.0.0.1:8001 y pulsar «Iniciar reproducción». Cerrar con Ctrl+C antes de cambiar de prueba. La aplicación mantiene el último informe como procedencia tras finalizar y elimina posiciones actuales al caducar.

```powershell
& $python -m mqtt_capture.replay_app --input "$run/controlled-test.import.jsonl" --mosquitto $mosquitto --acquisition frames --allow-unknown-retain --ws-hz 10 --manual-start --http-port 8001
```

Fixture visual **sintética**, no ensayo físico: 0→1→slots 1+3→3→0→silencio→1. Velocidad 0,5 y TTL 5 permiten observar cada fase durante cuatro segundos; el hueco de ocho segundos permite observar caducidad y recuperación. Esta configuración solo facilita inspección visual y no cambia el TTL por defecto de dos segundos.

```powershell
& $python -m mqtt_capture.replay_app --input "$run/display.import.jsonl" --mosquitto $mosquitto --acquisition frames --allow-unknown-retain --speed 0.5 --field-ttl 5 --ws-hz 10 --manual-start --http-port 8001
```

Esperado desde el primer informe: 0–4 s cero válido; 4–8 s slot 1; 8–12 s slots 1+3; 12–16 s tres; 16–21 s cero válido; ~21–24 s silencio/caducidad; 24–29 s slot 1; después silencio. La interfaz debe indicar desconocimiento de ocupación, no una habitación vacía confirmada. Las velocidades de esta fixture son numéricas porque así lo exige el contrato de informes; null desconocido sigue cubierto por legacy y sus pruebas.

Para repetir la compatibilidad legacy:

```powershell
& $python -m mqtt_capture.replay_app --input captures/ld2450-2026-11-24-01.mqtt.jsonl --mosquitto $mosquitto --acquisition legacy --manual-start --http-port 8001
```

Pruebas automáticas:

```powershell
$env:SMARTSPACE_REPLAY_CAPTURE = Join-Path $PWD 'captures\ld2450-2026-11-24-01.mqtt.jsonl'
$env:SMARTSPACE_FRAME_CAPTURES = Join-Path $PWD 'captures'
$env:SMARTSPACE_TEST_MOSQUITTO = $mosquitto
& $python -m pytest -q
& $python -m pytest -m mqtt -q
& 'C:\Program Files\nodejs\node.exe' --test tests/frontend.test.mjs
# Opcional: compilador local ya instalado; solo compila la prueba, no flashea.
$env:SMARTSPACE_XTENSA_CXX = 'C:\Users\danie\.platformio\packages\toolchain-xtensa-esp-elf\bin\xtensa-esp32-elf-g++.exe'
& $python -m pytest tests/test_ld2450_report.py::test_actual_cpp_policy -q
git diff --check
```

## Límites de alcance

La evidencia demuestra adquisición y procesamiento, no precisión física multiobjetivo, ocupación sincronizada, ausencia real ni falsos positivos. Comparación UART independiente y pérdida controlada de comunicación siguen pendientes de la validación física anterior. No se modificaron firmware ni originales, ni se accedió al broker de producción o desplegó en Raspberry. No se implementan fases posteriores.

## Verificación visual y criterios de aceptación

Se verificó el frontend real en Edge headless con perfil temporal independiente, contra FastAPI y el broker aislado. El navegador automatizado habitual no arrancó por `failed to write kernel assets`; Edge tampoco respondió dentro del sandbox, pero funcionó con permiso de ejecución local. No se añadieron dependencias.

La fixture display mostró 0, 1, slots 1+3 y 3 objetivos; regreso a cero, silencio/caducidad y recuperación. Se comprobaron tarjetas y capturas del SVG. Los slots 2 y 3 se superponen parcialmente porque las coordenadas sintéticas están separadas solo 0,10 m; se conservó esa geometría, sin inventar separación visual. Seis informes aceptados, cero errores y cierre automático ordenado. Evidencia local del chat: `work/p11c4/visual.json`, `visual-0-3.png`, `visual-1-3.png`, `visual-2-3.png`, `visual-3-3.png` y `visual-stale.png`. La imagen stale corresponde a la espera inicial; el JSON registra además la caducidad posterior y la recuperación. Las capturas físicas se validaron por MQTT/backend y referencia virtual, no mediante una inspección visual completa de todos sus informes.

La prueba de margen con un suscriptor WebSocket activo midió 11,27 Hz (57 informes, objetivo 11,25) y 99,00 Hz (100 informes, objetivo 100), sin pérdida de informes aceptados. Los tiempos dependen de Windows y la carga de la máquina.

| Criterio | Evidencia |
|---|---|
| Integración de informes completos | MQTT → adquisición → StateHub → WebSocket → SVG; fixtures 0–3 |
| 2529 informes reales sin rechazos inesperados | 675 + 674 + 1180 aceptados por MQTT y referencia virtual |
| Sin mezcla de coordenadas | Sustitución atómica bajo bloqueo y validación de targets contra el informe conservado |
| Desaparición frente a silencio | Cero válido inmediato; TTL/disconexión con occupancy unknown; prueba y navegador |
| Reproducción determinista | Igualdad completa de dos secuencias virtuales por captura, hashes documentados |
| Cadencia nativa sin colas crecientes | 675 informes a velocidad 1; margen observado 99 Hz; cola de último estado de tamaño 1 |
| Compatibilidad legacy | Pruebas anteriores y captura legacy reproducida por MQTT |
| Pruebas anteriores y nuevas | 189 locales contando compilación separada, 12 MQTT y 5 JavaScript correctas |
| Límites y fallo histórico documentados | Sin causa histórica de cierre demostrada; no reaparece en pruebas actuales; límites físicos y temporales explícitos |

## Archivos de este incremento

- `backend/app/frame_acquisition.py`: adquisición de informes completos y política de integridad/frescura.
- `backend/app/mqtt_consumer.py`: selección de modo y entrega de informes aceptados.
- `backend/app/radar_bridge.py`: procesamiento nativo y distribución WebSocket separada.
- `backend/app/main.py`: contrato ampliado, validación atómica, publicación protegida y cierre estructurado WebSocket.
- `mqtt_capture/replay_app.py`: opciones frames/legacy, cadencia, retain desconocido y evidencia opcional.
- `mqtt_capture/normalize_frames.py`: referencia virtual y microbenchmark reproducible.
- `frontend/js/app.js`: textos mínimos de compatibilidad.
- `tests/test_frame_acquisition.py`, `tests/test_frame_backend_integration.py`: pruebas nuevas.
- `tests/fixtures/frame_reports/display.synthetic.jsonl`: fixture visual nueva, explícitamente sintética.
- `docs/frame-backend-p11c4.md`, `docs/progress-p11c4.md`: decisiones, resultados, comandos y seguimiento por bloques.

El árbol ya contenía cambios de incrementos anteriores, incluidos firmware y otros archivos que aparecen en git diff; no deben atribuirse a P1.1c.4. No se ha realizado commit ni push en este incremento.
