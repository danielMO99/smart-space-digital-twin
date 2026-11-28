# P0.3 - Criterios de aceptación y resultados

Validación del 26/11/2026. Alcance cerrado en P0.3; P1 no implementado.

## Entorno y pruebas ejecutadas

Windows x64, CPython 3.11.9, paho-mqtt 2.2.0, Node.js 22.19.0 y Mosquitto 2.1.4
x64 extraído localmente. No se registró ningún servicio ni se usó Raspberry Pi.
No se añadieron dependencias Python ni se cambiaron constraints de P0.1.

| Comprobación | Resultado |
| --- | --- |
| `python -m pytest -q` | 117 pasan; 3 MQTT excluidas por defecto |
| Incrementos anteriores | Las 54 pruebas Python anteriores siguen pasando |
| Nuevas pruebas unitarias P0.3 | 63 pasan, sin broker ni hardware |
| `python -m pytest -q -m mqtt tests/test_mqtt_replay_integration.py` | 3 pasan, incluyendo la captura real local |
| `node --test tests/frontend.test.mjs` | 4 pasan |
| `python -m pip check` | Sin dependencias rotas |
| `git diff --check` | Sin errores |
| Reproducción CLI de fixture sintética a 10x | Cierre correcto; 24 publicaciones, 2 retenidos omitidos |
| Reproducción CLI de captura real a 100x | Cierre correcto; 767 publicaciones, 10 retenidos omitidos, cero errores |

Persiste el aviso previo `StarletteDeprecationWarning` por HTTPX/TestClient.
No se oculta ni se cambia esa dependencia fuera del alcance P0.3.

La integración prueba los bytes completos y el orden de todos los mensajes, QoS
de salida 1, `retain=False` y un suscriptor tardío sin entregas retenidas. Una
tercera prueba termina el broker propio y comprueba la parada del replay, sin
reconexión automática ni reenvíos ambiguos. La salida de los procesos hijos se
comprueba al finalizar las fixtures.

Durante la revisión, la prueba con QoS de origen mezclados detectó un adelantamiento
de QoS 0 frente a QoS 2. Se fijó QoS 1 para todas las publicaciones y un único mensaje
en vuelo en el broker; el QoS original queda en la traza. La prueba afectada pasó
cinco ejecuciones consecutivas adicionales. Esto verifica el comportamiento local,
no una garantía de temporización exacta en cualquier red.

## Comparación con la captura física

Fuente local: `captures/ld2450-2026-11-24-01.mqtt.jsonl`, sin modificaciones.

SHA-256 original antes y después:

```text
df85b856872ecc9a3325b06639ffcce39c12f602deffe9283d1bba31e6614edf
```

Se ejecutaron dos reproducciones virtuales independientes a velocidad 1. Se
compararon los eventos completos, los bytes de ambas trazas derivadas y, registro
a registro, secuencia, UTC original, tiempo monotónico/previsto, topic, bytes del
payload, retain y QoS originales. No se usa el backend para esta comparación.

| Elemento | Original | Reproducción |
| --- | --- | --- |
| Registros totales | 785 | 785 eventos derivados, mismo orden |
| Mensajes MQTT | 777 | 767 publicables + 10 omitidos por retain |
| Eventos de conexión/estado | 6 | 6 observados, no publicados |
| Cabecera y cierre | 2 | 2 observados |
| Tiempo monotónico final | 300.000.000.000 ns | Igual con velocidad 1 |
| Topics y bytes | 10 topics; payloads Base64 | Exactos en la representación; sin conversiones numéricas |
| Retain de salida | 10 entregas originales retenidas | Ninguna publicada; todas las publicaciones sin retain |
| QoS | 777 mensajes recibidos con QoS 0 | Publicaciones QoS 1; `original_qos=0` conservado |
| Slots 2 y 3 | Solo NaN retenidos | Ninguna publicación nueva inventada |
| Contador | Un `1` retenido | No publicado como detección reciente |
| Errores del replay | No aplica | 0 |

Las dos secuencias normalizadas son iguales. SHA-256 de su representación canónica:

```text
ff284973ca1d4c343e623f667ae9ae9a3b6051d3e763d6e719bc1d650e158afe
```

Las dos salidas JSONL derivadas son también idénticas byte a byte. SHA-256 del archivo
(con espacios de formato, distinto del JSON canónico anterior):

```text
b7fef3c5f97def88254f73c361122edda9703d73eb0db213438e3845bb61be7d
```

El hash de eventos cambia al cambiar `--speed`, porque contiene `scheduled_ns`.
No cambia por el identificador del cliente MQTT, puerto aleatorio o reloj de pared:
esos detalles de ejecución no forman parte de la secuencia normalizada.

