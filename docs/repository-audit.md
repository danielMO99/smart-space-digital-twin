# Auditoría de consolidación para GitHub

Fecha de cierre: 28-11-2026. Alcance: repositorio local después de P1.2a. **No se han realizado commits, push, cambios del índice ni reescrituras de historial.** Tampoco se han eliminado archivos, modificado código funcional/firmware o alterado capturas originales.

## Resultado ejecutivo

El código necesario para simulación, replay sintético, backend, SVG y diagnóstico está disponible en el árbol de trabajo, pero buena parte aún no está rastreada por Git. Publicar solo los cambios de archivos ya rastreados produciría una versión incompleta: main.py importa módulos nuevos y el firmware necesita los dos headers nuevos. Se propone consolidar explícitamente todo el conjunto funcional y sus pruebas/contratos.

La publicación como **proyecto de laboratorio**, con secretos y datos físicos excluidos, es viable tras revisar los riesgos siguientes. No debe describirse como un despliegue seguro, portable en modo directo o certificado para Raspberry. La auditoría no realiza la publicación ni concede aprobación automática a otros cambios futuros.

Al inicio: 27 archivos rastreados, 59 no rastreados candidatos; 9 archivos rastreados modificados. El índice estaba vacío. Se revisaron git status, diff, inventario no rastreado y 12 commits del historial local accesible. El remoto origin apunta a GitHub y su URL no contiene credenciales incrustadas; no se contactó al remoto ni se comprobó su estado actual. Los cambios funcionales mostrados por git diff pertenecen a incrementos anteriores, no a esta auditoría.

## Clasificación y lista de inclusión

La lista exhaustiva de archivos propuestos está en **[publication-files.txt](publication-files.txt)**: rutas relativas, una por línea, utilizable con `git add --pathspec-from-file`. Incluye archivos ya rastreados y nuevos, excluyendo lo ignorado. Debe revisarse de nuevo si se cambia el árbol después de esta auditoría; no utilizar `git add .` como sustituto de esa lista.

| Clase | Archivos o familias que se incluyen | Observaciones |
|---|---|---|
| Código backend | backend/app/*.py | main, adquisición legacy/frames, consumidor, puente y diagnóstico; conservar todos juntos |
| Herramientas | mqtt_capture/*.py | Grabación, importación, validación, replay, broker aislado, referencias virtuales y diagnóstico |
| Simulador | simulator/simulate_radar.py | Fuente independiente del radar |
| Frontend | frontend/index.html, css/styles.css, js/app.js y geometry.mjs | Sin build npm; los cambios previos de replay/velocidad nullable son necesarios |
| Firmware fuente | firmware/esp32_base.yaml, ld2450_report.h y ld2450_report_core.h | Preservar los tres; revisar riesgos de despliegue, no flashear desde esta auditoría |
| Pruebas | tests/*.py, tests/frontend.test.mjs, tests/test_ld2450_report_core.cpp, pytest.ini | No dejar fuera tests/conftest.py: protege las pruebas locales contra conexión accidental |
| Fixtures | tests/fixtures/**/*.synthetic.jsonl y README de fixtures | Datos sintéticos pequeños, incluidos los errores intencionados |
| Contratos | docs/contracts/*.json | Esquemas y ejemplos utilizados también por pruebas |
| Dependencias/configuración | backend/requirements*.txt, constraints-py311-windows.txt, config/room.json | Conservar restricciones de plataforma y un worker; revisar geometría si deja de ser ejemplo genérico |
| Ejemplos sin secretos | firmware/secrets.example.yaml, .env.example | El primero es nuevo y contiene placeholders; el segundo sigue vacío |
| Documentación | README.md, AGENTS.md, docs/*.md, docs/research/*.md | Documentación actual e histórica, con las limitaciones explicadas abajo |
| Repositorio | .gitignore, firmware/.gitignore, LICENSE, firmware/.gitkeep, docker-compose.yml | Los dos últimos placeholders no constituyen funcionalidad; conservar por ahora, no eliminados |

Los imports internos, referencias a los headers y acceso de tests a contratos/fixtures están cubiertos por esta lista. No se detectaron rutas personales codificadas como dependencia de ejecución en backend, herramientas, simulador o tests. Las herramientas externas se seleccionan por argumentos o variables de entorno. Sí existe una dirección MQTT privada fija, detallada más abajo.

## Lista de exclusión

| Excluir de Git | Motivo / tratamiento |
|---|---|
| firmware/secrets.yaml y otras variantes secrets.yaml/yml | Credenciales Wi-Fi locales; conservar en disco, no publicar |
| firmware/esp32_base_backup.yaml y backups/local/bench | Configuración anterior, redundante para reproducir el firmware actual; no eliminarla |
| captures/ld2450-2026-11-24-01.mqtt.jsonl | Captura física: posiciones, tiempos y metadatos del banco |
| captures/ld2450-frequency-v1.jsonl | Captura física de 675 informes |
| captures/ld2450-two-persons-v1.jsonl | Captura física de 674 informes |
| captures/ld2450-controlled-test-v1.jsonl | Captura física de 1180 informes |
| outputs/, work/, artifacts/ y otros JSONL fuera de fixtures | Evidencias derivadas, imports, resultados, capturas de pantalla y herramientas temporales |
| .venv/, .venv-p0/, .venv-*/, entornos y caches | Dependencias instaladas y rutas al intérprete de la máquina original |
| .esphome/, firmware/.esphome/, bin/elf/map generados | Build, almacenamiento local de ESPHome y posibles secretos incorporados |
| .env y .env.* salvo ejemplos | Configuración privada; revisar cualquier ejemplo antes de versionarlo |
| *.key, *.p12, *.pfx | Posibles claves privadas y almacenes de certificados |
| .git/, caches, logs, coberturas y temporales ya ignorados | Metadatos o productos locales, no código fuente |

