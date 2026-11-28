# P1.2a — Motor de diagnóstico de adquisición

## Alcance y evidencia previa

Implementación independiente de diagnóstico, sin cambiar aceptación de informes, coordenadas, firmware ni frontend. No implementa P1.2b, P1.3 o P2. Reutiliza P1.1c.4 y mantiene `/health` compatible.

El usuario comunica una validación manual adicional en modo directo frames: movimiento más fluido, buena latencia percibida y mayor estabilidad. Son observaciones cualitativas, no mediciones de latencia extremo a extremo. Desviación lateral pendiente de calibración **P2**. Textos y controles del simulador visibles con radar real: incidencia pendiente de **P1.3**, sin cambios de interfaz en este incremento. Precisión física multiobjetivo y comparación UART independiente siguen abiertas.

## Arquitectura

`AcquisitionDiagnostics` recibe el resultado de `FrameAcquisition.ingest` o `RadarNormalizer.ingest` a través del consumidor. Lee contadores e informe ya aceptado, sin repetir validación JSON ni reglas de secuencia. No cambia decisiones de adquisición. Usa el mismo RLock de la instancia: orden de acceso coherente entre MQTT y asyncio. StateHub suelta su bloqueo antes de notificar al diagnóstico, evitando inversión de bloqueos.

Recepción actualiza únicamente métricas acotadas en memoria. `StateHub.broadcast` cuenta un ciclo de distribución, independiente del número de suscriptores. El puente toma snapshots periódicos (10 Hz en frames por defecto, 1 Hz legacy). Las consultas también recalculan el diagnóstico; las ventanas y la frescura evolucionan sin recibir nuevos informes. No se crean tareas de diagnóstico, colas ni escrituras persistentes por informe. El helper offline conserva su resumen por separado, no altera originales.

Reloj `clock` monotónico inyectable en segundos. Debe compartir referencia temporal con el normalizador inyectado. El motor es determinista dados los mismos eventos **y calendario de consultas/muestreo**; el histórico refleja las muestras realizadas, no una reconstrucción de instantes no observados. En producción usa el monotónico del backend; no depende de cambios del reloj UTC.

## Contrato HTTP y separación de estados

`GET /api/diagnostics` devuelve JSON versionado, con `schema_version: 1`, `service` y `acquisition`. Contrato formal: [acquisition-diagnostics-v1.schema.json](contracts/acquisition-diagnostics-v1.schema.json). Ejemplos completos y explícitamente sintéticos: [acquisition-diagnostics-v1.examples.json](contracts/acquisition-diagnostics-v1.examples.json). No requiere nuevas dependencias ni se ejecuta un validador JSON Schema por cada informe.

`service.status` refleja productor terminado, hilo MQTT ausente/muerto o excepciones inesperadas del callback. La conectividad y la calidad de datos se presentan aparte. `service.health_http_status` conserva la decisión del endpoint anterior: `/health` responde 503 ante desconexión del consumidor o fallo de hilo/productor/callback, y 200 ante silencio o un payload inválido aislado si el servicio sigue operativo. Su cuerpo anterior (`status`, `simulation_enabled`) no cambia. Por ello servicio `ok` con MQTT desconectado y health 503 es una combinación intencionada. Este endpoint diagnóstico responde 200 aunque describa degradación: debe inspeccionarse su JSON.

Dimensiones independientes:

| Dimensión | Estados / significado |
|---|---|
| MQTT | `connected` del consumidor backend, no del ESP32; `device_connectivity=not_observable` |
| Frescura | `waiting`, `fresh`, `stale`, `disconnected`; frames reutiliza exactamente el estado del normalizador |
| Integridad | `unknown` sin muestras en histórico, `clear` sin unidades de incidencia recientes, `issues` al superar umbral |
| Frecuencia | `observing`, `normal`, `degraded`, `unavailable` en legacy o `unreliable` si se truncó la ventana |
| Servicio | `ok` o `error`, separado de la ocupación y frescura |

