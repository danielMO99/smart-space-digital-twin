# P1.1a: integración y referencia del comportamiento actual

Validación del 26/11/2026. No se implementa P1.1b. El consumidor numérico,
prepare_frame, process_frame y renderizado SVG conservan sus reglas anteriores.

## Ejecutar en Windows

Desde PowerShell:

```powershell
cd C:\Users\danie\Desktop\smart-space-digital-twin
$mosquitto = 'C:\Users\danie\Documents\Codex\2026-11-23\lee-el-archivo-agents-md-y\work\mqtt-tools\mosquitto\mosquitto.exe'
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay_app --input .\captures\ld2450-2026-11-24-01.mqtt.jsonl --mosquitto $mosquitto --speed 1 --http-port 8001 --manual-start --start-delay 0 --evidence-dir .\captures\p11a-real-01
```

Abrir http://127.0.0.1:8001/ y pulsar **Iniciar reproducción**. Se reproduce una
sola vez. Ctrl+C cierra la aplicación y el broker temporal. El directorio de
evidencias debe ser nuevo. Para cierre automático añadir `--exit-after-replay 5`.
La aplicación sigue produciendo estados después del último mensaje para observar
la caducidad. La ruta del ejecutable puede sustituirse por otra distribución local
de Mosquitto, según la instalación documentada en mqtt-replay.md.

El lanzador crea el broker de P0.3 con autenticación efímera, ACL y loopback; no
acepta host MQTT externo. FastAPI escucha solo en 127.0.0.1, un worker. El objeto
de sesión selecciona replay aunque SMARTSPACE_SOURCE contenga ld2450. Exportar
SMARTSPACE_SOURCE=replay sin el lanzador falla: no habilita un broker arbitrario.
No se instalan servicios ni se configura Raspberry Pi.

Para las fixtures existentes, cambiar únicamente `--input` y el directorio:

```powershell
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay_app --input .\tests\fixtures\mqtt_replay\multi_target.synthetic.mqtt.jsonl --mosquitto $mosquitto --speed 0.5 --start-delay 0 --http-port 8001 --exit-after-replay 5 --evidence-dir .\captures\p11a-synthetic-01
.\.venv-p0\Scripts\python.exe -m mqtt_capture.replay_app --input .\tests\fixtures\mqtt_replay\reconnection.synthetic.mqtt.jsonl --allow-incomplete --mosquitto $mosquitto --speed 1 --http-port 8001 --exit-after-replay 5 --evidence-dir .\captures\p11a-reconnect-01
```

Ejecutarlas por separado. La primera contiene un payload binario deliberado:
el consumidor actual falla al decodificarlo. El diagnóstico registra ese error;
no se ha arreglado ni filtrado para obtener un resultado favorable.

## Instrumentación y alcance

`mqtt_capture/replay_app.py` coordina broker, reproductor y aplicación. El puente
acepta una sesión aislada opcional; conserva lectura, conversión y publicación a
StateHub cada segundo. En replay se reinicia la caché a los valores de un proceso
nuevo. Los callbacks originales procesan los mismos bytes; la instrumentación
registra errores y los vuelve a lanzar, preservando su efecto.

`/api/runtime` informa del origen, fichero, velocidad, fase y contadores de
diagnóstico. `/api/replay/start` inicia la única reproducción. El frontend añade
un aviso de replay y deshabilita controles del simulador. No cambia geometría,
validez de tramas, watchdog ni la conversión de medidas. Los estados de medidas
siguen llevando source=ld2450; la identificación replay está en el contexto
operativo y el banner, no se ha ampliado todavía el contrato de Frame.

Evidencias separadas: replay.jsonl conserva los eventos programados; received.jsonl
contiene los bytes recibidos y caché resultante; states.jsonl contiene trama cruda,
adaptada y estado global; transport.jsonl distingue la conexión real del backend
de los eventos históricos de la captura. summary.json resume al cerrar. No se
guardan credenciales. Los tiempos elapsed_ns son de diagnóstico; los tiempos de
los campos son del reloj monotónico del consumidor, no timestamps del radar.

## Resultados observados

**Captura física a velocidad 1:** 777 mensajes originales, 10 retenidos omitidos,
767 publicados y recibidos en el mismo orden y con los mismos payloads. Se
generaron 354 estados, incluidos espera inicial y cinco segundos finales; todos
tenían targets vacío. Se comprobó WebSocket contra los estados registrados y el
SVG mostró 0/3 sin marcadores, aun recibiendo X/Y/velocidad. El hash del original
se conserva:

`df85b856872ecc9a3325b06639ffcce39c12f602deffe9283d1bba31e6614edf`

La causa comprobada en esta ejecución es el contador inicial cero: el único
contador de la captura es retenido y P0.3 lo omite correctamente. No se inyectó
un contador ficticio. Esto no demuestra que el radar físico detectara cero personas.

