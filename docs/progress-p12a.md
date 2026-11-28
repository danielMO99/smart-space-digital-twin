# Progreso P1.2a

Estado: COMPLETADO. Los pendientes de los bloques anteriores son historicos y quedan sustituidos por el cierre final. No avanzar a P1.2b/P1.3/P2.

## Bloque 1 — motor independiente implementado, pendiente de pruebas

Archivo nuevo: backend/app/acquisition_diagnostics.py. Reutiliza resultados y contadores de adquisición, bloqueo de instancia compartido y reloj inyectable. Ventanas 10/60 s con capacidad fija; separación conexión/frescura/integridad/frecuencia; referencia de contadores ESP por boot_id y detección de regresiones. Sin persistencia por informe.
Pendiente: pruebas unitarias, conexión de observadores MQTT/WS, endpoint y contrato, capturas reales, rendimiento y regresión. No se declara validado todavía.

## Bloque 1 — validado; bloque 2 — integración implementada

Pruebas: 11/11 correctas en tests/test_acquisition_diagnostics.py, sin broker. Incluyen reloj virtual, 0 objetivos sin alarma, caída de tasa, caducidad, reconexión, rechazos, reinicio de contadores, memoria de 32 muestras bajo 2000 informes y lectores concurrentes.
Archivos modificados: backend/app/mqtt_consumer.py (observación del resultado de ingestión), radar_bridge.py (origen, frecuencia configurada y muestreo periódico), main.py (ciclos de distribución y endpoint /api/diagnostics). /health no cambia. El frontend, firmware y capturas siguen intactos.
Pendiente: validar endpoint por MQTT aislado y capturas reales, determinismo completo, medir coste, contrato/documentación/ejemplos y regresión total. No se considera P1.2a completado.

## Bloque 2 — validado; bloque 3 — capturas y rendimiento

Endpoint y flujo real del broker aislado: 12/12 pruebas MQTT correctas en 62,32 s, incluyendo las anteriores. Las tres capturas siguen aceptando 675 + 674 + 1180 = 2529 informes sin errores inesperados. El endpoint distingue servicio correcto y telemetría stale. Los offline históricos 61/63 no producen incrementos nuevos.
Referencia virtual: 14/14 pruebas unitarias nuevas correctas; dos diagnósticos idénticos por captura. Las tres terminan normales antes del silencio y stale tras 61 s sin datos. Frecuencia reciente virtual de aceptación 11,3 Hz; la referencia ESP permanece separada (~11,24 Hz).
Microbenchmark local, 3540 procesamientos por condición: media sin observador 0,2926 ms, con observador 0,3450 ms (+0,0524 ms); p95 0,4664/0,6454 ms; snapshot medio 0,6684 ms. Medición local sin garantía de Raspberry. Resultados guardados en work/p12a del chat.
Archivos: mqtt_capture/diagnose.py (referencia virtual), tests/test_acquisition_diagnostics.py y ampliación tests/test_frame_backend_integration.py. Pendiente: contrato, ejemplos, documentación final, regresión local/JS y comprobación de archivos protegidos.

## Bloque 4 — contrato, documentación y regresión final

Archivos nuevos: docs/sensor-health-p12a.md; docs/contracts/acquisition-diagnostics-v1.schema.json y acquisition-diagnostics-v1.examples.json (cinco escenarios sintéticos con envolvente completa). Documentados umbrales provisionales, unidades, referencias temporales, origen replay, capacidad/ventanas, limitaciones y comandos Windows. Incidencias manuales de P1.3/P2 registradas sin tocar frontend.
Se añadieron pruebas de primer informe tardío/nuevo boot, independencia entre servicio/MQTT y límite del histórico. Total final local: 206/206, incluida prueba C++ existente; cero omisiones. JavaScript: 5/5. Referencia CLI real: determinista, 1180 aceptados, mismo hash de diagnóstico. Segunda medición reproducible: 0,2944 ms sin observador frente a 0,3108 ms con observador; snapshot 0,5511 ms. La variación respecto del primer ensayo está documentada y no se presenta como garantía de tiempo real.
22 archivos protegidos intactos por SHA256, incluidos todos los archivos del frontend. git diff --check sin errores. Pendiente registrar la última regresión MQTT y cerrar la tabla de aceptación; sin avance a fases posteriores.


## Cierre final

Ultima regresion MQTT con el codigo final: 12/12 correctas en 62,08 s. Total: 206 pruebas locales, 12 MQTT y 5 JavaScript, todas correctas; sin pruebas omitidas pendientes. Criterios de aceptacion satisfechos y limitaciones documentadas en docs/sensor-health-p12a.md. Motor, API versionada, ejemplos, pruebas y comandos Windows entregados. No se realizaron despliegues ni conexiones de produccion. Desarrollo detenido al finalizar P1.2a.
