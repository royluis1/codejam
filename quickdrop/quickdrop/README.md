# QuickDrop - plan de reparto (CodeJam UNViMe 2026)

## Uso
    python main.py <carpeta_dataset> <plan_salida.json|csv> [segundos]
    python main.py datos/practica1 plan.json 20

La carpeta del dataset debe tener `mundo`, `pedidos` y `vehiculos` (.json o .csv).
Necesita Python 3.9+, sin dependencias.

## Probar sin internet
    python tools/generar_dataset.py datos/prueba 40 5

## Estructura
- `main.py`                  lee el dataset, resuelve, valida y escribe el plan
- `planner/modelo.py`        datos del mundo + evaluador de costos (aca van las reglas nuevas)
- `planner/entrada_salida.py` leer JSON/CSV y escribir el plan
- `planner/solver.py`        greedy + recocido simulado
- `planner/validador.py`     evita planes invalidos (valen 0)

## Idea de diseño (para el pitch)
1. Construccion greedy: inserta cada pedido (empezando por los mas lejanos) donde menos suba el costo.
2. Recocido simulado: relocate, swap, 2-opt, mover segmentos e intercambiar rutas entre vehiculos.
3. El numero de vehiculos y de viajes (parada DEPOSITO) sale solo de minimizar el costo total.
4. Todo parametro (deposito, costos, tiempos) se lee de `mundo`; nada esta fijo al dataset de practica.
5. Se verifica siempre con el simulador oficial: python -m quickdrop simular <dataset> <plan.json> -detalle