Prioridad de `overall`: desconectado → stale → inicializando/sin informe → integridad problemática → diagnóstico limitado por capacidad → frecuencia degradada → observando → normal. `reasons` enumera también problemas secundarios. Un contador de integridad acumulado no mantiene una alarma para siempre: el estado usa la ventana reciente, los acumulados permanecen disponibles. No se infiere causalidad física de un salto de secuencia.

`current_targets` es el número de slots actuales únicamente con telemetría vigente. En frames, un informe válido vacío produce **0 y no alarma de comunicación**. Silencio, espera o desconexión producen **null**, con `occupancy=unknown`. Legacy muestra slots con coordenadas vigentes; si no hay ninguno, devuelve null porque los campos independientes no permiten confirmar un informe completo vacío. No implica identidades de personas.

## Campos, unidades y relojes

| Campo de acquisition | Significado |
|---|---|
| `mode`, `source` | frames/legacy y live/replay; simulador usa rama unavailable con source simulation |
| `time_basis`, `sampled_monotonic_s` | Referencia temporal y momento de cálculo en segundos; monotónico de backend o virtual explícito |
| `freshness.last_received_age_s` | Edad del último mensaje observado por el consumidor, incluso rechazado |
| `freshness.last_valid_age_s` | Edad del último informe aceptado; en legacy último payload numérico aceptado, no necesariamente posición completa |
| `integrity.counters` | Contadores originales: recibidos, aceptados cuando existen, inválidos, retenidos, duplicados, conflictos, orden, regresiones, huecos, boot_id y topics inesperados |
| `accepted_messages` | Aceptaciones desde creación del motor; frames cuenta informes, legacy cuenta campos/mensajes |
| `frequency.received_hz`, `accepted_hz` | Eventos en `(ahora−ventana, ahora]` divididos por min(ventana, tiempo desde creación), en Hz |
| `frequency.esp_processing_hz` | Inverso del intervalo medio rx_us entre informes aceptados consecutivos dentro de cada boot; no UART independiente ni frecuencia física certificada |
| `frequency.ws_observed_hz` | Ciclos de distribución StateHub por segundo, aunque no haya suscriptores; no confirmación de entrega ni tasa de renderizado del navegador |
| `frequency.ws_configured_hz` | Configuración del puente (10 Hz frames por defecto; 1 Hz legacy) |
| `interval_mean_s`, `interval_stddev_s` | Media y desviación poblacional de intervalos entre recepciones dentro de ventana reciente |
| `interval_p95_s` | Percentil nearest-rank, solo con al menos 20 intervalos por defecto |
| `session` | Últimos boot_id, seq y rx_us aceptados; null si no observables |
| `esp32` | Últimos valores originales, referencia inicial del boot, incrementos observados y regresiones de contadores |
| `history` | Muestras resumidas, como máximo una por segundo, recortadas a la ventana histórica |
| `memory` | Ocupación de buffers, capacidad y si el histórico conservado está completo |

Una ventana observada sin eventos tiene frecuencia **0**. Edad sin ningún evento, intervalo sin suficientes muestras, tasa sin duración positiva y datos no observables son **null**. Sin intervalos ESP no hay tasa ESP: null, no cero físico. Durante silencio corto pueden quedar intervalos históricos en la ventana; deben leerse junto con la frescura, no como prueba de actividad actual.

Las tasas de recepción y distribución usan el reloj del backend. rx_us es procesamiento monotónico del ESP32, conservado por boot_id. No se resta rx_us de un timestamp del backend; **no se ofrece latencia física extremo a extremo**. La tasa ESP solo describe separación entre informes aceptados, no informes descartados antes de recepción.

En replay, `source=replay`, `mqtt.scope=replay_consumer_to_isolated_broker` y `source_time_reference=recorded_esp_processing`. La conexión actual pertenece al ensayo aislado; los contadores ESP son contenido histórico reproducido, no salud actual del dispositivo. Los eventos históricos de conexión de la captura no cambian conexión actual ni demuestran desconexión del ESP32. Al acelerar replay, la tasa MQTT actual se acelera; la tasa de rx_us mantiene su escala original. El helper virtual declara `virtual_backend_monotonic` y simula ciclos de distribución a 10 Hz; no mide una conexión MQTT o WebSocket física.

