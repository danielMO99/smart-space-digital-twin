# P1.2b — Panel de diagnóstico

Panel desplegable bajo la habitación, implementado con HTML/CSS/JS/SVG nativos y sin dependencias. Consume /api/diagnostics v1; no modifica adquisición, diagnóstico, geometría ni firmware. No se ha hecho commit/push; la validación manual del usuario sigue siendo necesaria antes de publicar.

## Decisiones

El panel traduce estados del backend, sin calcular salud ni umbrales. Servicio, MQTT backend-broker, dispositivo no observable, frescura, TTL, tasas, edades y detecciones permanecen separados. Null es no disponible o detecciones desconocidas; cero válido es 0 detecciones, nunca prueba de habitación vacía. occupancy sigue unknown. simulation_enabled describe configuración del simulador, no la fuente activa: el panel usa acquisition.source/mode. window_complete=false se muestra como ventana incompleta. Los controles generales del simulador en directo siguen pendientes de P1.3.

Contadores y datos ESP32 se despliegan en una sección secundaria: acumulados separados de incrementos, máximo de callback en microsegundos sin tratarlo como contador, boot_id y secuencia. Los textos procedentes de la API se insertan con textContent, no HTML.

Consulta serial: una petición, timeout 3 s y siguiente intento 1 s después de terminar. No hay intervalos acumulados ni historial local creciente. Un timeout o error HTTP/JSON elimina la presentación anterior, informa API no disponible y reintenta. Una respuesta tardía abortada no puede restaurar normal. Durante consulta se etiqueta la muestra anterior; pagehide aborta y cancela los temporizadores. El WebSocket de posiciones permanece independiente.

Gráfico de aceptación: solo muestras API en los últimos 60 segundos monotónicos relativos al snapshot; escala automática, puntos reales y umbral backend (solo frames). Null y huecos >2 s interrumpen el trazo; el corte de 2 s es una convención de dibujo para el histórico aproximadamente 1 Hz, no un umbral de salud. No interpolación ni extensión al tiempo actual. Cero se dibuja en el eje. Cada respuesta sustituye el gráfico anterior. En replay se indica que el reloj del backend es real mientras los informes ESP son históricos; el reloj virtual se etiqueta cuando así lo declara el contrato.

## Evidencia física aportada por el usuario (no repetida aquí)

Normal: 11,1 Hz MQTT; 11,24 Hz ESP; 9,1 Hz WS frente a 10 configurados; edad 110 ms; 415/415 aceptados; cero incidencias. Tras desconectar equipo: stale, MQTT backend-broker conectado, edad 14,953 s, tasas MQTT 0, ESP null, objetivos null, ocupación unknown y 2557/2557 aceptados. No se da por realizada la recuperación física ni el ensayo directo de cero objetivos.

## Validación local

Pruebas JS de ejemplos versionados, estados, cero/null, modos, huecos del histórico y temporizadores. Pruebas Python previas sin alterar lógica. Visualización en Edge con perfil temporal y broker propio: captura real controlled-test a 10x, estados espera/observación/normal/stale; capturas locales work/p12b/visual-1.png a visual-4.png del chat, no versionadas. Muestra visual WS 9,2/10 Hz y posiciones actualizándose mientras el panel se consulta. Esto no certifica ausencia de impacto bajo cualquier carga ni latencia extremo a extremo.

## PowerShell — validación manual con radar real

**Comando para el usuario, no ejecutado por el asistente.** Usa la configuración directa del banco ya existente; no configura seguridad ni cambia firmware. Desde la raíz del repositorio, detener primero otros servidores que usen el puerto:

```powershell
$env:SMARTSPACE_SOURCE='ld2450'
$env:SMARTSPACE_ACQUISITION='frames'
$env:SMARTSPACE_WS_HZ='10'
.\.venv-p0\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Abrir http://127.0.0.1:8000 y desplegar «Diagnóstico del sensor», debajo de la habitación. Verificar fuente Directo/frames, frecuencias, edades y separación entre MQTT y telemetría; registrar por separado recuperación física y cero objetivos, pendientes. No confundir el estado del panel con confirmación de ocupación.

## Repetición aislada y pruebas

```powershell
$python='.\.venv-p0\Scripts\python.exe'
$mosquitto=Read-Host 'Ruta completa a mosquitto.exe'
$run=Join-Path $PWD ('outputs\p12b-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $run | Out-Null
& $python -m mqtt_capture.import_frames --input tests/fixtures/frame_reports/display.synthetic.jsonl --output "$run/display.import.jsonl" --evidence-kind synthetic
& $python -m mqtt_capture.replay_app --input "$run/display.import.jsonl" --mosquitto $mosquitto --acquisition frames --allow-unknown-retain --speed 0.5 --field-ttl 5 --manual-start --http-port 8001
```

Abrir http://127.0.0.1:8001. La fixture lenta puede generar frecuencia degradada: es correcto según la tasa recibida y los umbrales backend. No cambiar esos umbrales en JavaScript para aparentar normalidad.

```powershell
& $python -m pytest -q
node --test tests/frontend.test.mjs tests/diagnostics.test.mjs
$env:SMARTSPACE_TEST_MOSQUITTO=$mosquitto
& $python -m pytest -m mqtt -q
git diff --check
```

Las pruebas físicas opcionales requieren las variables/capturas de P1.2a. Sin ellas se omiten. Para simulación arrancar SMARTSPACE_SOURCE=simulator; el diagnóstico MQTT no disponible es esperado, no fallo de API.

## Archivos

Modificados frontend/index.html, frontend/css/styles.css y frontend/js/app.js. Nuevos frontend/js/diagnostics.mjs, tests/diagnostics.test.mjs, docs/sensor-health-p12b.md y docs/progress-p12b.md. El manifiesto de publicación de la auditoría anterior es una instantánea de P1.2a; deberá revisarse cuando se autorice publicar P1.2b.

## Cierre de validación automática

206/206 pruebas Python, 12/12 MQTT y 16/16 JavaScript (5 anteriores y 11 nuevas) correctas. La integración mantiene la aceptación de los 2529 informes reales. Ensayo visual adicional: controlled-test 1180/1180 reproducidos a 10x, sin errores del reproductor; fixture display sintética en móvil (390 px), estados de frecuencia degradada y stale esperados por su baja cadencia. Capturas y DOM en work/p12b del chat, excluidos de Git.

Fallo de API verificado bloqueando únicamente /api/diagnostics con DevTools del navegador local en modo simulación: se retira el diagnóstico anterior y se indica API no disponible, mientras las posiciones continúan actualizándose. Al desbloquear vuelve el diagnóstico legítimamente unavailable del simulador, distinto de fallo de transporte. Imágenes work/p12b/synthetic/api-error.png y api-recovery.png. Esta recuperación es HTTP local; no se presenta como recuperación física del radar. Las capturas visuales de desconexión MQTT/integridad no se obtuvieron; esos estados se validaron mediante los ejemplos y tests automatizados.

La lectura de contadores conserva sección abierta y foco entre respuestas. Git diff --check correcto. No se modificaron adquisición, diagnóstico, firmware ni originales. No se conectó al broker de producción ni se realizó commit/push. Implementación y validación automática terminadas; validación manual del usuario pendiente antes de publicar.
