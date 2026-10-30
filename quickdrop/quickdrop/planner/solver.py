"""Solver v2: ALNS + recocido simulado con evaluación incremental.

Cómo piensa (así lo resuelven los equipos de ruteo de última milla):
  1) CONSTRUIR  una solución inicial razonable (inserción más barata).
  2) MEJORAR    con recocido simulado: cambios chicos (relocate, swap, 2-opt, or-opt,
                intercambio de colas, premium al frente) y, de vez en cuando, un
                "ruin & recreate" (ALNS): se sacan varios pedidos juntos (al azar,
                cercanos entre sí, los que más cuestan, o una ruta entera) y se
                reinsertan cada uno en su mejor posición. Eso permite saltar de
                una solución con 3 vehículos a una con 2, algo que los cambios
                chicos casi nunca logran.
  3) PULIR      búsqueda local exhaustiva hasta que ningún cambio simple mejore.
  4) REINICIAR  varias corridas con distintos puntos de partida; gana la mejor.

Evaluación incremental: cada cambio solo recalcula los vehículos que tocó
(Estado.prueba / Estado.poner) en vez de simular todo el plan de nuevo, y los
cambios rechazados se deshacen sin copiar nada (las rutas nunca se modifican
en el lugar: siempre se arman listas nuevas).
"""
import math
import random
import time

from .modelo import Evaluador, PENAL

INF = float("inf")


# ======================================================================
# Utilidades sobre soluciones en formato dict {vehiculo: [viaje, viaje]}
# ======================================================================
def copia(sol):
    """Copia profunda de una solución."""
    return {v: [t[:] for t in ts] for v, ts in sol.items()}


def construir(d, ev, k=None):
    """Solución inicial greedy: inserción más barata.
    Premium primero (quedan al inicio de las rutas); el resto del más lejano al
    más cercano al depósito. Cada pedido va donde menos sube el costo total."""
    sol = {v: [] for v in d.vids}
    usables = d.vids if k is None else d.vids[:k]      # k = máximo de vehículos a usar
    orden = sorted(range(1, d.n + 1), key=lambda i: (-d.prem[i], -d.dist[0][i]))
    for p in orden:
        mejor = None
        c_mejor = INF
        for v in usables:
            ts = sol[v]
            for ti in range(len(ts)):
                t = ts[ti]
                for pos in range(len(t) + 1):
                    t.insert(pos, p)
                    c = ev.costo(sol)
                    t.pop(pos)                    # deshacer la prueba
                    if c < c_mejor:
                        c_mejor, mejor = c, (v, ti, pos)
            ts.append([p])                        # viaje nuevo / vehículo nuevo
            c = ev.costo(sol)
            ts.pop()
            if c < c_mejor:
                c_mejor, mejor = c, (v, len(ts), 0)
        if mejor is None or c_mejor >= PENAL:
            continue                              # no entra en ningún vehículo: falla
        v, ti, pos = mejor
        if ti == len(sol[v]):
            sol[v].append([p])
        else:
            sol[v][ti].insert(pos, p)
    return sol


def un_solo_vehiculo(d):
    """Partida alternativa: todo en UN vehículo (vecino más cercano). Obliga al
    recocido a explorar planes con pocos vehículos."""
    pendientes = list(range(1, d.n + 1))
    ruta, actual = [], 0
    while pendientes:
        prox = min(pendientes, key=lambda i: d.dist[actual][i])
        ruta.append(prox)
        pendientes.remove(prox)
        actual = prox
    sol = {v: [] for v in d.vids}
    if ruta and d.vids:
        sol[d.vids[0]] = [ruta]
    return sol