## Contadores de origen

El primer informe aceptado de cada boot establece la referencia de `invalid_reports`, `offline_reports`, `decimated_reports`, `enqueue_failures` y el máximo de callback. Acumulado offline=63 constante significa **incremento observado cero**. No se interpreta como 63 fallos nuevos.

En el mismo boot, diferencias no negativas de los cuatro contadores se suman en `observed_increments`. Una disminución incrementa `counter_resets`, establece el nuevo valor como referencia de comparación y no suma el valor reiniciado como si fueran fallos nuevos. El incremento total conserva los incrementos conocidos antes y después del reinicio; no reconstruye eventos desconocidos. `counter_resets` cuenta campos que regresan, no número probado de reinicios físicos.

Un boot_id nuevo reinicia la referencia, incrementos y regresiones de origen de la sesión actual. Los contadores de adquisición acumulados y la ventana reciente de integridad conservan su historia; no se ocultan incidencias recientes del boot anterior. `previous_callback_max_us` es un máximo histórico en microsegundos, no un contador, percentil ni duración del último callback; se expone sin sumarlo ni interpretarlo como incremento de errores.

## Umbrales provisionales y memoria

Valores de ingeniería configurables, **no especificaciones certificadas del radar**:

- Ventana reciente 10 s; histórico 60 s.
- Calentamiento 10 s desde primer informe válido, reconexión/primera aceptación posterior o nuevo boot. Evita etiquetar baja frecuencia por pocas muestras iniciales; integridad y desconexión se siguen señalando inmediatamente.
- Frecuencia de aceptación mínima frames 8 Hz: margen conservador respecto de ~11,25 Hz observado. No aplicar este umbral a campos legacy, cuyos sensores tienen cadencias distintas.
- Integridad: al menos 1 unidad de incidencia en 10 s. Un rechazo distinto de topic inesperado cuenta 1; secuencias ausentes cuentan su cantidad; incrementos de invalid/offline/enqueue de origen y regresiones de contadores cuentan unidades adicionales. No es una tasa de fallos físicos ni un conteo de incidentes causalmente independientes. Decimación se expone, pero por sí sola no alarma: puede ser una política intencionada del firmware.
- TTL heredado del normalizador, 2 s por defecto. Edad exactamente igual a TTL sigue vigente; se caduca al superarlo. El muestreo periódico agrega retraso del planificador.
- Dos deques con máximo 8192 elementos (eventos y distribuciones); histórico máximo min(capacidad, ceil(ventana histórica)+1). Poda por edad y por capacidad. El diagnóstico no conserva payloads ni un historial ilimitado de boot_ids.
- Si se excede capacidad, se marca `window_complete=false`, tasa `unreliable` y motivo explícito. Las tasas de conteo disponibles pueden ser inferiores a las reales; no deben usarse como estimación completa hasta que expire el tramo perdido. A 11,25 Hz hay unas 675 muestras en 60 s; a 99 Hz unas 5940, por debajo del límite.

La memoria del **motor** está acotada. El conjunto de boot_ids retirados de FrameAcquisition, anterior a P1.2a, sigue teniendo su limitación ya documentada: crece por sesiones hasta reiniciar el backend. No se cambia esa política de integridad en este incremento.

Configuración en PowerShell, antes de iniciar el lanzador aislado:

```powershell
$env:SMARTSPACE_DIAGNOSTICS_CONFIG = '{"frequency_window_s":10,"history_window_s":60,"warmup_s":10,"minimum_hz":8,"integrity_threshold":1,"minimum_intervals":20,"capacity":8192}'
```

El motor también acepta `DiagnosticPolicy(...)` en pruebas. Se rechazan ventanas incompatibles, valores no finitos/no positivos y capacidades no enteras. No hay ajuste de umbrales en caliente ni adaptación automática al speed de replay.

## Validación y resultados

Se conservan intactas las tres capturas originales. Cada una se reprodujo dos veces con reloj virtual y se comprobó igualdad completa de métricas, histórico y hash. Además, la integración MQTT aislada continúa procesando todos los informes:

