"""Solver: construcción greedy + recocido simulado (simulated annealing).

Decide solo cuántos vehículos usar, cuántos viajes hace cada uno y el orden de
las paradas, minimizando el costo total del Evaluador
(distancia + vehículos usados + makespan + fallas).

Idea general:
  1) construir() arma una primera solución razonable (greedy).
  2) recocido() la mejora probando cambios al azar; acepta los que mejoran
     y, al principio, también algunos que empeoran (para no quedar atascado).
  3) resolver() repite el paso 2 varias veces con distintas semillas y
     se queda con el mejor resultado.
"""
import math
import random
import time

from .modelo import Evaluador, PENAL


def copia(sol):
    """Copia profunda de una solución (para poder probar cambios sin romper la original)."""
    return {v: [t[:] for t in ts] for v, ts in sol.items()}


def limpiar(sol):
    """Elimina los viajes vacíos que quedan después de mover pedidos."""
    for v in sol:
        sol[v] = [t for t in sol[v] if t]


def construir(d, ev):
    """Solución inicial greedy: inserción más barata.
    Toma los pedidos del más lejano al más cercano al depósito y mete cada uno
    en la posición (de cualquier vehículo/viaje, o en un viaje nuevo) donde
    menos sube el costo total."""
    sol = {v: [] for v in d.vids}
    orden = sorted(range(1, d.n + 1), key=lambda i: -d.dist[0][i])
    for p in orden:
        mejor = None
        c_mejor = math.inf
        for v in d.vids:
            ts = sol[v]
            # Probar insertar p en cada posición de cada viaje existente
            for ti in range(len(ts)):
                t = ts[ti]
                for pos in range(len(t) + 1):
                    t.insert(pos, p)
                    c = ev.costo(sol)
                    t.pop(pos)  # deshacer la prueba
                    if c < c_mejor:
                        c_mejor, mejor = c, (v, ti, pos)
            # Probar abrir un viaje nuevo (o usar un vehículo todavía vacío)
            ts.append([p])
            c = ev.costo(sol)
            ts.pop()
            if c < c_mejor:
                c_mejor, mejor = c, (v, len(ts), 0)
        # Si no entra en ningún lado (ej: pesa más que toda capacidad), queda como falla
        if mejor is None or c_mejor >= PENAL:
            continue
        # Aplicar la mejor inserción encontrada
        v, ti, pos = mejor
        if ti == len(sol[v]):
            sol[v].append([p])
        else:
            sol[v][ti].insert(pos, p)
    return sol


def _insertar(s, items, rng, vids):
    """Inserta una lista de pedidos en un lugar al azar:
    elige un vehículo al azar y luego un viaje (o uno nuevo) y una posición."""
    v = rng.choice(vids)
    ts = s[v]
    k = rng.randrange(len(ts) + 1)   # el último valor significa "viaje nuevo"
    if k == len(ts):
        ts.append(list(items))
    else:
        t = ts[k]
        pos = rng.randint(0, len(t))
        t[pos:pos] = items


