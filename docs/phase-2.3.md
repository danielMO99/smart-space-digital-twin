# Fase 2.3 — Plano SVG en tiempo real

## Ejecutar (PowerShell, desde la raíz del repositorio)

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Abrir http://localhost:8000. FastAPI sirve HTML en `/` y recursos en `/static`.
No abrir el HTML con file:// ni iniciar otro servidor frontend.
Se conservan `/health`, `/api/room`, `/api/state`, `/ws` y `/docs`.

## Representación

Geometría cargada desde `/api/room`: actualmente 4 × 5 m y radar (2, 0.6) m.
Escala uniforme: 100 unidades SVG por metro y preserveAspectRatio. El origen
está abajo a la izquierda: SVG(x,y) = (100x, 100(longitud−y)). El backend ya
transforma las coordenadas; el cliente no vuelve a rotarlas ni trasladarlas.
Velocidad en m/s: positivo se aleja y negativo se acerca, según el simulador.
El timestamp se muestra exactamente como llega (incluida zona horaria).

Se crean una vez cuadrícula, radar, tres marcadores y tres tarjetas. Cada trama
solo modifica atributos y texto. Los slots ausentes se ocultan y limpian;
los objetivos exteriores conservan sus datos pero no se dibujan dentro del plano.
Los slots no son identidades persistentes. No se dibuja un campo de visión supuesto.

WebSocket usa el host/puerto de la página y ws/wss según HTTP/HTTPS. Reintento
automático de 1 a 10 s. Los datos anteriores se atenúan durante desconexión o
tras max(2 s, 5 intervalos) sin trama válida. Sin simulación, espera datos sin
inventar detecciones. Tramas inválidas se descartan con aviso.

## Verificar

```powershell
python -m pytest -q
node --test tests/frontend.test.mjs
```

Prueba manual: abrir la página, comprobar tres objetivos móviles y timestamps
que cambian cada ~100 ms. Redimensionar: los cuadrados de 1 m permanecen cuadrados.
El radar aparece cerca del borde inferior. Parar FastAPI: indicador desconectado
y datos atenuados. Reiniciar: reconexión y posiciones nuevas sin recargar.
Probar simulación desactivada: conectado esperando datos, sin objetivos falsos.
Para comprobar 0–3 slots o posiciones exteriores, publicar tramas desde un test
mediante StateHub; `/ws` distribuye estado y no acepta adquisición de sensores.

No se han realizado cambios en Raspberry, credenciales ni despliegue remoto.