| Captura | Aceptados | Estado al finalizar datos | Tras 61 s sin datos | Incrementos offline |
|---|---:|---|---|---:|
| frequency | 675 | normal | stale | 0 (acumulado 61) |
| two-persons | 674 | normal | stale | 0 (acumulado 63) |
| controlled-test | 1180 | normal | stale | 0 (acumulado 63) |
| Total | 2529 | Sin rechazos inesperados | Ocupación desconocida | 0 |

En la última ventana virtual de las tres capturas: recepción/aceptación **11,3 Hz** (113 eventos/10 s), distribución simulada **10 Hz**. Tasa ESP reciente respectivamente 11,23782; 11,23466; 11,23758 Hz. La diferencia con 11,3 proviene de contar eventos en una ventana frente a promediar intervalos; no implica pérdida. p95 de recepción virtual: 93,075 ms; 91,486 ms; 91,631 ms. Esos intervalos se derivan de rx_us en los archivos importados, no de tiempos MQTT físicos ausentes.

Microbenchmark local: tres pasadas por 1180 informes, 3540 muestras por condición, ingestión + StateHub; JSON de entrada preparado antes del intervalo. Sin observador: media 0,2926 ms, p95 0,4664 ms, p99 0,6683 ms. Con observador: media 0,3450 ms, p95 0,6454 ms, p99 0,8457 ms. Incremento medio **0,0524 ms** (~18%). Snapshot medio separado **0,6684 ms**. Son resultados de Windows bajo carga variable, no garantía de Raspberry. El benchmark reproducible puede variar. La prueba MQTT previa de margen a objetivo 100 Hz continúa pasando con diagnóstico habilitado.

Pruebas nuevas cubren inicialización tardía, 11,25 Hz, cero válido, baja frecuencia, silencio, desconexión y recuperación, duplicados/conflictos/orden/regresión, inválidos, retenidos, huecos, boot nuevo, reinicios de contadores, expiración sin datos, legacy, fuente, reloj virtual, concurrencia, memoria y compatibilidad de /health. La prueba de memoria procesa 2000 informes con capacidad 32 y dos lectores concurrentes, sin crecimiento del buffer. No se certifica seguridad frente a cualquier planificador ni un ensayo de resistencia de días.

## Comandos Windows reproducibles

Todos los comandos de red siguientes usan únicamente el broker de pruebas propio de P0.3. No arrancar el servicio directo para esta validación.

```powershell
Set-Location 'C:\Users\danie\Desktop\smart-space-digital-twin'
$python = '.\.venv-p0\Scripts\python.exe'
$mosquitto = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto\mosquitto.exe'
$run = Join-Path $PWD ('outputs\p12a-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $run | Out-Null
foreach ($name in @('frequency','two-persons','controlled-test')) {
  & $python -m mqtt_capture.import_frames --input "captures/ld2450-$name-v1.jsonl" --output "$run/$name.import.jsonl" --evidence-kind physical_capture
  & $python -m mqtt_capture.diagnose --input "$run/$name.import.jsonl"
}
& $python -m mqtt_capture.diagnose --input "$run/controlled-test.import.jsonl" --benchmark
& $python -m mqtt_capture.replay_app --input "$run/controlled-test.import.jsonl" --mosquitto $mosquitto --acquisition frames --allow-unknown-retain --speed 1 --ws-hz 10 --manual-start --http-port 8001
```

Desde otra consola PowerShell:

```powershell
Invoke-RestMethod -Method Post 'http://127.0.0.1:8001/api/replay/start'
Invoke-RestMethod 'http://127.0.0.1:8001/api/diagnostics' | ConvertTo-Json -Depth 12
Invoke-RestMethod 'http://127.0.0.1:8001/health'
```

Al terminar la captura, esperar >2 s y consultar de nuevo: adquisición stale/current_targets null, sin inferir habitación vacía; /health permanece 200 mientras consumidor y servicio siguen operativos. Ctrl+C cierra el lanzador y su broker. Para probar legacy, sustituir input por `captures/ld2450-2026-11-24-01.mqtt.jsonl` y `--acquisition legacy`; las métricas ESP/sesión serán null y no se aplicará el umbral de frecuencia frames.

