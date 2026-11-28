# Progreso P1.2b

Implementado y validado automáticamente; pendiente revisión manual. Los pendientes de bloques anteriores son históricos. Git inicial limpio, rama consolidate/p12a, sin nuevos commits.
Bloque 1: panel desplegable nativo, módulo de presentación y polling independiente, gráfico SVG sin historial acumulado. Archivos frontend/index.html, css/styles.css, js/app.js y nuevo js/diagnostics.mjs. Backend y firmware intactos.
Pendiente: pruebas automatizadas, revisión de robustez, validación visual aislada y documentación final. No declarar completado hasta verificar los criterios.

Bloque 2: 14/14 pruebas JavaScript correctas (5 previas y 9 nuevas). Cubren ejemplos reales del contrato, estados, null/cero, cortes del histórico, timeout, recuperación, una sola petición y cancelación de temporizadores. Regresión Python en ejecución. Pendientes validación visual, pruebas MQTT y documentación final. Sin commits/push.

Bloque 3: 206/206 Python correctas. Captura real controlled-test reproducida a 10x en broker aislado; navegador Edge headless verificó espera, observación, normal y stale. Capturas locales en work/p12b/visual-1.png a visual-4.png (fuera de Git). Panel stale muestra detecciones desconocidas y MQTT backend-broker conectado. WebSocket observado 9,2 Hz/configurado 10 en una muestra, posiciones continuaron cambiando. No es un benchmark controlado de latencia ni del dispositivo. Validación móvil/sintética y fallos HTTP en curso.

Bloque 4 — cierre automático: 206 Python, 12 MQTT y 16 JavaScript correctas. Panel desktop/móvil verificado con captura real y fixture sintética. Error/recuperación de API verificados mediante bloqueo de URL en navegador, con WebSocket de simulación activo. Se preservó apertura y foco de sección técnica entre consultas. Documentación incluye comando exacto de radar real para el usuario (no ejecutado), límites y archivos modificados.
Estado final: implementación y validación automática terminadas; pendiente validación manual del usuario antes de commit/push. No avanzar a P1.3/P2. No atribuir recuperación física ni cero objetivos directos a estas pruebas aisladas.
