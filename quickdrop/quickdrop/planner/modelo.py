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


def es_premium(v):
    """Interpreta el campo 'premium' de un pedido (EVENTO 1).
    Acepta true/false, 1/0, "1"/"0", "si"/"no", "true"/"false", vacío o null."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("1", "true", "si", "sí", "s", "yes", "y", "premium", "x")


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

        # --- EVENTO 1: costo por minuto de espera de los pedidos premium ---
        # No sé el nombre exacto del campo en 'mundo' (lo dice la guía del evento),
        # así que probamos nombres probables y, si no, cualquier clave con "premium".
        self.c_premium = None
        for k in ("costo_por_minuto_premium", "costo_premium_por_minuto", "costo_minuto_premium",
                  "costo_premium", "costo_por_premium"):
            if _num(mundo.get(k)) is not None:
                self.c_premium = _num(mundo.get(k))
                break
        if self.c_premium is None:
            for k, v in mundo.items():
                if "premium" in str(k).lower() and _num(v) is not None:
                    self.c_premium = _num(v)
                    break
        self.premium_en_mundo = self.c_premium is not None
        if self.c_premium is None:
            self.c_premium = 1  # valor provisorio si no se encontró (se avisa en main.py)

        # --- Pedidos ---
        # Usamos índices internos 1..n (el 0 queda reservado para el depósito).
        self.n = len(pedidos)
        self.ids = [p["id"] for p in pedidos]  # ids[i-1] = id original del pedido i
        # pos[0] = depósito, pos[i] = coordenadas (x, y) del pedido i
        self.pos = [self.dep] + [(int(_num(p["x"])), int(_num(p["y"]))) for p in pedidos]
        # peso[i] = peso del pedido i (si falta, 0)
        self.peso = [0] + [(_num(p.get("peso"), 0) or 0) for p in pedidos]
        # prem[i] = 1 si el pedido i es premium (debe recibirse lo antes posible)
        self.prem = [0] + [1 if es_premium(p.get("premium")) else 0 for p in pedidos]
        self.hay_prem = any(self.prem)
        # Avisos para mostrar en consola (los imprime main.py)
        self.avisos = []
        if self.hay_prem and not self.premium_en_mundo:
            self.avisos.append(
                "HAY PEDIDOS PREMIUM pero no encontré el costo premium en 'mundo' "
                "(claves: %s). Uso %s por minuto. Revisá la guía del evento y ajustá "
                "Datos.c_premium en planner/modelo.py." % (sorted(mundo.keys()), self.c_premium))
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

    def ruta(self, vid, viajes):
        """Costo parcial de UN vehículo. Devuelve la tupla:
            (cuadras, minutos_hasta_volver, minutos_premium, pedidos, costo_fijo, excesos)
        Simula parada por parada para conocer la hora de llegada a cada pedido
        (hace falta para el costo de los premium del Evento 1).
        El solver la usa para recalcular SOLO el vehículo que cambió."""
        d = self.d
        D = d.dist
        mc = d.min_cuadra
        ts = d.t_servicio
        prem = d.prem
        tm = 0        # reloj del vehículo (minutos desde la salida)
        nv = 0        # cantidad de viajes
        dist = 0      # cuadras recorridas
        pm = 0        # suma de minutos hasta que EMPIEZA la entrega de cada premium
        cnt = 0       # pedidos entregados
        exceso = 0    # viajes que se pasan de capacidad
        for t in viajes:
            if not t:
                continue
            if nv:
                tm += d.t_carga          # parada DEPOSITO: recarga entre viajes
            a = 0
            for b in t:
                k = D[a][b]
                dist += k
                tm += k * mc             # llegada al pedido b
                if prem[b]:
                    pm += tm             # la entrega empieza al llegar
                tm += ts                 # tiempo de servicio
                a = b
            k = D[a][0]
            dist += k
            tm += k * mc                 # vuelta al depósito
            nv += 1
            cnt += len(t)
            if d.hay_cap:
                w = 0
                for i in t:
                    w += d.peso[i]
                if w > d.cap[vid]:
                    exceso += 1
        fijo = d.fijo[vid] if nv else 0  # solo se paga si el vehículo se usa
        return dist, tm, pm, cnt, fijo, exceso

    def _calc(self, sol):
        """Suma los costos parciales de todos los vehículos y arma el costo total."""
        d = self.d
        dist_tot = fijo = usados = mk = entregados = exceso = pm = 0
        for vid, viajes in sol.items():
            dist, tm, p, cnt, f, ex = self.ruta(vid, viajes)
            dist_tot += dist
            pm += p
            entregados += cnt
            fijo += f
            exceso += ex
            if cnt:
                usados += 1
                if tm > mk:
                    mk = tm              # makespan: el último en volver
        fallas = d.n - entregados        # pedidos que no aparecen en el plan fallan
        total = (d.c_cuadra * dist_tot + fijo + d.c_minuto * mk
                 + d.c_falla * fallas + d.c_premium * pm + PENAL * exceso)
        return total, dist_tot, usados, fijo, mk, fallas, entregados, pm

    def costo(self, sol):
        """Devuelve solo el costo total (lo usa el solver para comparar planes)."""
        return self._calc(sol)[0]

    def desglose(self, sol):
        """Texto con el detalle del costo, con el mismo formato que el simulador."""
        d = self.d
        total, dist, usados, fijo, mk, fallas, entr, pm = self._calc(sol)
        extra = ""
        if d.hay_prem:
            extra = "\n  premium %d min acumulados x %g = %g" % (pm, d.c_premium, d.c_premium * pm)
        return (
            "\nCOSTO TOTAL: %g\n"
            "  distancia %d cuadras x %g = %g\n"
            "  vehiculos %d usados (costo fijo) = %g\n"
            "  tiempo %d min x %g = %g\n"
            "  fallas %d x %g = %g\n"
            "  Entregas: %d/%d"
            % (total, dist, d.c_cuadra, d.c_cuadra * dist, usados, fijo,
               mk, d.c_minuto, d.c_minuto * mk, fallas, d.c_falla,
               d.c_falla * fallas, entr, d.n) + extra
        )
