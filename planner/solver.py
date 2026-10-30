"""Solver: construcción greedy + recocido simulado (simulated annealing).

Decide solo cuántos vehículos usar, cuántos viajes hace cada uno y el orden de
las paradas, minimizando el costo total del Evaluador (distancia + vehículos
usados + makespan + fallas).
"""
import math
import random
import time

from .modelo import Evaluador, PENAL


def copia(sol):
    return {v: [t[:] for t in ts] for v, ts in sol.items()}


def limpiar(sol):
    for v in sol:
        sol[v] = [t for t in sol[v] if t]


def construir(d, ev):
    """Inserción más barata, empezando por los pedidos más lejanos."""
    sol = {v: [] for v in d.vids}
    orden = sorted(range(1, d.n + 1), key=lambda i: -d.dist[0][i])
    for p in orden:
        mejor = None
        c_mejor = math.inf
        for v in d.vids:
            ts = sol[v]
            for ti in range(len(ts)):
                t = ts[ti]
                for pos in range(len(t) + 1):
                    t.insert(pos, p)
                    c = ev.costo(sol)
                    t.pop(pos)
                    if c < c_mejor:
                        c_mejor, mejor = c, (v, ti, pos)
            ts.append([p])  # viaje nuevo (o vehículo nuevo)
            c = ev.costo(sol)
            ts.pop()
            if c < c_mejor:
                c_mejor, mejor = c, (v, len(ts), 0)
        if mejor is None or c_mejor >= PENAL:
            continue  # no entra en ningún vehículo: queda como falla
        v, ti, pos = mejor
        if ti == len(sol[v]):
            sol[v].append([p])
        else:
            sol[v][ti].insert(pos, p)
    return sol


def _insertar(s, items, rng, vids):
    v = rng.choice(vids)
    ts = s[v]
    k = rng.randrange(len(ts) + 1)
    if k == len(ts):
        ts.append(list(items))
    else:
        t = ts[k]
        pos = rng.randint(0, len(t))
        t[pos:pos] = items


def vecino(sol, rng, d):
    s = copia(sol)
    pos = [(v, ti, i) for v, ts in s.items() for ti, t in enumerate(ts) for i in range(len(t))]
    if not pos:
        return None
    r = rng.random()
    if r < 0.40:  # relocate
        v, ti, i = rng.choice(pos)
        p = s[v][ti].pop(i)
        _insertar(s, [p], rng, d.vids)
    elif r < 0.60:  # swap
        if len(pos) < 2:
            return None
        a, b = rng.sample(pos, 2)
        ta, tb = s[a[0]][a[1]], s[b[0]][b[1]]
        ta[a[2]], tb[b[2]] = tb[b[2]], ta[a[2]]
    elif r < 0.80:  # 2-opt dentro de un viaje
        v, ti, i = rng.choice(pos)
        t = s[v][ti]
        if len(t) < 2:
            return None
        j = rng.randrange(len(t))
        if i == j:
            return None
        if i > j:
            i, j = j, i
        t[i:j + 1] = t[i:j + 1][::-1]
    elif r < 0.95:  # mover un segmento de 1-3 pedidos
        v, ti, i = rng.choice(pos)
        t = s[v][ti]
        seg = t[i:i + rng.randint(1, 3)]
        del t[i:i + len(seg)]
        if rng.random() < 0.5:
            seg.reverse()
        _insertar(s, seg, rng, d.vids)
    else:  # intercambiar las rutas de dos vehículos
        if len(d.vids) < 2:
            return None
        a, b = rng.sample(d.vids, 2)
        s[a], s[b] = s[b], s[a]
    limpiar(s)
    return s


def recocido(sol, d, ev, rng, segundos, verbose):
    t0 = time.time()
    actual = copia(sol)
    c_act = ev.costo(actual)
    mejor, c_mej = copia(actual), c_act
    T0 = max(2.0, c_act * 0.01)
    Tf = 0.05
    T = T0
    it = 0
    ultimo_print = t0
    while True:
        if it % 256 == 0:
            ahora = time.time()
            frac = (ahora - t0) / segundos if segundos > 0 else 1
            if frac >= 1:
                break
            T = T0 * (Tf / T0) ** frac
            if verbose and ahora - ultimo_print >= 2:
                ultimo_print = ahora
                print("  [%4.1fs] iter %d  mejor %g" % (ahora - t0, it, c_mej))
        it += 1
        cand = vecino(actual, rng, d)
        if cand is None:
            continue
        c = ev.costo(cand)
        delta = c - c_act
        if delta <= 0 or rng.random() < math.exp(-delta / T):
            actual, c_act = cand, c
            if c < c_mej:
                mejor, c_mej = copia(cand), c
    if verbose:
        print("  iteraciones: %d" % it)
    return mejor, c_mej


def resolver(datos, segundos=20, verbose=False, semilla=1):
    ev = Evaluador(datos)
    rng = random.Random(semilla)
    sol = construir(datos, ev)
    if verbose:
        print("Costo inicial (greedy):", ev.costo(sol))
    mejor, c = recocido(sol, datos, ev, rng, segundos, verbose)
    if ev.costo(sol) < c:  # por las dudas
        mejor = sol
    return mejor, ev
