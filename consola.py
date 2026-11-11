"""
consola.py — lado del portal de la consola del servidor.

El portal NO ejecuta nada: habla por un socket UNIX con `consola-puente`, que
corre en el host como `urben` y es quien tiene los terminales. Aquí solo se
firman las peticiones y se hace de relé entre el websocket del navegador y el
socket del puente.

Quién llega hasta aquí ya ha pasado por app.py: sesión válida, rol admin, 2FA
verificado hace menos de CONSOLA_DESBLOQUEO_HORAS, Origin correcto y ticket de
un solo uso. Este módulo no se fía de nada de lo que venga del navegador más
allá de «tipo de terminal», «carpeta», teclas y tamaño.
"""

import hashlib
import hmac
import json
import os
import socket
import struct
import threading
import time

ACTIVA = os.environ.get("CONSOLA_ACTIVA", "0").strip().lower() in ("1", "true", "yes")
RUTA_SOCKET = os.environ.get("CONSOLA_SOCKET", "/consola-puente/consola.sock")
RUTA_SECRETO = os.environ.get("CONSOLA_SECRETO_FICHERO", "/run/secrets/consola-puente")


def _secreto():
    try:
        return open(RUTA_SECRETO, "rb").read().strip()
    except OSError:
        return b""


def activa() -> bool:
    return ACTIVA and bool(_secreto())


def _firmar(peticion: dict) -> bytes:
    peticion = {**peticion, "exp": time.time() + 60}
    cuerpo = json.dumps(peticion, sort_keys=True, separators=(",", ":")).encode()
    firma = hmac.new(_secreto(), cuerpo, hashlib.sha256).hexdigest()
    return (json.dumps({"peticion": peticion, "firma": firma}) + "\n").encode()


def _conectar(timeout=5):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(RUTA_SOCKET)
    return s


def _leer_linea(s):
    datos = b""
    while not datos.endswith(b"\n"):
        t = s.recv(4096)
        if not t:
            break
        datos += t
        if len(datos) > 1024 * 1024:
            break
    return json.loads(datos or b'{"ok": false, "error": "sin respuesta"}')


def pedir(peticion: dict, timeout: float = 5) -> dict:
    """Petición simple (listar, crear, cerrar, info). Nunca lanza: devuelve {"ok": False, ...}."""
    try:
        s = _conectar(timeout)
        try:
            s.sendall(_firmar(peticion))
            return _leer_linea(s)
        finally:
            s.close()
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": "No se pudo hablar con la consola del servidor "
                                      f"(¿está en marcha consola-puente?): {type(exc).__name__}"}


# --------------------------------------------------------------------------
#  Consultas de solo lectura para el asistente
#
#  Independientes de la consola: el asistente las puede usar aunque
#  CONSOLA_ACTIVA esté a 0, porque no abren ninguna terminal. Solo hace falta
#  el puente y su secreto. AGENTE_CONSULTAS=0 las apaga.
# --------------------------------------------------------------------------

CONSULTAS_ACTIVAS = os.environ.get("AGENTE_CONSULTAS", "1").strip().lower() not in ("0", "false", "no")


def consultas_disponibles() -> bool:
    return CONSULTAS_ACTIVAS and bool(_secreto())


def consultar(clave: str, usuario: str = "asistente") -> dict:
    """Ejecuta una consulta del catálogo del puente. El puente decide qué existe."""
    if not consultas_disponibles():
        return {"ok": False, "error": "Las consultas al servidor no están disponibles en este portal."}
    return pedir({"op": "info", "consulta": str(clave)[:40], "usuario": usuario}, timeout=60)


# --------------------------------------------------------------------------
#  Relé websocket ↔ puente
# --------------------------------------------------------------------------

def _leer_exacto(s, n):
    datos = b""
    while len(datos) < n:
        t = s.recv(n - len(datos))
        if not t:
            raise ConnectionError
        datos += t
    return datos


def _trama(tipo: bytes, datos: bytes) -> bytes:
    return tipo + struct.pack(">I", len(datos)) + datos


def rele(ws, terminal_id, usuario, cols, rows, sigue_valida):
    """Engancha el websocket a un terminal hasta que uno de los dos se cierre.

    `sigue_valida()` se llama cada poco: si la sesión se cierra o la consola se
    bloquea mientras hay un terminal abierto, se corta la conexión.
    """
    try:
        s = _conectar(timeout=10)
        s.sendall(_firmar({"op": "adjuntar", "id": terminal_id, "usuario": usuario,
                           "cols": cols, "rows": rows}))
        # La respuesta inicial es una línea JSON; después, tramas.
        linea = b""
        while not linea.endswith(b"\n"):
            c = s.recv(1)
            if not c:
                raise ConnectionError
            linea += c
        respuesta = json.loads(linea)
    except (OSError, ValueError, ConnectionError):
        ws.send(json.dumps({"error": "No se pudo conectar con la consola del servidor."}))
        return
    if not respuesta.get("ok"):
        ws.send(json.dumps({"error": respuesta.get("error", "No se pudo abrir la terminal.")}))
        s.close()
        return
    s.settimeout(None)

    fin = threading.Event()

    def del_puente():
        try:
            while not fin.is_set():
                cab = _leer_exacto(s, 5)
                largo = struct.unpack(">I", cab[1:])[0]
                datos = _leer_exacto(s, largo)
                if cab[:1] == b"o":
                    ws.send(datos)                       # binario: salida del terminal
                elif cab[:1] == b"x":
                    ws.send(json.dumps({"fin": json.loads(datos or b"{}")}))
                    break
        except Exception:  # noqa: BLE001 — cualquier corte acaba igual
            pass
        finally:
            fin.set()
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    hilo = threading.Thread(target=del_puente, daemon=True)
    hilo.start()

    ultima_comprobacion = time.time()
    try:
        while not fin.is_set():
            mensaje = ws.receive(timeout=20)
            if time.time() - ultima_comprobacion > 30:
                ultima_comprobacion = time.time()
                if not sigue_valida():
                    ws.send(json.dumps({"error": "La consola se ha bloqueado o la sesión ha caducado."}))
                    break
            if mensaje is None:
                continue
            if isinstance(mensaje, bytes):
                mensaje = mensaje.decode("utf-8", "replace")
            try:
                datos = json.loads(mensaje)
            except ValueError:
                continue
            if "i" in datos:
                entrada = str(datos["i"]).encode("utf-8", "replace")[:65536]
                s.sendall(_trama(b"i", entrada))
            elif "r" in datos:
                try:
                    c, r = int(datos["r"][0]), int(datos["r"][1])
                    s.sendall(_trama(b"r", json.dumps({"cols": c, "rows": r}).encode()))
                except (TypeError, ValueError, IndexError):
                    pass
    except Exception:  # noqa: BLE001 — el navegador se fue
        pass
    finally:
        fin.set()
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        s.close()