```powershell
$env:SMARTSPACE_REPLAY_CAPTURE = Join-Path $PWD 'captures\ld2450-2026-11-24-01.mqtt.jsonl'
$env:SMARTSPACE_FRAME_CAPTURES = Join-Path $PWD 'captures'
$env:SMARTSPACE_TEST_MOSQUITTO = $mosquitto
& $python -m pytest -q
& $python -m pytest -m mqtt -q
& 'C:\Program Files\nodejs\node.exe' --test tests/frontend.test.mjs
# Compilación opcional existente: no modifica ni carga firmware.
$env:SMARTSPACE_XTENSA_CXX = 'C:\Users\danie\.platformio\packages\toolchain-xtensa-esp-elf\bin\xtensa-esp32-elf-g++.exe'
& $python -m pytest tests/test_ld2450_report.py::test_actual_cpp_policy -q
git diff --check
```

## Limitaciones y archivos

El diagnóstico no confirma disponibilidad del ESP32 a través del estado de conexión del consumidor. No mide exactitud de posiciones, número físico de personas, latencia extremo a extremo, salud UART independiente ni origen causal de pérdidas. Tampoco distingue dos boot_id nunca vistos mediante un orden global. No añade alertas persistentes, integración visual, monitor externo del propio proceso ni cambios de despliegue.

Archivos nuevos: `backend/app/acquisition_diagnostics.py`, `mqtt_capture/diagnose.py`, `tests/test_acquisition_diagnostics.py`, contrato y ejemplos en `docs/contracts/acquisition-diagnostics-v1.*`, este documento y `docs/progress-p12a.md`. Cambios acotados en `mqtt_consumer.py`, `radar_bridge.py`, `main.py` y `tests/test_frame_backend_integration.py`. Los cambios de incrementos anteriores que aparecen en git status no pertenecen a P1.2a.

## Resultado final y criterios de aceptación

Regresión local final: **206/206**, incluida compilación C++ existente; cero omisiones. JavaScript: **5/5**. Advertencia de deprecación Starlette/httpx ya existente, sin fallo de pruebas ni cambio de dependencias. Los 22 archivos protegidos de frontend, firmware, capturas y fixtures conservan sus hashes. `git diff --check` no detecta errores.

La última ejecución del comando `diagnose --benchmark` midió 0,2944 ms sin observador y 0,3108 ms con él (incremento medio 0,0164 ms, ~5,6%); p95 0,4756/0,5406 ms; p99 0,6664/0,7467 ms; snapshot 0,5511 ms. Se conserva también la medición anterior de +0,0524 ms para hacer visible la variabilidad. Ninguna de las dos certifica capacidad de otro equipo.

| Criterio | Evidencia |
|---|---|
| Separación conexión, telemetría e integridad | Dimensiones independientes y pruebas de API; health compatible |
| 2529 informes reales | Aceptados íntegros por replay virtual y MQTT aislado |
| Métricas con reloj virtual | Tasas, intervalos, p95, edades, ventanas y determinismo comprobados |
| Cero objetivos sin alarma | Estado normal con current_targets=0 en fixture virtual |
| Silencio sin nuevos informes | Caducidad y expiración de ventanas por consulta/muestreo |
| Sesiones y contadores | Referencia inicial, incrementos, regresiones y boot nuevo probados |
| Memoria acotada del motor | Deques con capacidad fija; prueba concurrente y señalización de truncado |
| Legacy compatible | Regresión existente y métricas no observables como null/unavailable |
| /health compatible | Mismo cuerpo/códigos; pruebas de hilo, desconexión, recuperación e inválidos |
| Umbrales y límites documentados | Reglas provisionales, separación de relojes y límites físicos explícitos |

No se conectó al broker de producción, no se desplegó ni se modificó firmware/frontend/originales. No se implementaron P1.2b, P1.3 ni P2.

Regresion MQTT final con el codigo entregado: **12/12 correctas en 62,08 s**, incluidas las capturas reales y la prueba de margen. P1.2a completado; desarrollo detenido en este incremento.