No se publica ninguna captura física. No se eliminaron ni transformaron sus originales. Publicarlas en el futuro requeriría revisar privacidad, consentimiento/contexto de ocupación, identificadores y metadatos, y definir una distribución de datos separada. No desanonimizar ni presentar las fixtures como observaciones físicas.

## Seguridad y privacidad

**1. Credenciales locales protegidas.** Existe firmware/secrets.yaml con claves Wi-Fi. El YAML principal y el backup usan referencias !secret. No se encontraron contraseñas/keys literales en los YAML versionados revisados ni coincidencias exactas de las credenciales locales en candidatos a publicación, payloads Base64 revisados o blobs del historial local accesible. Tampoco aparecieron patrones de tokens GitHub/AWS o claves privadas en el barrido descrito. No se muestran valores. Esto no prueba ausencia universal de secretos: el escaneo es heurístico, conoce solo las credenciales locales actuales y no inspeccionó ramas/remotos no disponibles.

**2. OTA sin autenticación configurada (riesgo alto de operación).** Tanto el YAML principal como su backup habilitan OTA con plataforma esphome sin contraseña definida. No es una contraseña filtrada: es ausencia de protección configurada. No se ha cambiado por la restricción de no alterar funcionamiento/firmware. Antes de reutilizarlo en una red no aislada, planificar el endurecimiento y validarlo por separado.

**3. MQTT directo sin autenticación/TLS configurados (riesgo de operación).** YAML y consumidor directo usan el banco LAN y puerto sin configuración explícita de usuario/contraseña/TLS. La auditoría no accedió al broker y no puede afirmar cómo está protegido el servidor, la red o sus ACL. El replay sí utiliza un broker temporal propio, loopback, puerto aleatorio y credenciales efímeras. Estas credenciales se crean localmente y no se versionan.

**4. Topología privada y rutas personales (privacidad/reproducibilidad).** Hay una dirección privada fija en backend/app/mqtt_consumer.py y firmware/esp32_base.yaml; aparece también en ejemplos y pruebas de protección del reproductor. No es un token, pero identifica configuración del banco y no es un valor universal. No se modificó código para parametrizarla. Las guías históricas conservan nombre/rutas de usuario y carpetas de trabajo; revisar si ese nivel de identificación es aceptable antes de hacer público el repositorio. El README nuevo evita depender de esas rutas.