| Comportamiento | Evidencia |
| --- | --- |
| X/Y asíncronos | Prueba de caracterización: X antiguo e Y nuevo se combinan si ambos tienen edad <=2 s; no se exige una trama conjunta. |
| Caducidad | A 2 s exactos el campo aún vale; por encima de 2 s cualquier eje vencido elimina el slot. La salida se muestrea cada segundo. |
| NaN | Se ignora sin invalidar ni refrescar el último valor finito. Se conserva hasta caducar. Comprobado con pruebas y fixture. |
| Velocidad ausente/vencida | El consumidor genera None y el puente lo convierte en 0.0; no se distingue desconocida de inmóvil. |
| Contador no cero | Su edad no se utiliza; no limita el número de slots. Se observaron más slots que el contador vigente. |
| Contador cero | Borra los campos y bloquea objetivos hasta un nuevo contador no cero. |
| Slots no consecutivos | Se conservan 1 y 3; no se reasignan identidades. |
| Sin telemetría | El puente sigue enviando estados vacíos con timestamps nuevos. El frontend puede indicar conectado/en directo aunque no haya medidas frescas. |
| Desconexión real del consumidor | Prueba MQTT: los ejes caducan; health sigue 200. Tras reconectar y refrescar X/Y reaparece el slot sin contador nuevo. |
| Evento histórico de desconexión | No desconecta al backend ni acredita una caída del ESP32; permanece como evento de evidencia. |
| Payload binario de fixture | UnicodeDecodeError termina el hilo Paho: 20 recibidos frente a 24 publicados, un error. El puente sigue vivo y health responde 200. |
| QoS | Replay publica QoS 1; el consumidor existente suscribe QoS 0, por lo que recibe QoS 0. No se ha cambiado esa suscripción. |

**Fixtures sintéticas:** las pruebas de integración observaron estados de dos y
tres slots. El muestreo a 1 Hz depende de la fase respecto al replay: en un arranque
manual se observaron como máximo dos, aunque otra ejecución capturó tres. No se
promete igualdad de la salida del backend por tener un replay determinista: el
backend usa su propio reloj, tick y cola WebSocket de último estado.

Se añadió `display_hold.synthetic.mqtt.jsonl`, auxiliar de visualización: repite
valores finitos de la fixture original para mantener fases de uno, dos y tres
slots. No es evidencia física ni modifica las fixtures P0.3. Su revisión visual
adicional quedó pendiente por un bloqueo de cuota en la revisión automática del
navegador. Las capturas ya obtenidas muestran la sesión física sin objetivos y
un slot sintético; no se presentan como fotografías de tres objetivos simultáneos.

## Pruebas reproducibles

```powershell
.\.venv-p0\Scripts\python.exe -m pytest -q
$env:SMARTSPACE_TEST_MOSQUITTO = $mosquitto
$env:SMARTSPACE_REPLAY_CAPTURE = (Resolve-Path .\captures\ld2450-2026-11-24-01.mqtt.jsonl).Path
.\.venv-p0\Scripts\python.exe -m pytest -q -m mqtt
node --test tests/frontend.test.mjs
git diff --check
```

Las nuevas pruebas locales están en test_current_mqtt_characterization.py;
test_replay_app_integration.py añade broker real, FastAPI y WebSocket. La selección
por defecto sigue excluyendo MQTT/hardware. La prueba del binario espera la muerte
del hilo y silencia únicamente ese aviso de pytest en ese caso; el error queda
registrado y se verifica explícitamente. Persiste el aviso previo Starlette/HTTPX.

Resultado final: 134 pruebas locales pasan (7 MQTT excluidas), 7 pruebas MQTT
pasan y 4 JavaScript pasan. La ejecución MQTT mostró avisos de caché por permisos
del entorno, no fallos de los casos. Al renovar permisos se verificó la suite
local sin esos avisos. Se corrigió únicamente el reloj de una prueba nueva para
no depender de la resolución UTC de Windows. Se observaron 319 tramas WebSocket
en la ejecución física reproducida, todas presentes en states.jsonl.

## Propuesta P1.1b, sin implementar

1. Definir estados distintos para contador desconocido, cero medido y dato antiguo;
   resolver el bloqueo por contador ausente sin reutilizar retenidos como frescos.
2. Aislar errores de decodificación/validación y propagar salud real del hilo MQTT,
   conectividad y última medida hasta API/UI.
3. Definir invalidación por NaN, edad por campo y política explícita para asociar
   ejes asíncronos; conservar velocidad desconocida como tal.
4. Decidir la autoridad del contador frente a los slots y el comportamiento al
   desconectar/reconectar. Mantener slot separado de identidad.
5. Hacer comprobable el reloj de normalización y muestreo; distinguir fase de
   adquisición, tick del backend y descarte del WebSocket. Acelerar MQTT no acelera
   el TTL actual, por lo que 100x sirve para transporte, no para validar caducidad.

Archivos P1.1a: nuevo replay_app.py, dos módulos de pruebas, fixture auxiliar y esta
guía; cambios de conexión/instrumentación en radar_bridge.py, selección/rutas en
main.py y contexto visual en index.html, app.js y styles.css. mqtt_consumer.py,
prepare_frame y process_frame no se refactorizan. Firmware, topics, captura y
reproductor P0.3 se conservan. La siguiente fase queda detenida.
