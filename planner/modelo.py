"""Modelo de datos + evaluador de costos (replica la simulación de la guía).

Representación interna de una solución ("sol"):
    { id_vehiculo: [ [i, j, k], [m, n], ... ] }
Cada vehículo tiene una lista de VIAJES; cada viaje es una lista de índices de
pedido (1..n). Entre un viaje y el siguiente el vehículo vuelve al depósito
(eso es la parada "DEPOSITO" del plan).

Si en un evento cambian las reglas (ventanas horarias, prioridades, etc.),
el lugar para tocar el costo es Evaluador._calc.
"""
import math

PENAL = 1e6  # penalización por violar capacidad (nunca debería aceptarse)


def _num(x, defecto=None):
    if x is None:
        return defecto
    if isinstance(x, bool):
        return defecto
    if isinstance(x, (int, float)):
        return x
    s = str(x).strip()
    if s == "" or s.lower() in ("null", "none"):
        return defecto
    try:
        f = float(s)
    except ValueError:
        return defecto
    return int(f) if f == int(f) else f


def a_minutos(h, defecto=480):
    if h is None:
        return defecto
    s = str(h).strip()
    if ":" not in s:
        return int(_num(s, defecto))
    hh, mm = s.split(":")[:2]
    return int(hh) * 60 + int(mm)


class Datos:
    def __init__(self, mundo, pedidos, vehiculos):
        self.mundo = mundo

        def g(clave, defecto):
            return _num(mundo.get(clave), defecto)

        # El depósito SIEMPRE se lee del archivo mundo (no asumir (0,0)).
        self.dep = (int(g("deposito_x", 0)), int(g("deposito_y", 0)))
        self.hora_salida = a_minutos(mundo.get("hora_salida"))
        self.t_servicio = g("tiempo_servicio", 5)
        self.t_carga = g("tiempo_carga", 10)
        self.min_cuadra = g("min_por_cuadra", 3)
        self.c_cuadra = g("costo_por_cuadra", 3)
        self.c_vehiculo = g("costo_por_vehiculo", 60)
        self.c_minuto = g("costo_por_minuto_total", 1)
        self.c_falla = g("costo_por_falla", 200)

        # Pedidos: índice interno 1..n  (0 = depósito)
        self.n = len(pedidos)
        self.ids = [p["id"] for p in pedidos]
        self.pos = [self.dep] + [(int(_num(p["x"])), int(_num(p["y"]))) for p in pedidos]
        self.peso = [0] + [(_num(p.get("peso"), 0) or 0) for p in pedidos]
        self.indice = {pid: i + 1 for i, pid in enumerate(self.ids)}
        self.dist = [[abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in self.pos] for a in self.pos]

        # Vehículos (capacidad y costo fijo opcionales)
        self.vids = [v["id"] for v in vehiculos]
        self.cap = {}
        self.fijo = {}
        for v in vehiculos:
            cap = None
            for k in ("capacidad", "capacidad_max", "capacidad_peso", "cap"):
                cap = _num(v.get(k))
                if cap is not None:
                    break
            self.cap[v["id"]] = cap if cap is not None else math.inf
            self.fijo[v["id"]] = _num(v.get("costo_fijo"), self.c_vehiculo)
        self.hay_cap = any(c != math.inf for c in self.cap.values())


class Evaluador:
    def __init__(self, datos):
        self.d = datos

    def _calc(self, sol):
        d = self.d
        D = d.dist
        mc = d.min_cuadra
        ts = d.t_servicio
        dist_tot = 0
        fijo = 0
        usados = 0
        mk = 0
        entregados = 0
        exceso = 0
        for vid, viajes in sol.items():
            dur = 0
            nv = 0
            for t in viajes:
                if not t:
                    continue
                c = D[0][t[0]]
                a = t[0]
                for b in t[1:]:
                    c += D[a][b]
                    a = b
                c += D[a][0]
                dist_tot += c
                dur += c * mc + ts * len(t)
                nv += 1
                entregados += len(t)
                if d.hay_cap:
                    w = 0
                    for i in t:
                        w += d.peso[i]
                    if w > d.cap[vid]:
                        exceso += 1
            if nv:
                usados += 1
                fijo += d.fijo[vid]
                dur += d.t_carga * (nv - 1)
                if dur > mk:
                    mk = dur
        fallas = d.n - entregados
        total = (d.c_cuadra * dist_tot + fijo + d.c_minuto * mk
                 + d.c_falla * fallas + PENAL * exceso)
        return total, dist_tot, usados, fijo, mk, fallas, entregados

    def costo(self, sol):
        return self._calc(sol)[0]

    def desglose(self, sol):
        d = self.d
        total, dist, usados, fijo, mk, fallas, entr = self._calc(sol)
        return (
            "\nCOSTO TOTAL: %g\n"
            "  distancia %d cuadras x %g = %g\n"
            "  vehiculos %d usados (costo fijo) = %g\n"
            "  tiempo %d min x %g = %g\n"
            "  fallas %d x %g = %g\n"
            "  Entregas: %d/%d"
            % (total, dist, d.c_cuadra, d.c_cuadra * dist, usados, fijo,
               mk, d.c_minuto, d.c_minuto * mk, fallas, d.c_falla,
               d.c_falla * fallas, entr, d.n)
        )
