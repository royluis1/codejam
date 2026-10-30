"""Modelo de datos + evaluador de costos (replica la simulación de la guía).

Representación interna de una solución ("sol"):
    { id_vehiculo: [ [i, j, k], [m, n], ... ] }
- Cada vehículo tiene una lista de VIAJES.
- Cada viaje es una lista de índices de pedido (1..n); el 0 es el depósito.
- Entre un viaje y el siguiente el vehículo vuelve al depósito
  (eso es la parada "DEPOSITO" del plan que se escribe al final).

Si en un evento cambian las reglas (ventanas horarias, prioridades, etc.),
el lugar para tocar el costo es Evaluador._calc.
"""
import math

# Penalización enorme por pasarse de capacidad: hace que el solver nunca acepte
# una solución que viola la capacidad de un vehículo.
PENAL = 1e6


def _num(x, defecto=None):
    """Convierte un valor a número (int o float).
    Si está vacío, es null/None o no es un número, devuelve 'defecto'."""
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
    # Si es un entero (ej: "5.0") lo devolvemos como int
    return int(f) if f == int(f) else f


def a_minutos(h, defecto=480):
    """Convierte "HH:MM" a minutos desde las 00:00 (ej: "08:00" -> 480)."""
    if h is None:
        return defecto
    s = str(h).strip()
    if ":" not in s:
        return int(_num(s, defecto))
    hh, mm = s.split(":")[:2]
    return int(hh) * 60 + int(mm)


class Datos:
    """Guarda todo lo que viene del dataset ya procesado y listo para usar."""

    def __init__(self, mundo, pedidos, vehiculos):
        self.mundo = mundo

        def g(clave, defecto):
            # Lee un número del archivo "mundo"; si falta usa el valor por defecto.
            return _num(mundo.get(clave), defecto)

        # --- Parámetros del mundo (SIEMPRE se leen del archivo, nunca fijos) ---
        # El depósito puede cambiar de un dataset a otro: no asumir (0,0).
        self.dep = (int(g("deposito_x", 0)), int(g("deposito_y", 0)))
        self.hora_salida = a_minutos(mundo.get("hora_salida"))  # hora a la que salen los vehículos
        self.t_servicio = g("tiempo_servicio", 5)   # minutos que toma entregar un pedido
        self.t_carga = g("tiempo_carga", 10)        # minutos que toma recargar en el depósito
        self.min_cuadra = g("min_por_cuadra", 3)    # minutos para recorrer una cuadra
        self.c_cuadra = g("costo_por_cuadra", 3)    # costo por cada cuadra recorrida
        self.c_vehiculo = g("costo_por_vehiculo", 60)   # costo fijo por cada vehículo usado
        self.c_minuto = g("costo_por_minuto_total", 1)  # costo por cada minuto de makespan
        self.c_falla = g("costo_por_falla", 200)    # costo por cada pedido no entregado

        # --- Pedidos ---
        # Usamos índices internos 1..n (el 0 queda reservado para el depósito).
        self.n = len(pedidos)
        self.ids = [p["id"] for p in pedidos]  # ids[i-1] = id original del pedido i
        # pos[0] = depósito, pos[i] = coordenadas (x, y) del pedido i
        self.pos = [self.dep] + [(int(_num(p["x"])), int(_num(p["y"]))) for p in pedidos]
        # peso[i] = peso del pedido i (si falta, 0)
        self.peso = [0] + [(_num(p.get("peso"), 0) or 0) for p in pedidos]
        # Para pasar de id original a índice interno
        self.indice = {pid: i + 1 for i, pid in enumerate(self.ids)}
        # Matriz de distancias Manhattan entre todos los puntos (depósito incluido):
        # dist[a][b] = |xa - xb| + |ya - yb|. Se calcula una sola vez.
        self.dist = [[abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in self.pos] for a in self.pos]

        # --- Vehículos ---
        self.vids = [v["id"] for v in vehiculos]
        self.cap = {}    # capacidad de cada vehículo (infinita si no se informa)
        self.fijo = {}   # costo fijo de cada vehículo
        for v in vehiculos:
            cap = None
            # Probamos varios nombres posibles para el campo de capacidad
            for k in ("capacidad", "capacidad_max", "capacidad_peso", "cap"):
                cap = _num(v.get(k))
                if cap is not None:
                    break
            self.cap[v["id"]] = cap if cap is not None else math.inf
            # Si el vehículo trae su propio costo_fijo lo usamos; si no, el del mundo
            self.fijo[v["id"]] = _num(v.get("costo_fijo"), self.c_vehiculo)
        # Solo chequeamos capacidad si algún vehículo realmente tiene límite
        self.hay_cap = any(c != math.inf for c in self.cap.values())


class Evaluador:
    """Calcula el costo de una solución, igual que el simulador oficial."""

    def __init__(self, datos):
        self.d = datos

    def _calc(self, sol):
        """Recorre la solución y devuelve todos los componentes del costo.
        Está escrita de forma compacta porque se llama cientos de miles de veces."""
        d = self.d
        D = d.dist
        mc = d.min_cuadra
        ts = d.t_servicio
        dist_tot = 0     # cuadras recorridas entre todos los vehículos
        fijo = 0         # suma de costos fijos de los vehículos usados
        usados = 0       # cantidad de vehículos usados
        mk = 0           # makespan: minutos hasta que vuelve el último vehículo
        entregados = 0   # pedidos entregados
        exceso = 0       # cantidad de viajes que se pasan de capacidad

        for vid, viajes in sol.items():
            dur = 0   # duración total de este vehículo
            nv = 0    # cantidad de viajes de este vehículo
            for t in viajes:
                if not t:
                    continue
                # Distancia del viaje: depósito -> primer pedido -> ... -> último -> depósito
                c = D[0][t[0]]
                a = t[0]
                for b in t[1:]:
                    c += D[a][b]
                    a = b
                c += D[a][0]
                dist_tot += c
                # Tiempo del viaje: manejar + entregar cada pedido
                dur += c * mc + ts * len(t)
                nv += 1
                entregados += len(t)
                # Chequeo de capacidad (solo si hay límites)
                if d.hay_cap:
                    w = 0
                    for i in t:
                        w += d.peso[i]
                    if w > d.cap[vid]:
                        exceso += 1
            if nv:
                usados += 1
                fijo += d.fijo[vid]
                # Entre viaje y viaje hay una parada DEPOSITO que cuesta tiempo_carga
                dur += d.t_carga * (nv - 1)
                if dur > mk:
                    mk = dur

        fallas = d.n - entregados  # pedidos que no aparecen en el plan fallan
        total = (d.c_cuadra * dist_tot + fijo + d.c_minuto * mk
                 + d.c_falla * fallas + PENAL * exceso)
        return total, dist_tot, usados, fijo, mk, fallas, entregados

    def costo(self, sol):
        """Devuelve solo el costo total (lo usa el solver para comparar planes)."""
        return self._calc(sol)[0]

    def desglose(self, sol):
        """Texto con el detalle del costo, con el mismo formato que el simulador."""
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