def vecino(sol, rng, d):
    """Genera una solución 'vecina': la actual con UN cambio al azar.
    Devuelve None si el cambio elegido no se puede hacer."""
    s = copia(sol)
    # Lista de todas las posiciones ocupadas: (vehículo, nº de viaje, posición en el viaje)
    pos = [(v, ti, i) for v, ts in s.items() for ti, t in enumerate(ts) for i in range(len(t))]
    if not pos:
        return None
    r = rng.random()

    if r < 0.40:
        # RELOCATE: saca un pedido y lo pone en otro lugar al azar
        v, ti, i = rng.choice(pos)
        p = s[v][ti].pop(i)
        _insertar(s, [p], rng, d.vids)

    elif r < 0.60:
        # SWAP: intercambia dos pedidos de lugar
        if len(pos) < 2:
            return None
        a, b = rng.sample(pos, 2)
        ta, tb = s[a[0]][a[1]], s[b[0]][b[1]]
        ta[a[2]], tb[b[2]] = tb[b[2]], ta[a[2]]

    elif r < 0.80:
        # 2-OPT: da vuelta un tramo de un viaje (sirve para desenredar cruces)
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

    elif r < 0.95:
        # OR-OPT: mueve un tramo de 1 a 3 pedidos seguidos a otro lugar (a veces invertido)
        v, ti, i = rng.choice(pos)
        t = s[v][ti]
        seg = t[i:i + rng.randint(1, 3)]
        del t[i:i + len(seg)]
        if rng.random() < 0.5:
            seg.reverse()
        _insertar(s, seg, rng, d.vids)

    else:
        # Intercambia las rutas completas de dos vehículos
        # (útil si los vehículos tienen capacidades o costos distintos)
        if len(d.vids) < 2:
            return None
        a, b = rng.sample(d.vids, 2)
        s[a], s[b] = s[b], s[a]

    limpiar(s)
    return s


def recocido(sol, d, ev, rng, segundos, verbose):
    """Recocido simulado: mejora 'sol' durante 'segundos' segundos.
    Acepta siempre los cambios que mejoran el costo; los que empeoran los acepta
    con una probabilidad que baja con la 'temperatura' T (al principio alta,
    al final casi cero). Así explora mucho al inicio y afina al final."""
    t0 = time.time()
    actual = copia(sol)
    c_act = ev.costo(actual)
    mejor, c_mej = copia(actual), c_act      # mejor solución vista hasta ahora
    T0 = max(2.0, c_act * 0.01)              # temperatura inicial (proporcional al costo)
    Tf = 0.05                                # temperatura final
    T = T0
    it = 0
    ultimo_print = t0
    while True:
        # Cada 256 iteraciones miramos el reloj y actualizamos la temperatura
        # (así no gastamos tiempo llamando a time.time() en cada vuelta)
        if it % 256 == 0:
            ahora = time.time()
            frac = (ahora - t0) / segundos if segundos > 0 else 1
            if frac >= 1:
                break  # se acabó el tiempo
            T = T0 * (Tf / T0) ** frac       # enfriamiento exponencial
            if verbose and ahora - ultimo_print >= 2:
                ultimo_print = ahora
                print("  [%4.1fs] iter %d  mejor %g" % (ahora - t0, it, c_mej))
        it += 1

        cand = vecino(actual, rng, d)        # probar un cambio al azar
        if cand is None:
            continue
        c = ev.costo(cand)
        delta = c - c_act                    # >0 significa que empeora
        # Aceptar si mejora, o con probabilidad exp(-delta/T) si empeora
        if delta <= 0 or rng.random() < math.exp(-delta / T):
            actual, c_act = cand, c
            if c < c_mej:                    # guardar si es el mejor visto
                mejor, c_mej = copia(cand), c
    if verbose:
        print("  iteraciones: %d" % it)
    return mejor, c_mej


def resolver(datos, segundos=20, verbose=False, semilla=1, reinicios=4):
    """Función principal del solver (la que llama main.py).
    Arma la solución greedy y corre el recocido varias veces con distintas
    semillas (el tiempo total se reparte entre las corridas); devuelve la mejor
    solución y el evaluador para poder mostrar el desglose del costo."""
    ev = Evaluador(datos)
    base = construir(datos, ev)
    if verbose:
        print("Costo inicial (greedy):", ev.costo(base))
    mejor, c_mejor = base, ev.costo(base)
    por_corrida = segundos / reinicios
    for k in range(reinicios):
        rng = random.Random(semilla + k)     # semilla distinta en cada corrida
        sol, c = recocido(base, datos, ev, rng, por_corrida, verbose)
        if verbose:
            print("Corrida %d/%d: %g" % (k + 1, reinicios, c))
        if c < c_mejor:
            mejor, c_mejor = sol, c
    return mejor, ev
