# P1.1b — Adquisición y normalización verificables

Implementado el 26-11-2026. Este documento sustituye las expectativas de comportamiento de P1.1a; su informe se conserva como referencia histórica. No implementa P1.1c ni P1.2.

## Decisiones y contrato

- `MQTTConsumer` recibe mensajes y contiene excepciones. `RadarNormalizer` mantiene mediciones, reloj y bloqueo por instancia. `prepare_frame` adapta unidades; `process_frame` valida y transforma; `StateHub.publish` sigue siendo la entrada única. Un productor y un worker.
- Solo se aceptan los diez topics numéricos existentes. Los inesperados se cuentan; los retenidos se omiten. El replay P0.3 ya excluye sus diez retenidos antes de publicar.
- Cada campo tiene tiempo monotónico de recepción. Se exige edad X/Y <= 2 s y separación entre sus tiempos <= 250 ms. Se utilizan las últimas muestras, sin interpolación, historial de emparejamiento ni identificación persistente. Los slots siguen siendo referencias 1–3.
- Esta asociación temporal **no identifica una trama UART sincronizada**. Se declara `association=temporal_not_synchronized`. Los tiempos reflejan recepción MQTT, no adquisición física.
- El contador reciente (`reported_count`) es independiente de `observed_slots`. Su ausencia no bloquea coordenadas; cero no borra coordenadas recientes. Una discrepancia activa `count_inconsistent`. No se limita el slot por su número: 1 y 3 son válidos aunque el contador sea 2.
- `occupancy=unknown` evita afirmar ocupación física o habitación vacía. Un contador cero reciente sigue disponible como dato publicado, pero no equivale por sí solo a una confirmación física. Lista vacía significa que ninguna posición supera los criterios.
- NaN, infinitos, texto inválido, bytes no UTF-8 y contador fuera de 0–3 invalidan inmediatamente el campo afectado. Otros campos se conservan hasta caducar. Velocidad ausente, inválida o caducada es `null`, distinta de `0`.
- Desconectar el consumidor invalida campos y contador; reconectar requiere datos nuevos. Los eventos históricos del grabador NO desconectan el consumidor y NO prueban una desconexión del ESP32.
- `observation` añade contador, slots, discrepancia, conectividad, política, motivos de rechazo y contadores de recepción. Se valida antes de reemplazar el estado. `invalid` cuenta payloads inválidos, no muertes del hilo; `callback_errors` cuenta excepciones inesperadas del adaptador.
- `/health` responde 503 ante productor terminado, consumidor desconectado, hilo MQTT ausente/muerto o excepción inesperada registrada. Un payload inválido aislado no lo degrada si la recepción continúa. No hay máquina de estados de salud, ni inferencia de ausencia por silencio. La comprobación del hilo usa `_thread` de paho 2.2.0; revisar al actualizar la dependencia.

Extensión explícita del contrato v1: campo opcional `observation` y velocidad nullable (`speed_cm_s` de entrada, `speed_m_s` de salida). El simulador conserva su forma previa; los clientes antiguos que exijan velocidad numérica necesitan adaptación. El frontend acepta `null`, muestra «Desconocida» y avisa que son posiciones asociadas temporalmente con ocupación no confirmada. No cambia proyección ni transformación: esta sigue exclusivamente en backend. La adaptación de unidades previa se conserva (MQTT mm/s → entrada cm/s → salida m/s); este incremento no certifica la escala del firmware físico.

## Umbrales y comparación reproducible

P0.2 midió X/Y a 0,930 Hz (~1,075 s por publicación en promedio), velocidad a 0,697 Hz. TTL=2 s mantiene el límite anterior y permite un intervalo normal; no oculta pausas largas ampliando la memoria. 250 ms es una política inicial de asociación, no una garantía física derivada de UART. Es bastante menor que el intervalo típico entre publicaciones; la sensibilidad siguiente muestra su coste. Ambos parámetros son configurables por `Policy` y por el lanzador aislado.

Captura original SHA256: `df85b856872ecc9a3325b06639ffcce39c12f602deffe9283d1bba31e6614edf`.

Se alimentó el consumidor anterior conservado antes de editar y el nuevo con los mismos 767 mensajes no retenidos, bytes y tiempos. Referencia: ticks enteros de 1 a 303 s, incluidos tres segundos de cola; UTC derivado del encabezado, sin sockets. El contador retenido se excluye. Dos ejecuciones nuevas producen estados exactamente iguales, no solo el mismo número de posiciones.

