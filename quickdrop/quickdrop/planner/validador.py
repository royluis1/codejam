"""Chequea que el plan sea válido antes de escribirlo (un plan inválido vale 0)."""


def validar(sol, datos):
    """Devuelve una lista de errores (vacía si el plan es válido).
    Reglas de la guía: no usar vehículos inexistentes, ni pedidos inexistentes,
    ni repetir pedidos. Además chequeamos que no se exceda la capacidad."""
    errores = []
    vistos = set()  # pedidos ya asignados, para detectar repetidos
    for vid, viajes in sol.items():
        if vid not in datos.cap:
            errores.append("vehiculo inexistente: %s" % vid)
            continue
        for t in viajes:
            peso = 0
            for i in t:
                if not (1 <= i <= datos.n):
                    errores.append("pedido inexistente (indice %s)" % i)
                    continue
                if i in vistos:
                    errores.append("pedido repetido: %s" % datos.ids[i - 1])
                vistos.add(i)
                peso += datos.peso[i]
            if peso > datos.cap[vid]:
                errores.append("capacidad excedida en %s (%s > %s)" % (vid, peso, datos.cap[vid]))
    return errores