## Criterios de aceptación

| Criterio | Evidencia y estado |
| --- | --- |
| Formato v1 y bytes originales | Prevalidación completa; pruebas de versión, esquema, Base64, vacío y binario. Cumplido. |
| Orden, empates e intervalos | Secuencia sin ordenar de nuevo; plazos absolutos; velocidades 1, 10, 0.5 y 3 con reloj virtual. Cumplido. |
| Determinismo de dos ejecuciones | Fixtures y captura real producen eventos iguales; comparación física documentada arriba. Cumplido. |
| Broker exclusivamente aislado | Proceso temporal propio, loopback, puerto dinámico, autenticación y ACL. CLI rechaza broker/puerto externos. Cumplido. |
| Ausencia de comandos | Allowlist exacta en lector, publicador y ACL; rechazo de topics ajenos. Cumplido. |
| Retenidos históricos | Omitidos de MQTT, conservados como metadatos incluso tras reconexión. Cumplido. |
| Eventos y huecos | Se conservan en la cronología como eventos del grabador, sin simular caída del ESP32. Cumplido. |
| Datos inválidos/incompletos | Inválidos siempre bloquean antes de conectar; incompletos parseables exigen opt-in. Cumplido. |
| Cierre y fallos de ejecución | Ctrl+C, error de publicación/escritura, timeout y fallo durante el silencio final tienen pruebas. Cumplido. |
| Escenarios sintéticos pedidos | 0/1/2/3/0, slots 1 y 3, parcial/asíncrono, NaN, retain, huecos y reconexión. Cumplido; no son pruebas físicas. |
| Compatibilidad P0.1/P0.2 | Suite anterior conservada; grabador sin cambios funcionales. Cumplido. |
| Límites de alcance | Captura, backend, frontend, firmware y topics sin cambios; sin despliegue ni P1. Cumplido. |

## Archivos añadidos o modificados por P0.3

| Archivo | Cambio |
| --- | --- |
| `mqtt_capture/replay.py` | Nuevo: validación, reloj inyectable, reproducción, eventos y CLI |
| `mqtt_capture/isolated_broker.py` | Nuevo: broker temporal y publicador Paho |
| `mqtt_capture/__init__.py` | Solo descripción del paquete |
| `tests/test_mqtt_replay.py` | Nuevas pruebas unitarias |
| `tests/test_mqtt_replay_integration.py` | Nuevas pruebas con broker propio, marca `mqtt` |
| `tests/fixtures/mqtt_replay/README.md` | Procedencia sintética y escenarios |
| `tests/fixtures/mqtt_replay/multi_target.synthetic.mqtt.jsonl` | Fixture pequeña de escenarios y payloads |
| `tests/fixtures/mqtt_replay/reconnection.synthetic.mqtt.jsonl` | Fixture incompleta con recuperación |
| `tests/fixtures/mqtt_replay/truncated.synthetic.mqtt.jsonl` | Fixture incorrecta deliberada |
| `docs/mqtt-replay.md` | Instalación, comandos PowerShell, semántica y límites |
| `docs/mqtt-replay-validation.md` | Este registro de aceptación |
| `README.md` | Entrada P0.3 y selección actualizada de pruebas |

El repositorio ya contenía cambios locales de integración y de P0.2. Se preservaron;
no se confunden con cambios de este incremento ni se crea commit/push en esta tarea.

## Pendientes y recomendaciones para P1

- Obtener evidencia física multiobjetivo y fases sincronizadas; esta captura solo
  aporta novedades del slot 1. Las fixtures sintéticas no validan el radar.
- Definir explícitamente la normalización de ejes asíncronos, unidades, NaN y TTL
  antes de alimentar StateHub. No reconstruir objetivos ausentes.
- Cuando se autorice integrar el replay en la aplicación, mantener un solo productor
  y mostrar el origen replay en el estado operativo y frontend. En P0.3 se identifica
  únicamente en la CLI/traza, conforme al alcance que prohíbe modificar el frontend.
- El reloj real no es de tiempo duro; a velocidades altas puede acumular retraso
  de transporte. No se promete igualdad de timestamps de recepción MQTT.
- El lector carga el archivo en memoria. Un cierre forzado del sistema puede dejar
  recursos temporales; el cierre ordenado y los errores gestionados sí los liberan.
- La captura incompleta no se repara y una publicación de entrega incierta no se
  reintenta. Los fallos de red son observables, no se convierten en medidas válidas.

No se avanza a P1. Los [comandos exactos de ejecución](mqtt-replay.md) permiten
repetir las comprobaciones con el entorno y la captura local disponibles.