# ======================================================================
# Estado: solución mutable con costo incremental
# ======================================================================
class Estado:
    """Guarda las rutas de cada vehículo y el costo parcial de cada una.
    INVARIANTE: una lista de ruta ya colocada NUNCA se modifica en el lugar;
    para cambiarla se arma una lista nueva y se coloca con poner(). Así
    deshacer un cambio es solo volver a poner la referencia anterior."""

    def __init__(self, d, ev, sol, V=None):
        self.d = d
        self.ev = ev
        self.V = len(d.vids) if V is None else V    # solo se usan los primeros V vehículos
        self.exigir = 0                              # mínimo de vehículos que deben seguir usados
        self.rutas = [[t[:] for t in sol.get(v, []) if t] for v in d.vids[:self.V]]
        self.st = [ev.ruta(v, r) for v, r in zip(d.vids, self.rutas)]

    def usados(self):
        return sum(1 for s in self.st if s[3] > 0)

    def costo(self):
        """Costo total a partir de los costos parciales (igual que Evaluador)."""
        d = self.d
        dist = pm = cnt = fijo = exc = mk = 0
        for s in self.st:
            dist += s[0]
            pm += s[2]
            cnt += s[3]
            fijo += s[4]
            exc += s[5]
            if s[1] > mk:
                mk = s[1]
        return (d.c_cuadra * dist + fijo + d.c_minuto * mk
                + d.c_falla * (d.n - cnt) + d.c_premium * pm + PENAL * exc)

    def poner(self, i, rutas_i):
        """Reemplaza la ruta del vehículo i. Devuelve lo anterior para poder deshacer."""
        viejo = (self.rutas[i], self.st[i])
        r = [t for t in rutas_i if t]             # sin viajes vacíos
        self.rutas[i] = r
        self.st[i] = self.ev.ruta(self.d.vids[i], r)
        return viejo

    def restaurar(self, i, viejo):
        self.rutas[i], self.st[i] = viejo

    def prueba(self, i, rutas_i):
        """Costo total SI el vehículo i tuviera rutas_i (sin cambiar el estado)."""
        viejo = self.poner(i, rutas_i)
        c = self.costo()
        self.restaurar(i, viejo)
        return c

    def foto(self):
        """Copia barata del estado (las rutas son inmutables, alcanza con copiar las listas)."""
        return (list(self.rutas), list(self.st))

    def volver(self, foto):
        self.rutas, self.st = list(foto[0]), list(foto[1])

    def a_dict(self):
        sol = {v: [] for v in self.d.vids}
        for v, r in zip(self.d.vids, self.rutas):
            sol[v] = [t[:] for t in r]
        return sol


# ======================================================================
# Cambios chicos (vecindario)
# ======================================================================
def _ubicaciones(est):
    """Todas las posiciones ocupadas: (vehículo, nº de viaje, posición en el viaje)."""
    return [(i, ti, k) for i, r in enumerate(est.rutas)
            for ti, t in enumerate(r) for k in range(len(t))]


