# P1.1c.2 — Validación física parcial (27-11-2026)

El usuario confirma que cargó el firmware y recibió informes completos en `smartspace/esp32/radar/frame/v1`. Las cifras siguientes se contrastaron en lectura con los tres archivos originales del repositorio. **Se acepta la adquisición MQTT durante estos ensayos; la validación física multiobjetivo sigue abierta.** No se realizaron nuevas actuaciones sobre hardware en P1.1c.3.

| Captura | Duración indicada por usuario | Informes | 0 slots | 1 slot | 2 slots | 3 slots | Intervalo ESP primero–último |
|---|---:|---:|---:|---:|---:|---:|---:|
| ld2450-frequency-v1.jsonl | 60 s | 675 | 0 | 612 | 63 | 0 | 59,977056 s |
| ld2450-two-persons-v1.jsonl | 60 s | 674 | 0 | 535 | 139 | 0 | 59,890319 s |
| ld2450-controlled-test-v1.jsonl | 105 s | 1180 | 0 | 954 | 192 | 34 | 104,915539 s |

La tasa indicada por el usuario, N/duración de la prueba, es 11,25 Hz en la primera y 11,24 Hz en la tercera. Usando los intervalos internos del ESP, `(N−1)/(rx_us último−primero)`, se obtiene respectivamente **11,237631; 11,237208; 11,237611 Hz**. Son métricas distintas y compatibles. No son una medición UART independiente ni permiten calcular latencia MQTT.

Cada archivo contiene una sesión y cero saltos de seq, duplicados, regresiones temporales o payloads inválidos. No se observaron intervalos ESP >500 ms entre los informes guardados. Los extremos del registro no permiten demostrar ausencia de pérdidas antes del primero o después del último. La segunda y tercera capturas comparten boot_id; no deben contarse como dos reinicios.

- Primera: seq 2633–3307, offline_reports constante 61; previous_callback_max_us constante 7849.
- Segunda: seq 4923–5596, offline_reports constante 63; previous_callback_max_us constante 6612.
- Tercera: seq 8027–9206, offline_reports constante 63; previous_callback_max_us constante 6612.
- En las tres: invalid_reports, decimated_reports y enqueue_failures constantes en cero.
- Mayor tramo de dos slots en la segunda: **11,559492 s**, entre primer y último informe consecutivo del tramo. En la tercera, mayor tramo de tres: 2,925877 s. No se extrapola hasta la siguiente muestra.

Los contadores y máximos del firmware son acumulados: 63 offline constante no significa 63 desconexiones durante esa captura, y 6,612 ms es el máximo histórico reportado, no un percentil ni una duración medida para cada callback de ese intervalo. La primera sesión reporta un máximo histórico diferente: 7,849 ms. La medición de callback definida en P1.1c.1 empieza después de la copia y no incluye todo el parser UART.

## Límites de interpretación

La ocupación física no se etiquetó con tiempos sincronizados. No hubo dos personas durante toda la segunda prueba. En la tercera se giró el radar para intentar representar ausencia; no se sabe si había una tercera persona cuando aparecieron tres slots. Por ello:

- Los porcentajes de slots NO son tasas de acierto.
- El tercer slot NO es un falso positivo confirmado.
- No observar informes vacíos NO confirma un fallo.
- No se considera validada la precisión física multiobjetivo ni identidad persistente de personas.
- Siguen pendientes UART pasiva independiente, prueba controlada de pérdida de comunicación, ausencia real etiquetada y comparación de modo multiobjetivo por consulta/respuesta.

Los archivos son líneas de payload JSON de mosquitto_sub. No contienen timestamp UTC/monotónico del receptor, QoS, retain, dup, conexión ni cierre de captura. Las importaciones P1.1c.3 declaran estos datos desconocidos, nunca los reconstruyen como observaciones. Los originales no se alteran.

SHA256 originales:

- frequency: `8e46b5d82d9fb041f89e5a48a03fc18e599bf30680c294b3d792614d26a471f8`
- two-persons: `168be964c59141a5764425f1ee5730862b79a0ca4bac94901d122c5ef08bd87b`
- controlled-test: `a044599ba98ac8399cf4fed374844eafcdc1a2a3cf120570f8c4c430ee8eb9a7`