**5. Datos físicos.** Las cuatro capturas pueden revelar posiciones, horarios, boot_id/sesiones y comportamiento del espacio aunque no incluyan nombres de personas. Base64 no es anonimización ni cifrado. Se mantienen excluidas. Los informes técnicos agregados se proponen para publicación como documentación experimental, no como un conjunto de verdad de ocupación física.

**6. Historial.** No se encontró exposición de las credenciales actuales en los 12 commits locales revisados. .gitignore no elimina archivos ya rastreados, no borra secretos de commits anteriores y `git add -f` puede saltárselo. Si una revisión posterior identifica un secreto real, parar la publicación y rotarlo antes de decidir cómo tratar su historial; aquí no se reescribió nada.

## Revisión de capturas y fixtures

Las cuatro capturas se analizaron sin modificarlas. La captura antigua contiene 777 mensajes MQTT; las nuevas contienen directamente 675, 674 y 1180 informes JSON. Se conservan los hashes de referencia ya documentados. No se encontraron coincidencias de las credenciales locales en sus payloads revisados; esto no convierte las posiciones o identificadores en datos públicos.

Las seis fixtures JSONL sintéticas tienen aproximadamente 1–45 KB y están identificadas por nombre. Se revisó también Base64 de los mensajes. Se propone conservarlas, incluidas `scenarios.synthetic.jsonl`, mensajes inválidos, NaN, bytes no UTF-8 y `truncated.synthetic.mqtt.jsonl`: su JSON truncado en la segunda línea es **intencionado**, necesario para las pruebas negativas. El grabador/reproductor y los tests existentes justifican estos archivos; no deben limpiarse como si fueran capturas corruptas accidentales.

## .gitignore: cambios aplicados

Se conserva el archivo existente y se añaden exclusiones de outputs/work/artifacts, variantes de entornos, .env privados, secrets.yaml/yml, backups/locales/bench de firmware, binarios de firmware y almacenes de claves. Se excluye cualquier JSONL fuera de `tests/fixtures`, con excepción explícita para las fixtures revisadas. Se permiten plantillas `secrets.example.yaml/yml` y .env.example.

Se comprobó que secretos, backup y capturas están ignorados y que las fixtures/plantilla siguen siendo candidatas. No hay archivos rastreados que pasen a estar ignorados por estas reglas. Los patrones reducen accidentes; no son una política de prevención de filtraciones completa. No se ha ejecutado `git rm`, ni siquiera con --cached.

## Reproducibilidad y documentación

- **Código consolidado:** main.py depende de módulos que aún estaban sin rastrear; incluirlos todos es obligatorio. El firmware depende de ambos headers. La propuesta de commits mantiene unido el cambio funcional.
- **Instalación:** requisitos y constraints fijan versiones Python para Windows x64/3.11; `pip check` del entorno existente no encontró problemas. Una copia de archivos fuente limpia funciona con ese entorno. No se hizo una instalación desde cero ni se comprobó disponibilidad actual de paquetes en el índice: no se certifica resolución nueva en otro equipo o Linux.
- **Mosquitto:** dependencia externa de las pruebas MQTT, junto a mosquitto_passwd y DLL. No distribuir los binarios extraídos de la carpeta de trabajo del chat. El README pide la ruta de una instalación local y enlaza la preparación ya documentada.
- **ESPHome:** versión de referencia 2026.6.5, entorno independiente, claves locales no incluidas. Se añadió secrets.example.yaml sin tocar el archivo real. No se compiló ni flasheó firmware en esta auditoría.
- **Xtensa:** compilación C++ opcional mediante SMARTSPACE_XTENSA_CXX. Ausente en un clon normal: omisión explícita, no fallo de pruebas funcionales.
- **Capturas reales:** exclusión deliberada. Las pruebas opcionales usan SMARTSPACE_REPLAY_CAPTURE y SMARTSPACE_FRAME_CAPTURES. El clon público reproduce escenarios sintéticos sin ellas, pero no permite reproducir de forma independiente la evidencia física exacta de 2529 informes; publicar el código no equivale a publicar esos datos.
- **Documentación histórica:** rutas absolutas en docs/frame-backend-p11c4.md, frame-capture-replay-p11c3.md, mqtt-capture.md, mqtt-replay.md, normalization-p11b.md, normalization-p11c1.md, phase-2.2.md, replay-app-p11a.md y sensor-health-p12a.md. Son ejemplos del banco original, no requisitos de ejecución. La entrada portable se concentra ahora en README.
- **README corregido:** ya no presenta la integración MQTT como código ajeno a P0; explica frames, replay, diagnóstico, pruebas opcionales y riesgos. Corrige las afirmaciones obsoletas de firmware no cargado/no integrado como estado actual, conservando los informes de cada fase como historia.
- **Arquitectura:** se añade aviso de diseño objetivo/historia a docs/architecture.md. Sus capas de almacenamiento/automatización y la descripción de Raspberry no acreditan implementación o despliegue actual.
- **Redundancias:** .env.example, docker-compose.yml y firmware/.gitkeep vacíos se conservan para no eliminar sin autorización. Docker y carga .env no están implementados. Backend/app/__init__.py vacío es normal y se conserva. El backup YAML queda excluido, no borrado.
- **Pendientes ya conocidos:** warning Starlette/httpx, controles/textos de simulador en directo (P1.3), calibración lateral (P2), precisión física y UART independiente. No se corrigió funcionalidad ni se avanzó de fase.