| Métrica (ticks fijos) | Antes | P1.1b, 250 ms |
|---|---:|---:|
| Estados | 303 | 303 |
| Con posiciones | 0 | 186 |
| Sin posiciones aceptables | 303 | 117 |
| Estados con rechazo por separación X/Y | No instrumentado | 114 |
| Estados con rechazo por caducidad | Enmascarado por contador | 3 |
| Posiciones con velocidad desconocida | No observables | 19 |
| Payloads nuevos inválidos | 0 | 0 |
| Errores inesperados del consumidor | 0 | 0 |

Hash canónico de la secuencia nueva: `f7a6f540dc4a0bba65641c189b595b80c85d351156d87faaf831a087de894042`. Incluye estados completos (timestamp UTC derivado, posiciones transformadas, velocidades, observación y contadores); no es el `normalized_sha256` del reproductor P0.3. El comando offline ejecuta y compara ambas secuencias.

| Separación máxima X/Y | Con posiciones / 303 | Sin posiciones | Rechazo temporal |
|---|---:|---:|---:|
| 100 ms | 58 | 245 | 242 |
| 250 ms | 186 | 117 | 114 |
| 500 ms | 247 | 56 | 53 |

No elegir el umbral solo por maximizar posiciones: ampliar la ventana aumenta el riesgo de combinar épocas diferentes. Requiere pruebas físicas futuras. Las tres políticas tienen tres ticks con caducidad. En capturas multislots los motivos pueden coexistir: estas columnas no siempre son categorías excluyentes.

Reproducción MQTT a **1x**, con Mosquitto aislado: 777 mensajes leídos, 10 retenidos omitidos, 767 publicados y recibidos, igualdad exacta de topic/bytes/orden, cero errores. Publicación QoS1, entrega al consumidor QoS0 por su suscripción existente; ningún retain. 301 estados: 188 con slot 1, 113 sin posiciones; 109 con rechazo temporal, 4 con caducidad, 15 posiciones con velocidad desconocida. Nunca aparecen slots 2 o 3. La fase del tick y planificación real difieren de los ticks virtuales, por lo que estas cantidades y hashes no deben coincidir. La ejecución terminó ordenadamente y el broker temporal se cerró.

## Validación desde Windows

Desde la raíz del repositorio, con el entorno P0 y Mosquitto local ya instalados. Se muestra el entorno `.venv-p0` utilizado aquí; sustituirlo por `.venv` si ese es el nombre de su instalación. No configurar el broker de Raspberry.

```powershell
$py = '.\.venv-p0\Scripts\python.exe'
$env:SMARTSPACE_REPLAY_CAPTURE = (Resolve-Path '.\captures\ld2450-2026-11-24-01.mqtt.jsonl').Path
$env:SMARTSPACE_TEST_MOSQUITTO = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto\mosquitto.exe'

& $py -m pytest -q
node --test tests/frontend.test.mjs
& $py -m pytest -q -m mqtt
& $py -m mqtt_capture.normalize --input $env:SMARTSPACE_REPLAY_CAPTURE --field-ttl 2 --xy-skew 0.25

$evidence = Join-Path $env:TEMP ('smartspace-p11b-' + [guid]::NewGuid().ToString('N'))
& $py -m mqtt_capture.replay_app --input $env:SMARTSPACE_REPLAY_CAPTURE --mosquitto $env:SMARTSPACE_TEST_MOSQUITTO --speed 1 --field-ttl 2 --xy-skew 0.25 --http-port 8001 --start-delay 3 --exit-after-replay 3 --evidence-dir $evidence
```

Durante la ejecución abrir `http://127.0.0.1:8001`. El lanzador crea su broker propio con credenciales temporales, nunca toma un endpoint de producción. Para las fixtures, sustituir `--input` por `tests\fixtures\mqtt_replay\display_hold.synthetic.mqtt.jsonl` (0, 1, 2, 3 y slots no consecutivos). `multi_target.synthetic.mqtt.jsonl` incluye NaN/binario; su salida puede indicar errores de datos aunque la recepción sobreviva. `reconnection.synthetic.mqtt.jsonl` requiere `--allow-incomplete`. Son datos sintéticos, no evidencia multiobjetivo física.

