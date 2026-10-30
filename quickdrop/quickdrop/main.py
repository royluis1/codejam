"""Uso: python main.py <carpeta_dataset> <plan_salida.json|csv> [segundos]
Ej:  python main.py datos/practica1 plan.json 20"""
import sys

# Funciones de cada módulo del paquete "planner":
from planner.entrada_salida import cargar, escribir_plan  # leer dataset / escribir plan
from planner.solver import resolver                       # busca el mejor plan
from planner.validador import validar                     # chequea que el plan sea válido


def main():
    # Si faltan argumentos, mostramos el modo de uso y salimos.
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    carpeta, salida = sys.argv[1], sys.argv[2]          # carpeta del dataset y archivo de salida
    segundos = float(sys.argv[3]) if len(sys.argv) > 3 else 20  # tiempo que puede pensar el solver

    datos = cargar(carpeta)                              # 1) leer mundo, pedidos y vehículos
    sol, ev = resolver(datos, segundos, verbose=True)    # 2) buscar el plan (sol) y el evaluador (ev)

    errores = validar(sol, datos)                        # 3) un plan inválido vale 0: lo frenamos acá
    if errores:
        print("PLAN INVALIDO:", errores)
        sys.exit(2)

    escribir_plan(sol, datos, salida)                    # 4) escribir el plan en JSON o CSV
    print("Costo estimado:", ev.desglose(sol))           # desglose del costo (igual al del simulador)
    print("Plan escrito en", salida)


if __name__ == "__main__":
    main()