## Validación de la copia publicable

Se exportaron 86 archivos candidatos iniciales a una carpeta nueva, sin .git, entornos, secretos, backup, capturas reales ni outputs. La auditoría y lista final añaden documentación posteriormente; no cambian código ejecutado.

- Python local: **204 correctas, 2 omitidas, 12 MQTT no seleccionadas**. Omisiones: captura física opcional y compilador Xtensa.
- JavaScript: **5/5 correctas**.
- Se reutilizó el intérprete/paquetes ya instalados desde fuera de la copia. Esto demuestra integridad de archivos fuente y acceso relativo a recursos, **no una instalación virgen**.
- Una ejecución inicial dentro del sandbox quedó sin avanzar y se interrumpió. La repetición fuera del sandbox terminó en 9,18 s, sin fallo reproducido; no se atribuye una causa definitiva ni se cambió lógica para ocultarlo.
- Integración MQTT de la copia: **9 correctas y 3 omitidas** en 31,45 s. Las omisiones requieren capturas físicas locales. Solo broker propio de pruebas y fixtures sintéticas; no producción.

## Propuesta de commits

Se proponen dos commits nuevos, sin reescribir ni fingir commits históricos por cada incremento:

1. `chore(repo): exclude local evidence and add a secrets template` — .gitignore, firmware/.gitignore y firmware/secrets.example.yaml.
2. `feat: consolidate LD2450 acquisition replay and diagnostics through P1.2a` — código, firmware fuente anterior, frontend, herramientas, pruebas, contratos y documentación restantes del manifiesto. Mantenerlos juntos evita commits intermedios con imports o fixtures ausentes.

No se ha ejecutado ninguno. Antes de publicarlos revisar los riesgos OTA/MQTT, la topología/rutas privadas que se conservarían, el diff propuesto y si el proyecto debe ser privado. Endurecer firmware o parametrizar el modo directo sería un cambio funcional separado, fuera de esta auditoría.

## PowerShell: consolidar y publicar posteriormente

**Los siguientes comandos son una propuesta para ejecución manual después de la revisión. No se han ejecutado git add, commit, switch, fetch ni push en esta auditoría.** Utilizar desde la raíz del repositorio. Detenerse ante cualquier resultado inesperado; no usar reset, clean, add -f ni push --force.

Comprobación previa, sin mostrar valores de secretos:

