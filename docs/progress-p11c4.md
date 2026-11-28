# Progreso P1.1c.4

Estado: COMPLETADO el 27-11-2026. Criterios verificados en docs/frame-backend-p11c4.md. Los pendientes de cada bloque inferior son historicos; el cierre final los sustituye.

## Plan de bloques

1. Adquisición atómica por instancia, reutilizando mqtt_capture.frames.validate; reglas temporales y pruebas unitarias.
2. Integración MQTT → StateHub → WebSocket, selección frames/legacy y publicación desacoplada; pruebas de concurrencia/cierre.
3. Replay aislado, referencia virtual, 2529 informes reales y comparación/rendimiento.
4. Regresión completa, documentación/validación visual y revisión de criterios.

Restricciones: no tocar firmware ni originales, no producción/Raspberry, no P1.2/P1.3/P2. Preferir cambios acotados. Copia de hashes iniciales local en work/p11c4/protected.json del chat.

## Bloque 1 — completado

Archivos: backend/app/frame_acquisition.py (nuevo), tests/test_frame_acquisition.py (nuevo).
Reutiliza el validador P1.1c.3. Copia atómica del informe completo, separación de reloj ESP/recepción backend, TTL de informe entero, cero válido frente a silencio, retención y reglas de orden/sesión sin fallback. El último informe se conserva como procedencia al caducar, pero deja de aportar posiciones actuales. Estado por instancia con RLock y sin cola de informes.
Pruebas: 4/4 unitarias nuevas correctas, sin broker. Cubren 0–3, 1+3, resolución, invalidación, TTL, duplicados/conflictivos, orden, regresión de reloj, salto, nueva sesión y rechazo de sesión retirada.
Pendiente: conectar este módulo al consumidor/hub y ampliar contrato WebSocket; todavía NO hay integración funcional en la aplicación. Después ejecutar reproducción real, rendimiento, concurrencia y regresión completa.

## Bloque 2 — integración implementada; validación parcial

Archivos: backend/app/{mqtt_consumer,radar_bridge,main}.py, mqtt_capture/replay_app.py y tests/test_frame_acquisition.py.
Selección explícita frames/legacy, suscripción exclusiva, StateHub.publish por cada informe aceptado y envío WebSocket separado a 10 Hz con cola de último estado de tamaño 1. Metadatos del informe y recepción backend separados. Evidencia a disco opcional en replay.
El cierre WebSocket usa un grupo de tareas estructurado (AnyIO ya es dependencia de FastAPI), cancelando emisor/receptor conjuntamente y retirando suscriptores incluso sin estado inicial. La limpieza anterior mezclaba tareas asyncio y cancelación del portal AnyIO; causa exacta del fallo histórico aún no demostrada.
Pruebas: 34 correctas, 1 omitida por captura local no configurada. Incluyen 100 ciclos con dos WebSockets simultáneos sin estado inicial y verificación de limpieza (200 conexiones), validación atómica y cola limitada.
Pendiente: pruebas MQTT completas, carga sostenida, tres capturas reales, frontend y regresión general. P1.1c.4 sigue EN CURSO.

## Bloque 3 - validacion funcional y rendimiento completados

Archivos: mqtt_capture/normalize_frames.py, tests/test_frame_backend_integration.py, tests/fixtures/frame_reports/display.synthetic.jsonl y frontend/js/app.js.
Los 2529 informes se aceptan tanto en referencia virtual como por MQTT aislado: 675 + 674 + 1180. Cero errores del consumidor y cero rechazos inesperados. Dos referencias virtuales por captura producen estados identicos; metadatos de reloj virtual se identifican como prueba, no recepcion fisica.
Carga real a velocidad 1: 675 informes en unos 60 segundos, 675 aceptados, errors=0. Integracion adicional a 100 Hz; cola por WebSocket limitada a un estado. Regresion MQTT completa: 12 pruebas correctas en 59,73 s.
Regresion local: 188 correctas, una compilacion opcional omitida; dicha compilacion se ejecuto posteriormente por separado y paso (1/1). Advertencia existente de Starlette/httpx; sin cambios de dependencias.
Frontend: solo textos para distinguir informe completo, silencio y reproduccion. El navegador habitual fallo al crear sus recursos; comprobacion alternativa local en curso.
Pendiente: cerrar evidencia visual, documentacion tecnica/comandos y revision final de archivos protegidos. No se ha avanzado a otras fases.

## Bloque 4 — verificación visual y cierre documental

Archivos: docs/frame-backend-p11c4.md y este registro; pruebas de carga completadas con un WebSocket activo. Último ajuste funcional: bloquear la retirada del callback durante el cierre para no competir con una recepción en curso.
Verificación visual: Edge headless con perfil temporal, frontend real y broker aislado. Confirmados 0, 1, 1+3, 3, cero válido, silencio y recuperación. Seis informes, cero errores. Capturas y DOM guardados en work/p11c4 del chat. Limitación documentada: el navegador habitual falló; se utilizó Edge local con autorización de ejecución.
Pruebas: regresión local 188/188 más compilación C++ separada 1/1; JavaScript 5/5. Regresión MQTT 12/12 antes del último ajuste de cierre; prueba afectada de carga/cierre repetida correctamente después, y regresión MQTT completa final en ejecución. Margen medido: 99,00 Hz frente al objetivo 100; nativa 11,27 Hz frente a 11,25. Hashes: 17 archivos protegidos intactos. git diff --check correcto.
Documentación: arquitectura, reglas de aceptación/rechazo, relojes, costes comparados, límites, comandos Windows, inventario de archivos y tabla de criterios completos. Pendiente únicamente registrar el resultado final de regresión MQTT que ya está en ejecución; no avanzar a otra fase.


## Cierre final

Regresion MQTT final tras el ajuste de cierre: 12/12 correctas en 63,24 s. Regresion local: 188 correctas mas compilacion separada 1/1; JavaScript: 5/5. Sin pruebas fallidas pendientes. Advertencia de deprecacion Starlette/httpx documentada. UTF-8 verificado y git diff --check sin errores. Los 17 archivos protegidos mantienen sus hashes.
Todos los criterios de P1.1c.4 satisfechos con las limitaciones explicitas del informe. Validacion fisica de precision y pruebas UART siguen siendo trabajo pendiente anterior, fuera de este incremento. Sin despliegues, cambios de firmware, cambios de originales ni avance a fases posteriores. Desarrollo detenido al completar P1.1c.4.
