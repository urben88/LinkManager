#!/usr/bin/env python3
"""
registros.py — fuentes y tokens para el visor de registros de LinkManager.

Los tokens se crean también desde la web (/registros), pero esta CLI sirve
para automatizar el alta de una fuente (por ejemplo, el colector de logs).

  docker exec -it linkmanager_web python3 /app/tools/registros.py crear abogados
  docker exec -it linkmanager_web python3 /app/tools/registros.py listar
  docker exec -it linkmanager_web python3 /app/tools/registros.py borrar abogados

El token solo se muestra al crearlo: en la base queda su hash.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seguridad  # noqa: E402

DB = os.environ.get("LINKMANAGER_DB", "/app/database/database.db")


def fecha(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "nunca"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("orden", choices=("crear", "listar", "borrar"))
    p.add_argument("nombre", nargs="?")
    a = p.parse_args()

    con = seguridad.conectar(DB)
    con.executescript(seguridad.ESQUEMA)

    if a.orden == "listar":
        filas = seguridad.listar_fuentes(con)
        if not filas:
            print("No hay fuentes. Crea una con: registros.py crear NOMBRE")
            return
        print(f"{'ID':>3}  {'NOMBRE':<24} {'TOKEN':<14} {'CREADO':<16} {'ÚLTIMO USO'}")
        for f in filas:
            print(f"{f['id']:>3}  {f['nombre']:<24} {f['prefijo'] + '…':<14} "
                  f"{f['creado'][:16]:<16} {fecha(f['ultimo_uso'])}")
        return

    if not a.nombre:
        sys.exit("Falta el nombre de la fuente.")

    if a.orden == "crear":
        fila, token, error = seguridad.crear_fuente(con, a.nombre)
        if error:
            sys.exit(error)
        print(f"Fuente creada: {fila['nombre']} (id {fila['id']})")
        print(f"Token (solo se muestra ahora): {token}")
        print("Guárdalo en la herramienta; no se puede recuperar después.")
        return

    if a.nombre.isdigit():
        fila = con.execute("SELECT * FROM log_fuentes WHERE id = ?", (int(a.nombre),)).fetchone()
    else:
        fila = con.execute("SELECT * FROM log_fuentes WHERE nombre = ?", (a.nombre,)).fetchone()
    if not fila:
        sys.exit(f"No existe la fuente «{a.nombre}».")
    seguridad.borrar_fuente(con, fila["id"])
    print(f"Fuente eliminada: {fila['nombre']}. Sus registros se conservan.")


if __name__ == "__main__":
    main()