def particion_angular(d, k):
    """Partida para exactamente k vehículos: ordena los pedidos por ángulo alrededor
    del depósito (con una rotación al azar de corte no necesaria: se corta en k
    sectores de igual cantidad) y cada sector se ordena por vecino más cercano.
    Da un reparto geográficamente prolijo, mucho mejor que dejar todo en un vehículo."""
    dx, dy = d.dep
    pedidos = sorted(range(1, d.n + 1),
                     key=lambda i: (math.atan2(d.pos[i][1] - dy, d.pos[i][0] - dx), d.dist[0][i]))
    sol = {v: [] for v in d.vids}
    k = max(1, min(k, d.n, len(d.vids)))
    for g in range(k):
        grupo = pedidos[g * d.n // k:(g + 1) * d.n // k]
        ruta, actual = [], 0
        while grupo:
            prox = min(grupo, key=lambda i: d.dist[actual][i])
            ruta.append(prox)
            grupo.remove(prox)
            actual = prox
        if ruta:
            sol[d.vids[g]] = [ruta]
    return sol


def _insertar(R, items, rng, hay_cap):
    """Inserta 'items' en un lugar al azar de la ruta R (lista de viajes).
    Un viaje nuevo solo tiene sentido si hay capacidad (o si R está vacía)."""
    n = len(R)
    k = rng.randrange(n + (1 if (hay_cap or n == 0) else 0))
    if k == n:
        R.append(list(items))
    else:
        t = R[k]
        pos = rng.randint(0, len(t))
        t[pos:pos] = items


def _vehiculo_destino(est, rng, origen):
    """Elige a qué vehículo mandar un pedido: casi siempre uno ya usado,
    a veces cualquiera (así se pueden abrir vehículos nuevos)."""
    if rng.random() < 0.85:
        usados = [x for x in range(est.V) if est.st[x][3] > 0 or x == origen]
        return rng.choice(usados)
    return rng.randrange(est.V)


def propuesta(est, rng):
    """Arma UN cambio al azar. Devuelve {vehículo: nuevas_rutas} o None.
    No toca el estado: solo copia las rutas que cambian."""
    d = est.d
    ub = _ubicaciones(est)
    if not ub:
        return None
    cop = {}

    def get(i):                                   # copia (una sola vez) de la ruta i
        if i not in cop:
            cop[i] = [t[:] for t in est.rutas[i]]
        return cop[i]

    r = rng.random()
    if d.hay_prem and r < 0.08:
        # Premium al frente: lo pasa al inicio de la ruta de algún vehículo
        premium = [x for x in ub if d.prem[est.rutas[x[0]][x[1]][x[2]]]]
        if not premium:
            return None
        i, ti, k = rng.choice(premium)
        p = get(i)[ti].pop(k)
        j = _vehiculo_destino(est, rng, i)
        Rj = get(j)
        if Rj:
            Rj[0].insert(0, p)
        else:
            Rj.append([p])
    elif r < 0.38:
        # RELOCATE: saca un pedido y lo pone en otro lugar
        i, ti, k = rng.choice(ub)
        p = get(i)[ti].pop(k)
        j = _vehiculo_destino(est, rng, i)
        _insertar(get(j), [p], rng, d.hay_cap)
    elif r < 0.52:
        # SWAP: intercambia dos pedidos
        if len(ub) < 2:
            return None
        a, b = rng.sample(ub, 2)
        ta, tb = get(a[0])[a[1]], get(b[0])[b[1]]
        ta[a[2]], tb[b[2]] = tb[b[2]], ta[a[2]]
    elif r < 0.68:
        # 2-OPT: da vuelta un tramo de un viaje (desenreda cruces)
        i, ti, k = rng.choice(ub)
        t = get(i)[ti]
        if len(t) < 2:
            return None
        j = rng.randrange(len(t))
        if j == k:
            return None
        a, b = (k, j) if k < j else (j, k)
        t[a:b + 1] = t[a:b + 1][::-1]
    elif r < 0.82:
        # OR-OPT: mueve un tramo de 1 a 3 pedidos seguidos (a veces invertido)
        i, ti, k = rng.choice(ub)
        t = get(i)[ti]
        seg = t[k:k + rng.randint(1, 3)]
        del t[k:k + len(seg)]
        if rng.random() < 0.5:
            seg.reverse()
        j = _vehiculo_destino(est, rng, i)
        _insertar(get(j), seg, rng, d.hay_cap)
    else:
        # COLAS (2-opt*): dos viajes intercambian lo que queda después de un corte
        a, b = rng.sample(ub, 2) if len(ub) >= 2 else (None, None)
        if a is None or (a[0], a[1]) == (b[0], b[1]):
            return None
        A, B = get(a[0])[a[1]], get(b[0])[b[1]]
        Ra, Rb = get(a[0]), get(b[0])
        Ra[a[1]] = A[:a[2]] + B[b[2]:]
        Rb[b[1]] = B[:b[2]] + A[a[2]:]
    return cop


# ======================================================================
# ALNS: ruin & recreate
# ======================================================================
def mejor_insercion(est, p):
    """Mejor lugar (en cualquier vehículo y viaje) para el pedido p.
    Devuelve (costo_total_resultante, vehículo, nuevas_rutas_del_vehículo)."""
    mejor = (INF, None, None)
    d = est.d
    for i in range(est.V):
        ts = est.rutas[i]
        for ti in range(len(ts)):
            t = ts[ti]
            for k in range(len(t) + 1):
                nr = ts[:ti] + [t[:k] + [p] + t[k:]] + ts[ti + 1:]
                c = est.prueba(i, nr)
                if c < mejor[0]:
                    mejor = (c, i, nr)
        if not ts or d.hay_cap:                   # viaje nuevo solo si tiene sentido
            nr = ts + [[p]]
            c = est.prueba(i, nr)
            if c < mejor[0]:
                mejor = (c, i, nr)
    return mejor


def ruina_recreacion(est, rng):
    """Saca varios pedidos de golpe y los reinserta uno por uno en su mejor lugar."""
    d = est.d
    asignados = [x for r in est.rutas for t in r for x in t]
    if not asignados:
        return
    q = min(len(asignados), rng.randint(2, max(3, min(10, d.n // 4))))
    tipo = rng.random()
    if tipo < 0.30:
        # al azar
        quitar = set(rng.sample(asignados, q))
    elif tipo < 0.65:
        # relacionados: un pedido y los más cercanos a él (se reacomodan como grupo)
        s = rng.choice(asignados)
        orden = sorted(asignados, key=lambda x: d.dist[s][x] + rng.random() * 2)
        quitar = set(orden[:q])
    elif tipo < 0.85:
        # los que más cuestan: los que más bajan el costo al sacarlos (con algo de azar)
        ganancias = []
        c0 = est.costo()
        for i, r in enumerate(est.rutas):
            for ti, t in enumerate(r):
                for k, x in enumerate(t):
                    nt = t[:k] + t[k + 1:]
                    nr = r[:ti] + [nt] + r[ti + 1:]
                    ganancias.append((c0 - est.prueba(i, nr), x))
        ganancias.sort(reverse=True)
        quitar = set()
        while len(quitar) < q and ganancias:
            idx = int(len(ganancias) * rng.random() ** 3)
            quitar.add(ganancias.pop(idx)[1])
    else:
        # una ruta entera (ayuda a eliminar un vehículo)
        usados = [i for i in range(est.V) if est.st[i][3] > 0]
        if len(usados) > 1:
            i = rng.choice(usados)
            quitar = {x for t in est.rutas[i] for x in t}
        else:
            quitar = set(rng.sample(asignados, q))

    # Ruina: sacar los pedidos
    for i in range(est.V):
        if any(x in quitar for t in est.rutas[i] for x in t):
            est.poner(i, [[x for x in t if x not in quitar] for t in est.rutas[i]])

    # Recreación: reinsertar en la mejor posición (incluye pedidos que estaban sin asignar)
    presentes = {x for r in est.rutas for t in r for x in t}
    pendientes = [p for p in range(1, d.n + 1) if p not in presentes]
    rng.shuffle(pendientes)
    for p in pendientes:
        c_sin = est.costo()
        c, i, nr = mejor_insercion(est, p)
        if i is not None and c < c_sin:           # solo si conviene más que dejarlo fallar
            est.poner(i, nr)


# ======================================================================
# Recocido simulado
# ======================================================================
def recocido(est, rng, segundos, factor_T, verbose, prob_rr=0.002):
    """Mejora 'est' durante 'segundos'. Acepta cambios que mejoran siempre, y los
    que empeoran con probabilidad exp(-aumento/T); T baja con el tiempo.
    Con probabilidad prob_rr, en vez de un cambio chico hace un ruin & recreate."""
    t0 = time.time()
    c_act = est.costo()
    c_mej, foto_mej = c_act, est.foto()
    T0 = max(2.0, c_act * factor_T)
    Tf = 0.05
    T = T0
    it = 0
    ultimo = t0
    while True:
        if it & 255 == 0:                         # mirar el reloj de vez en cuando
            ahora = time.time()
            frac = (ahora - t0) / segundos if segundos > 0 else 1
            if frac >= 1:
                break
            T = T0 * (Tf / T0) ** frac            # enfriamiento exponencial
            if verbose and ahora - ultimo >= 2:
                ultimo = ahora
                print("  [%4.1fs] iter %d  mejor %g" % (ahora - t0, it, c_mej))
        it += 1

        if rng.random() < prob_rr:
            foto = est.foto()
            ruina_recreacion(est, rng)
            c = est.costo()
            delta = c - c_act
            if est.usados() < est.exigir:
                est.volver(foto)
            elif delta <= 0 or rng.random() < math.exp(-delta / T):
                c_act = c
                if c < c_mej - 1e-9:
                    c_mej, foto_mej = c, est.foto()
            else:
                est.volver(foto)
            continue

        cam = propuesta(est, rng)
        if not cam:
            continue
        viejos = {i: est.poner(i, r) for i, r in cam.items()}
        c = est.costo()
        delta = c - c_act
        if est.exigir and est.usados() < est.exigir:
            for i, v in viejos.items():           # no se puede dejar vacío un vehículo exigido
                est.restaurar(i, v)
        elif delta <= 0 or rng.random() < math.exp(-delta / T):
            c_act = c
            if c < c_mej - 1e-9:
                c_mej, foto_mej = c, est.foto()
        else:
            for i, v in viejos.items():           # deshacer
                est.restaurar(i, v)
    est.volver(foto_mej)
    if verbose:
        print("  iteraciones: %d" % it)


# ======================================================================
# Búsqueda local exhaustiva (pulido final)
# ======================================================================
def pulir(est):
    """Aplica cambios que mejoran hasta que ninguno lo hace:
    1) cada pedido a su mejor posición posible, 2) 2-opt completo en cada viaje."""
    d = est.d
    mejora = True
    while mejora:
        mejora = False
        for p in range(1, d.n + 1):
            loc = None
            for i, r in enumerate(est.rutas):
                for ti, t in enumerate(r):
                    if p in t:
                        loc = (i, ti, t.index(p))
            c0 = est.costo()
            viejo = None
            if loc:
                i, ti, k = loc
                r = est.rutas[i]
                viejo = (i, est.poner(i, r[:ti] + [r[ti][:k] + r[ti][k + 1:]] + r[ti + 1:]))
            c, j, nr = mejor_insercion(est, p)
            if j is not None and c < c0 - 1e-9:
                est.poner(j, nr)
                mejora = True
            elif viejo:
                est.restaurar(*viejo)
        for i in range(est.V):
            for ti in range(len(est.rutas[i])):
                n = len(est.rutas[i][ti])
                for a in range(n - 1):
                    for b in range(a + 1, n):
                        r = est.rutas[i]
                        t = r[ti]
                        nt = t[:a] + t[a:b + 1][::-1] + t[b + 1:]
                        nr = r[:ti] + [nt] + r[ti + 1:]
                        if est.prueba(i, nr) < est.costo() - 1e-9:
                            est.poner(i, nr)
                            mejora = True


# ======================================================================
# Función principal (la que llama main.py)
# ======================================================================
def _correr(d, ev, inicio, k_exigido, rng, segundos, factor_T, verbose):
    """Una corrida completa: recocido/ALNS + pulido. Devuelve (costo_oficial, solución)."""
    est = Estado(d, ev, inicio)
    est.exigir = k_exigido            # no dejar vacío ningún vehículo de los k pedidos
    recocido(est, rng, segundos, factor_T, verbose)
    pulir(est)
    sol = est.a_dict()
    return ev.costo(sol), sol         # costo "oficial" (no el incremental)


def resolver(datos, segundos=20, verbose=False, semilla=1):
    """Estrategia (la clave es decidir CUÁNTOS vehículos usar):
      Fase 1: para cada cantidad k de vehículos (1..V) se busca el mejor plan que usa
              exactamente k, partiendo de un reparto por sectores alrededor del depósito.
              (Sin esto el recocido tiende a juntar todo en un solo vehículo.)
      Fase 2: con las 2 mejores cantidades se invierte el resto del tiempo con más
              corridas: otras semillas y reinicios desde la mejor solución encontrada.
    Devuelve la mejor solución y el evaluador para mostrar el desglose del costo."""
    d = datos
    ev = Evaluador(d)
    if d.n == 0 or not d.vids:
        return {v: [] for v in d.vids}, ev
    t_ini = time.time()
    V = min(len(d.vids), d.n)
    base = construir(d, ev)
    mejor, c_mejor = base, ev.costo(base)
    if verbose:
        print("Costo inicial (greedy):", c_mejor)

    # Con capacidad, un reparto angular puede romperla: se parte del greedy limitado a k
    def inicio_k(k):
        return construir(d, ev, k) if d.hay_cap else particion_angular(d, k)

    # ---- Fase 1: una corrida por cada cantidad de vehículos ----
    presupuesto1 = segundos * 0.40
    por_k = presupuesto1 / V
    por_k_mejor = {}                  # k -> (costo, solución)
    for k in range(1, V + 1):
        rng = random.Random(semilla * 1000 + k)
        c, sol = _correr(d, ev, inicio_k(k), 0 if d.hay_cap else k, rng, por_k, 0.01, False)
        por_k_mejor[k] = (c, sol)
        if verbose:
            print("  k=%d vehículos -> costo %g" % (k, c))
        if c < c_mejor:
            mejor, c_mejor = sol, c

    # ---- Fase 2: profundizar en las 2 mejores cantidades ----
    top = sorted(por_k_mejor, key=lambda k: por_k_mejor[k][0])[:2]
    ronda = 0
    while True:
        restante = segundos - (time.time() - t_ini)
        if restante < 0.3:
            break
        k = top[ronda % len(top)]
        # El tiempo que queda se reparte entre las corridas que faltan (mín. 1 s cada una)
        t_run = max(1.0, restante / max(1, 2 * len(top) - ronda)) if ronda < 2 * len(top) else restante
        t_run = min(t_run, restante)
        rng = random.Random(semilla * 7919 + ronda)
        if ronda % 2 == 0:
            # reinicio desde la mejor solución de ese k, con temperatura baja
            inicio, factor = por_k_mejor[k][1], 0.005
        else:
            # corrida nueva desde el reparto angular con otra semilla
            inicio, factor = inicio_k(k), 0.02
        c, sol = _correr(d, ev, inicio, 0 if d.hay_cap else k, rng, t_run, factor, False)
        if verbose:
            print("  Fase 2 (k=%d, corrida %d): %g" % (k, ronda + 1, c))
        if c < por_k_mejor[k][0]:
            por_k_mejor[k] = (c, sol)
        if c < c_mejor:
            mejor, c_mejor = sol, c
        ronda += 1
    return mejor, ev