Acelerar MQTT no acelera el reloj ni TTL del backend: usar 1x para caducidad real y `normalize` para comparación determinista. La referencia offline conserva eventos históricos sin convertirlos en desconexiones actuales, y muestrea a ticks fijos; no pretende reproducir el planificador de Windows.

## Pruebas y cambios intencionados

Resultados: **146 pruebas Python locales**, **7 de integración MQTT** y **5 JavaScript**, todas correctas. Las locales impiden conectar paho incluso si el entorno apunta a LD2450. La captura física es opcional/local: sin `SMARTSPACE_REPLAY_CAPTURE`, su prueba se omite. No se añade ninguna dependencia. Aviso pendiente de Starlette sobre `httpx` en TestClient; no se cambian dependencias en esta fase.

- Se sustituyen las expectativas P1.1a de bloqueo por contador, NaN conservado, velocidad cero artificial, combinación sin límite y muerte del hilo por las nuevas reglas explícitas.
- Se conservan aislamiento, rechazo de replay habilitado solo por variable, rutas normales, bytes/orden MQTT y descarte de retenidos.
- Se prueban TTL y separación en sus límites, invalidez por campo, contador contradictorio/caducado, instancias independientes, estados inválidos que no reemplazan el anterior, slots no consecutivos y velocidad cero frente a desconocida.
- Las fixtures existentes comprueban transición 0–3 y retorno a cero, parcialidad, silencio, valores inválidos y eventos históricos. Una prueba MQTT desconecta/reconecta realmente el consumidor y verifica 503 y recuperación con X/Y nuevas. Las pruebas de integración reciben estados por WebSocket y comparan con la evidencia de StateHub.
- La validación visual manual fue completada por el usuario: captura real con slot 1 y display_hold con slots no consecutivos, tres simultáneos y transiciones correctas. Las cinco pruebas JavaScript siguen siendo pruebas de funciones puras.

Archivos P1.1b: `backend/app/radar_normalizer.py`, `mqtt_capture/normalize.py`, `tests/test_normalized_replay.py` nuevos; cambios en `mqtt_consumer.py`, `radar_bridge.py`, `main.py`, `replay_app.py`, `frontend/js/app.js`, `frontend/js/geometry.mjs`, `tests/test_current_mqtt_characterization.py`, `tests/test_replay_app_integration.py`, `tests/frontend.test.mjs`, README y esta guía. Los cambios previos no confirmados en Git, incluido firmware, no pertenecen a este incremento.

## Limitaciones pendientes

La captura solo valida slot 1. No prueba detección de dos personas ni permite elegir un umbral físico definitivo. La política usa últimas muestras: puede descartar asociaciones que un historial conservaría; no reconstruye tramas ni personas. Contadores/velocidades constantes sin nueva publicación caducan aunque el radar mantenga físicamente el mismo valor. Silencio es desconocido, nunca vacío confirmado. La compatibilidad visual queda comprobada manualmente; falta evaluar capturas físicas multiobjetivo etiquetadas. La salud es instrumentación mínima, no P1.2. Se detiene el desarrollo en P1.1b, sin despliegue ni cambios de firmware, topics o captura.


## Cierre aceptado de P1.1b

El usuario da por completadas normalización y validación visual. Captura real: slot 1 correcto. `display_hold`: slots no consecutivos y tres simultáneos correctos. `multi_target`: 24 recibidos, ocho rechazos esperados (seis NaN, un binario, un vacío), sin excepciones del callback identificadas ni fallos inesperados del consumidor. La reproducción controlada produjo `invalid=8`, `callback_errors=0`; la fase exacta del tick de la ejecución visual no se registró. Tres slots coinciden solo de 0,910 a 1,010 s: 100 ms que el muestreo aproximadamente a 1 Hz puede omitir. Ver solo uno en esa fixture no contradice la validación sostenida con display_hold.

Referencia determinista: 0 → 186 estados con posiciones aceptables sobre 303. Última suite completa de P1.1b: 146 Python locales, 7 MQTT, 5 JavaScript; revisión posterior: 26 pruebas pertinentes correctas.

Pendientes registrados, expresamente sin implementar en P1.1c.1:

- Separar rechazos de datos inválidos de errores reales del consumidor.
- Exigir exactamente ocho rechazos en la prueba de multi_target.
- Revisar la frecuencia de generación de estados del backend.
- Evitar etiquetar replay como datos en directo.
- Corregir la codificación del indicador de conexión.
- Validar físicamente múltiples personas.