```powershell
$ErrorActionPreference = 'Stop'
$repo = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Ejecutar desde el repositorio' }
Set-Location -LiteralPath $repo
git status --short
git diff --stat
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar errores del diff' }
$staged = @(git diff --cached --name-only)
if ($staged.Count -ne 0) { throw 'Ya existe contenido en el indice: revisarlo antes de continuar' }
$files = @(Get-Content -LiteralPath docs/publication-files.txt | Where-Object { $_.Trim() })
foreach ($file in $files) {
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Falta el archivo: $file" }
  git check-ignore --quiet -- $file
  if ($LASTEXITCODE -eq 0) { throw "Candidato ignorado: $file" }
  if ($LASTEXITCODE -gt 1) { throw 'Fallo al comprobar exclusiones' }
}
git check-ignore -- firmware/secrets.yaml firmware/esp32_base_backup.yaml captures/ld2450-controlled-test-v1.jsonl
$origin = (git remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or $origin -notmatch '^(https://github\.com/|git@github\.com:)') { throw 'Revisar el remoto origin sin publicar credenciales' }
# No imprimir $origin si contiene configuracion privada.
```

Instalar/probar siguiendo el README nuevo. Después, preparar los commits en una rama nueva; **revisar la lista antes de cada commit**:

```powershell
git switch -c consolidate/p12a
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la rama; no sobrescribir una existente' }
git add -- .gitignore firmware/.gitignore firmware/secrets.example.yaml
if ($LASTEXITCODE -ne 0) { throw 'Fallo al preparar exclusiones' }
git diff --cached --stat
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar el contenido preparado' }
# Revisar estos tres archivos antes de ejecutar la siguiente linea.
git commit -m "chore(repo): exclude local evidence and add a secrets template"
if ($LASTEXITCODE -ne 0) { throw 'Commit no realizado' }

git add --pathspec-from-file=docs/publication-files.txt
if ($LASTEXITCODE -ne 0) { throw 'Fallo al preparar la consolidacion' }
$names = @(git diff --cached --name-only)
$forbidden = @($names | Where-Object {
  $_ -match '(^|/)(captures|outputs|work|artifacts|\.esphome|\.venv[^/]*)/' -or
  $_ -match '(^|/)secrets\.(yaml|yml)$|_backup.*\.ya?ml$|\.(key|p12|pfx)$' -or
  ($_ -match '\.jsonl$' -and $_ -notmatch '^tests/fixtures/')
})
if ($forbidden.Count -gt 0) { throw 'Hay archivos excluidos en el indice; revisar sin publicar' }
git diff --cached --stat
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar el diff preparado' }
# Revisar el diff completo localmente sin copiar posibles secretos al chat.
git commit -m "feat: consolidate LD2450 acquisition replay and diagnostics through P1.2a"
if ($LASTEXITCODE -ne 0) { throw 'Commit no realizado' }
git status --short
```

Solo después de revisar los commits, ejecutar las pruebas y confirmar que se acepta el contenido público, publicar la rama; no se fusiona automáticamente en main:

```powershell
git log -2 --oneline
git push --set-upstream origin consolidate/p12a
if ($LASTEXITCODE -ne 0) { throw 'Publicacion fallida; no forzar el push' }
```

El remoto GitHub ya existe localmente; no se crea otro repositorio ni se cambia su visibilidad desde estos comandos. Revisar la rama en GitHub y proponer su integración mediante PR por separado.


## Cierre de auditoría

Manifiesto final: **88 archivos candidatos** (27 ya rastreados y 61 no rastreados), incluidos este informe y la lista de publicación. El índice permanece vacío. Se verificaron sin cambios 57 archivos de código/configuración/pruebas respecto de la copia previa, y los 22 archivos protegidos de firmware/frontend/capturas/fixtures respecto de sus hashes de referencia. No se eliminó el backup ni ningún otro archivo.

Modificados únicamente por esta auditoría: `.gitignore`, `README.md`, `docs/architecture.md`. Nuevos: `firmware/secrets.example.yaml`, `docs/repository-audit.md`, `docs/publication-files.txt`. Ningún cambio funcional, commit, push, despliegue ni avance de fase.

Antes de publicar queda una decisión explícita del propietario sobre la exposición de rutas/topología privadas y la presentación como configuración de laboratorio con OTA/MQTT por endurecer. Los comandos anteriores están preparados para revisión, no ejecutados. La reproducibilidad de instalación completamente nueva permanece sin verificar; la copia de fuentes y sus pruebas sí se han comprobado sin datos privados.
