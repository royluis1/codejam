"""Lectura del dataset (JSON o CSV) y escritura del plan (JSON o CSV)."""
import csv
import json
import os

from .modelo import Datos, _num


def _val(x):
    """Normaliza un valor leído de un archivo:
    vacío/null -> None, "12" -> 12 (número), "V1" -> "V1" (texto)."""
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
    """Lee <nombre>.json si existe; si no, <nombre>.csv.
    Los JSON se devuelven tal cual; los CSV como lista de diccionarios (una fila = un dict)."""
    j = os.path.join(carpeta, nombre + ".json")
    c = os.path.join(carpeta, nombre + ".csv")
    if os.path.exists(j):
        with open(j, encoding="utf-8-sig") as f:   # utf-8-sig ignora el BOM de Windows
            return json.load(f)
    if os.path.exists(c):
        with open(c, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    raise FileNotFoundError("No encuentro %s.json ni %s.csv en %s" % (nombre, nombre, carpeta))


def _mundo(obj):
    """Deja el archivo 'mundo' como un diccionario simple {clave: valor}."""
    # Por si el JSON viene envuelto como {"mundo": {...}}
    if isinstance(obj, dict) and isinstance(obj.get("mundo"), dict):
        obj = obj["mundo"]
    # En CSV viene como filas clave,valor
    if isinstance(obj, list):
        obj = {r["clave"].strip(): r["valor"] for r in obj if r.get("clave")}
    return {k: _val(v) for k, v in obj.items()}


def _lista(obj, clave):
    """Deja pedidos/vehículos como lista de diccionarios normalizados.
    Acepta una lista directa o un dict envuelto, ej: {"pedidos": [...]}."""
    if isinstance(obj, dict):
        obj = obj.get(clave, list(obj.values()))
    return [{k: _val(v) for k, v in fila.items()} for fila in obj]


def cargar(carpeta):
    """Lee los tres archivos del dataset y devuelve un objeto Datos listo para usar.
    Los campos que el programa no conoce simplemente se ignoran."""
    mundo = _mundo(_leer(carpeta, "mundo"))
    pedidos = _lista(_leer(carpeta, "pedidos"), "pedidos")
    vehiculos = _lista(_leer(carpeta, "vehiculos"), "vehiculos")
    return Datos(mundo, pedidos, vehiculos)


def _paradas(viajes, datos):
    """Convierte los viajes de un vehículo en la lista de paradas del plan:
    ids de pedido, con la palabra DEPOSITO entre un viaje y el siguiente."""
    paradas = []
    for t in [t for t in viajes if t]:
        if paradas:
            paradas.append("DEPOSITO")
        paradas.extend(datos.ids[i - 1] for i in t)  # índice interno -> id original
    return paradas


def escribir_plan(sol, datos, salida):
    """Escribe el plan. Si el nombre termina en .csv usa CSV; si no, JSON."""
    rutas = []
    for vid in datos.vids:  # recorremos en el orden original de los vehículos
        paradas = _paradas(sol.get(vid, []), datos)
        if paradas:  # los vehículos sin pedidos no se incluyen (no se usan)
            rutas.append({"vehiculo": vid, "paradas": paradas})

    if salida.lower().endswith(".csv"):
        # Formato CSV: una fila por parada
        with open(salida, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["vehiculo", "parada"])
            for r in rutas:
                for p in r["paradas"]:
                    w.writerow([r["vehiculo"], p])
    else:
        # Formato JSON: {"rutas": [{"vehiculo": ..., "paradas": [...]}, ...]}
        with open(salida, "w", encoding="utf-8") as f:
            json.dump({"rutas": rutas}, f, ensure_ascii=False)
