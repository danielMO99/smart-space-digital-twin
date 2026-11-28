# Fixtures sintéticas P0.3

Estos archivos son **datos inventados para pruebas de software**, no grabaciones
del LD2450. Llevan `synthetic` en el nombre, UUID fijo, fecha 2020-01-01 y
`metadata.evidence_kind=synthetic`. No prueban detección física multiobjetivo.
El formato es el mismo JSONL v1 del grabador; no se añaden topics.

- `multi_target.synthetic.mqtt.jsonl`: 31 registros, 26 mensajes, dos retenidos.
  Contador nuevo 0→1→2→3→2→1→0; la fase de dos slots usa 1 y 3. Incluye ejes
  asíncronos/parciales, NaN, timestamps coincidentes, hueco de 3,79 s, payloads
  binarios y vacíos, QoS 0/1/2. Los payloads no numéricos comprueban conservación
  de bytes, no validez de una medida radar. Cierre completo.
- `reconnection.synthetic.mqtt.jsonl`: desconexión del **grabador**, hueco,
  reconexión y nueva entrega retenida; cierre `incomplete`, requiere autorización
  explícita `--allow-incomplete`. No representa una desconexión del ESP32.
- `truncated.synthetic.mqtt.jsonl`: cabecera válida y segunda línea truncada;
  siempre se rechaza antes de conectar, incluso con `--allow-incomplete`.

Los demás casos inválidos se crean en directorios temporales durante los tests.
No editar ni copiar la captura real como fixture del repositorio.

P1.1a añade `display_hold.synthetic.mqtt.jsonl`: 114 registros, 110 mensajes,
20 segundos. Repite valores finitos de la fixture P0.3 para mantener fases
visibles de uno, dos (slots 1 y 3) y tres slots. Es una ayuda visual sintética;
no representa una prueba física ni sustituye las fixtures anteriores.
