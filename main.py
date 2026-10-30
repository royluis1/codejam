"""Uso: python main.py <carpeta_dataset> <plan_salida.json|csv> [segundos]
Ej:  python main.py datos/practica1 plan.json 20"""
import sys

from planner.entrada_salida import cargar, escribir_plan
from planner.solver import resolver
from planner.validador import validar


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    carpeta, salida = sys.argv[1], sys.argv[2]
    segundos = float(sys.argv[3]) if len(sys.argv) > 3 else 20
    datos = cargar(carpeta)
    sol, ev = resolver(datos, segundos, verbose=True)
    errores = validar(sol, datos)
    if errores:
        print("PLAN INVALIDO:", errores)
        sys.exit(2)
    escribir_plan(sol, datos, salida)
    print("Costo estimado:", ev.desglose(sol))
    print("Plan escrito en", salida)


if __name__ == "__main__":
    main()
