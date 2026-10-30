"""Lectura del dataset (JSON o CSV) y escritura del plan (JSON o CSV)."""
import csv
import json
import os

from .modelo import Datos, _num


def _val(x):
    """Normaliza un valor: vacío/null -> None, '12' -> 12, 'V1' -> 'V1'."""
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        if s == "" or s.lower() in ("null", "none"):
            return None
        n = _num(s)
        return n if n is not None else s
    return x


def _leer(carpeta, nombre):
    j = os.path.join(carpeta, nombre + ".json")
    c = os.path.join(carpeta, nombre + ".csv")
    if os.path.exists(j):
        with open(j, encoding="utf-8-sig") as f:
            return json.load(f)
    if os.path.exists(c):
        with open(c, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    raise FileNotFoundError("No encuentro %s.json ni %s.csv en %s" % (nombre, nombre, carpeta))


def _mundo(obj):
    if isinstance(obj, dict) and isinstance(obj.get("mundo"), dict):
        obj = obj["mundo"]
    if isinstance(obj, list):  # CSV: clave,valor
        obj = {r["clave"].strip(): r["valor"] for r in obj if r.get("clave")}
    return {k: _val(v) for k, v in obj.items()}


def _lista(obj, clave):
    if isinstance(obj, dict):
        obj = obj.get(clave, list(obj.values()))
    return [{k: _val(v) for k, v in fila.items()} for fila in obj]


def cargar(carpeta):
    mundo = _mundo(_leer(carpeta, "mundo"))
    pedidos = _lista(_leer(carpeta, "pedidos"), "pedidos")
    vehiculos = _lista(_leer(carpeta, "vehiculos"), "vehiculos")
    return Datos(mundo, pedidos, vehiculos)


def _paradas(viajes, datos):
    paradas = []
    for t in [t for t in viajes if t]:
        if paradas:
            paradas.append("DEPOSITO")
        paradas.extend(datos.ids[i - 1] for i in t)
    return paradas


def escribir_plan(sol, datos, salida):
    rutas = []
    for vid in datos.vids:  # orden estable
        paradas = _paradas(sol.get(vid, []), datos)
        if paradas:
            rutas.append({"vehiculo": vid, "paradas": paradas})
    if salida.lower().endswith(".csv"):
        with open(salida, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["vehiculo", "parada"])
            for r in rutas:
                for p in r["paradas"]:
                    w.writerow([r["vehiculo"], p])
    else:
        with open(salida, "w", encoding="utf-8") as f:
            json.dump({"rutas": rutas}, f, ensure_ascii=False)
