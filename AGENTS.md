# AGENTS.md

## Objetivo

Mantener Smart Space Digital Twin mediante cambios pequeños, verificables
y compatibles con su arquitectura: ESPHome → MQTT → FastAPI →
WebSocket → frontend 2D.

Distinguir siempre lo implementado de lo descrito como trabajo futuro.

## Mapa del repositorio

- firmware/esp32_base.yaml: ESPHome, UART LD2450 y publicación MQTT.
- simulator/simulate_radar.py: generación de medidas y carga de configuración.
- backend/app/main.py: validación, transformación, StateHub, HTTP y WebSocket.
- config/room.json: geometría, instalación del radar y simulación.
- frontend/: HTML, CSS, JavaScript y plano SVG.
- tests/: pruebas Python y JavaScript.
- docs/: arquitectura, requisitos y procedimientos existentes.

## Arquitectura que debe conservarse

- Mantener ESPHome y el frontend HTML/CSS/JavaScript con SVG.
- Mantener FastAPI como servidor de API y archivos frontend.
- Usar StateHub.publish como entrada al procesamiento.
- Mantener /ws como salida de estados, sin adquisición ni comandos.
- Ejecutar un solo worker mientras el estado resida en memoria.
- Mantener un productor activo por instancia: simulador o MQTT.
- Separar adquisición, normalización, procesamiento y presentación.
- Introducir módulos nuevos solo cuando permitan aislar una responsabilidad
  o probarla sin hardware; evitar reorganizaciones generales.

## Contratos y coordenadas

- Entrada normalizada: coordenadas locales en mm y velocidad en cm/s.
- Salida: coordenadas globales en m y velocidad en m/s.
- Aplicar rotación y traslación una sola vez, en el backend.
- El frontend solo proyecta las coordenadas globales al SVG.
- Mantener slots únicos del 1 al 3; no son identidades de personas.
- Cero objetivos es una medida válida; ausencia de datos es otro estado.
- Una trama inválida no sustituye el último estado válido.
- No recortar puntos exteriores: conservarlos con inside_room=false.
- Verificar unidades, signos, validez y cadencia del firmware instalado.
- No confundir datos retenidos o antiguos con medidas nuevas.
- No asumir coherencia temporal entre entidades MQTT independientes.
- Ampliar fuentes o esquemas mediante cambios explícitos y pruebas.

## Grabación y reproducción MQTT

- Conservar topics, bytes, orden y tiempos de recepción.
- Versionar el formato y usar tiempo monotónico para los intervalos.
- Separar el archivo original de cualquier normalización derivada.
- Mantener grabador y reproductor utilizables sin FastAPI.
- Probar temporización con reloj inyectable.
- Informar de pérdidas, desconexiones, errores de disco y capturas incompletas.
- Reproducir inicialmente en un broker aislado y sin retain.
- No reproducir comandos ni mezclar replay con el radar real.
- Identificar la reproducción en el estado operativo y en la interfaz.
- No aplicar al grabador el descarte de estados del WebSocket.
- Versionar solo fixtures pequeñas y revisadas; excluir capturas locales
  y credenciales del repositorio.

## Verificación

Desde la raíz, con las dependencias de desarrollo instaladas:

    python -m pytest -q
    node --test tests/frontend.test.mjs
    git diff --check

- Añadir pruebas del comportamiento cambiado y de sus errores relevantes.
- Mantener las pruebas unitarias independientes del radar y del broker.
- Separar las pruebas que necesitan MQTT o hardware.
- Para firmware, validar y compilar con una versión conocida de ESPHome.
- Compilar firmware no implica autorización para flashear dispositivos.
- Comprobar en navegador los cambios de interacción o presentación.
- Informar qué se ejecutó, qué falló y qué no pudo verificarse.

## Alcance y entrega

- Respetar cambios ajenos y revisar el diff antes de terminar.
- No introducir frameworks, almacenamiento o servicios adicionales
  salvo que la tarea lo requiera.
- No modificar servicios de Raspberry ni desplegar sin que forme parte
  del encargo.
- Mantener secretos fuera de código, fixtures, capturas y logs.
- Documentar los cambios de configuración, contratos y ejecución.
- Entregar cada incremento con un criterio de aceptación comprobable.