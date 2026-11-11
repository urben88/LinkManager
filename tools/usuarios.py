#!/usr/bin/env python3
"""
usuarios.py — gestión de usuarios, roles, 2FA y sesiones de LinkManager.

Se ejecuta DENTRO del contenedor, en el servidor (nunca desde la web: activar
el 2FA o dar el rol admin desde el navegador sería justo lo que haría quien
hubiera robado una contraseña):

  docker exec -it linkmanager_web python3 /app/tools/usuarios.py <orden> ...

Órdenes:
  listar                         usuarios, rol, 2FA y sesiones abiertas
  crear NOMBRE [--rol editor|admin]
  clave NOMBRE                   cambia la contraseña (y cierra sus sesiones)
  rol NOMBRE editor|admin
  activar NOMBRE / desactivar NOMBRE
  2fa NOMBRE                     activa (o rehace) el 2FA: enseña el QR
  quitar-2fa NOMBRE
  sesiones [NOMBRE]              sesiones abiertas
  cerrar-sesiones NOMBRE         cierra todas las sesiones del usuario
  registro [N]                   últimos N accesos (por defecto 40)
"""

import argparse
import getpass
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

import seguridad  # noqa: E402

DB = os.environ.get("LINKMANAGER_DB", "/app/database/database.db")


def fecha(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def pedir_clave():
    while True:
        a = getpass.getpass("Contraseña nueva: ")
        error = seguridad.validar_clave_nueva(a)
        if error:
            print(error)
            continue
        if a != getpass.getpass("Repítela: "):
            print("No coinciden.")
            continue
        return a


def usuario_o_salir(con, nombre):
    u = seguridad.usuario_por_nombre(con, nombre)
    if not u:
        sys.exit(f"No existe el usuario «{nombre}».")
    return u


def mostrar_qr(uri):
    try:
        import segno
        segno.make(uri, error="m").terminal(compact=True)
    except ImportError:
        print("(sin la librería segno no puedo dibujar el QR; usa la clave a mano)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("orden")
    p.add_argument("args", nargs="*")
    p.add_argument("--rol", default="editor", choices=seguridad.ROLES)
    a = p.parse_args()

    con = seguridad.conectar(DB)
    con.executescript(seguridad.ESQUEMA)

    if a.orden == "listar":
        print(f"{'usuario':<16}{'rol':<9}{'2FA':<5}{'activo':<8}sesiones")
        for u in con.execute("SELECT * FROM usuarios ORDER BY nombre"):
            n = len(seguridad.sesiones_usuario(con, u["id"]))
            print(f"{u['nombre']:<16}{u['rol']:<9}{'sí' if u['totp'] else 'no':<5}"
                  f"{'sí' if u['activo'] else 'no':<8}{n}")

    elif a.orden == "crear":
        nombre = a.args[0]
        if seguridad.usuario_por_nombre(con, nombre):
            sys.exit("Ya existe.")
        con.execute("INSERT INTO usuarios (nombre, hash, rol) VALUES (?, ?, ?)",
                    (nombre, generate_password_hash(pedir_clave()), a.rol))
        con.commit()
        print(f"Creado «{nombre}» con rol {a.rol}.")
        if a.rol == "admin":
            print("Para que pueda usar la consola, actívale el 2FA: usuarios.py 2fa", nombre)

    elif a.orden == "clave":
        u = usuario_o_salir(con, a.args[0])
        con.execute("UPDATE usuarios SET hash = ? WHERE id = ?", (generate_password_hash(pedir_clave()), u["id"]))
        con.commit()
        n = seguridad.cerrar_sesiones_usuario(con, u["id"])
        print(f"Contraseña cambiada. Sesiones cerradas: {n}.")
        if os.environ.get("LINKMANAGER_PASSWORD") or os.environ.get("LINKMANAGER_PASSWORD_HASH"):
            print("OJO: LINKMANAGER_PASSWORD está definido en el entorno y volverá a mandar "
                  "en el próximo arranque. Quítalo del .env si quieres usar esta.")

    elif a.orden == "rol":
        u = usuario_o_salir(con, a.args[0])
        if a.args[1] not in seguridad.ROLES:
            sys.exit(f"Rol no válido: {', '.join(seguridad.ROLES)}")
        con.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (a.args[1], u["id"]))
        con.commit()
        print(f"«{u['nombre']}» ahora es {a.args[1]}.")

    elif a.orden in ("activar", "desactivar"):
        u = usuario_o_salir(con, a.args[0])
        con.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (1 if a.orden == "activar" else 0, u["id"]))
        con.commit()
        if a.orden == "desactivar":
            seguridad.cerrar_sesiones_usuario(con, u["id"])
        print("Hecho.")

    elif a.orden == "2fa":
        u = usuario_o_salir(con, a.args[0])
        secreto = seguridad.totp_nuevo_secreto()
        uri = seguridad.totp_uri(secreto, u["nombre"])
        print("\nEscanea este QR con tu app de códigos (Google Authenticator, Aegis, 1Password, Bitwarden…):\n")
        mostrar_qr(uri)
        print(f"\nO mete la clave a mano: {secreto}\n")
        for _ in range(3):
            codigo = input("Escribe el código de 6 cifras que te enseña la app: ").strip()
            if seguridad.totp_paso_valido(secreto, codigo) is not None:
                con.execute("UPDATE usuarios SET totp = ?, totp_paso = 0 WHERE id = ?", (secreto, u["id"]))
                con.commit()
                n = seguridad.cerrar_sesiones_usuario(con, u["id"])
                print(f"2FA activado para «{u['nombre']}». Sesiones cerradas: {n} (vuelve a entrar).")
                return
            print("No coincide. ¿La hora del móvil está bien?")
        sys.exit("No se ha activado nada.")

    elif a.orden == "quitar-2fa":
        u = usuario_o_salir(con, a.args[0])
        con.execute("UPDATE usuarios SET totp = NULL, totp_paso = 0 WHERE id = ?", (u["id"],))
        con.commit()
        con.execute("UPDATE sesiones SET consola_hasta = 0 WHERE usuario_id = ?", (u["id"],))
        con.commit()
        print("2FA quitado. Sin 2FA no hay consola.")

    elif a.orden == "sesiones":
        filtro = a.args[0] if a.args else None
        for u in con.execute("SELECT * FROM usuarios ORDER BY nombre"):
            if filtro and u["nombre"] != filtro:
                continue
            for s in seguridad.sesiones_usuario(con, u["id"]):
                consola = "consola abierta" if s["consola_hasta"] > time.time() else ""
                print(f"{u['nombre']:<14} desde {fecha(s['creada'])}  último uso {fecha(s['ultima'])}  "
                      f"{s['ip'] or '?':<16} {consola}\n{'':<14} {(s['agente'] or '')[:90]}")

    elif a.orden == "cerrar-sesiones":
        u = usuario_o_salir(con, a.args[0])
        print(f"Sesiones cerradas: {seguridad.cerrar_sesiones_usuario(con, u['id'])}.")

    elif a.orden == "registro":
        n = int(a.args[0]) if a.args else 40
        filas = con.execute("SELECT * FROM accesos ORDER BY ts DESC LIMIT ?", (n,)).fetchall()
        for f in reversed(filas):
            print(f"{fecha(f['ts'])}  {'ok ' if f['ok'] else 'MAL'}  {f['evento']:<12} "
                  f"{(f['usuario'] or '')[:14]:<14} {f['ip'] or '':<16} {f['detalle'] or ''}")
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
