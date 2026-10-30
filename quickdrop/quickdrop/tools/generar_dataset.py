"""Genera un dataset de prueba (JSON + CSV) para probar sin internet.
Uso: python tools/generar_dataset.py <carpeta> [pedidos=40] [vehiculos=5] [semilla=1] [dep_x=0] [dep_y=0]
"""
import csv
import json
import os
import random
import sys


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(1)
    # Leer argumentos (con valores por defecto)
    carpeta = a[0]
    n = int(a[1]) if len(a) > 1 else 40
    nv = int(a[2]) if len(a) > 2 else 5
    rng = random.Random(int(a[3]) if len(a) > 3 else 1)  # semilla: mismo número = mismo dataset
    dx = int(a[4]) if len(a) > 4 else 0                  # posición del depósito
    dy = int(a[5]) if len(a) > 5 else 0
    os.makedirs(carpeta, exist_ok=True)

    # Parámetros del mundo (los mismos valores que la guía)
    mundo = {"grilla_ancho": 20, "grilla_alto": 20, "deposito_x": dx, "deposito_y": dy,
             "hora_salida": "08:00", "tiempo_servicio": 5, "tiempo_carga": 10,
             "min_por_cuadra": 3, "costo_por_cuadra": 3, "costo_por_vehiculo": 60,
             "costo_por_minuto_total": 1, "costo_por_falla": 200}
    # Pedidos en posiciones y pesos al azar
    pedidos = [{"id": i, "x": rng.randint(0, 19), "y": rng.randint(0, 19),
                "peso": rng.randint(1, 15)} for i in range(1, n + 1)]
    vehiculos = [{"id": "V%d" % i} for i in range(1, nv + 1)]

    # Escribir los archivos en JSON...
    with open(os.path.join(carpeta, "mundo.json"), "w") as f:
        json.dump(mundo, f, indent=1)
    with open(os.path.join(carpeta, "pedidos.json"), "w") as f:
        json.dump(pedidos, f)
    with open(os.path.join(carpeta, "vehiculos.json"), "w") as f:
        json.dump(vehiculos, f)
    # ...y en CSV (mismos datos)
    with open(os.path.join(carpeta, "mundo.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clave", "valor"])
        w.writerows(mundo.items())
    with open(os.path.join(carpeta, "pedidos.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "x", "y", "peso"])
        w.writerows([[p["id"], p["x"], p["y"], p["peso"]] for p in pedidos])
    with open(os.path.join(carpeta, "vehiculos.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id"])
        w.writerows([[v["id"]] for v in vehiculos])
    print("Dataset generado en", carpeta)


if __name__ == "__main__":
    main()
