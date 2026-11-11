"""
seguridad.py — usuarios, roles, sesiones, 2FA y límites de intentos.

El portal está en Internet y, desde que tiene consola, quien entra como
administrador puede ejecutar órdenes en el servidor. Por eso:

  · USUARIOS EN LA BASE, con rol: `editor` (enlaces, asistente, monitor) y
    `admin` (lo anterior + consola). Se gestionan con tools/usuarios.py.
  · SESIONES EN EL SERVIDOR: la cookie firmada solo lleva un identificador
    aleatorio; lo que vale es la fila de `sesiones`. Así una sesión se puede
    cerrar desde fuera (otro dispositivo, la CLI, un cambio de contraseña).
    Duran LINKMANAGER_SESION_DIAS (30) y caducan antes si pasan
    LINKMANAGER_SESION_INACTIVA_DIAS (7) sin uso.
  · 2FA (TOTP, RFC 6238): si el usuario lo tiene activado, el login pide el
    código. La consola EXIGE tenerlo y lo vuelve a pedir cada
    CONSOLA_DESBLOQUEO_HORAS (8). Un código no se puede usar dos veces.
  · LÍMITES DE INTENTOS en SQLite (gunicorn tiene varios workers y no
    comparten memoria): por IP y, para el segundo paso, por usuario, que es lo
    que impide probar el millón de códigos desde muchas IPs.
  · REGISTRO de accesos (`accesos`): logins, fallos, consola. Se ve con la CLI.

Solo biblioteca estándar + werkzeug (que ya trae Flask).
"""

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import struct
import time
from urllib.parse import quote

from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("editor", "admin")


def _entero(nombre, defecto, minimo=1):
    try:
        return max(minimo, int(os.environ.get(nombre, str(defecto))))
    except (TypeError, ValueError):
        return defecto


SESION_DIAS = _entero("LINKMANAGER_SESION_DIAS", 30)
SESION_INACTIVA_DIAS = _entero("LINKMANAGER_SESION_INACTIVA_DIAS", 7)
CONSOLA_HORAS = _entero("CONSOLA_DESBLOQUEO_HORAS", 8)

# Límites (ventanas en segundos)
IP_FALLOS, IP_VENTANA = 10, 900            # 10 fallos por IP cada 15 min
USUARIO_2FA_FALLOS, USUARIO_2FA_VENTANA = 5, 900   # 5 códigos malos por usuario cada 15 min
TOQUE_SESION = 300                         # cada cuánto se apunta `ultima` (no en cada petición)

# Hash de mentira para comparar cuando el usuario no existe: el tiempo de
# respuesta no debe delatar qué usuarios hay.
_HASH_SEÑUELO = generate_password_hash(secrets.token_urlsafe(16))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'editor',
    totp TEXT,
    totp_paso INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sesiones (
    id TEXT PRIMARY KEY,               -- sha256 del identificador de la cookie
    usuario_id INTEGER NOT NULL,
    creada REAL NOT NULL,
    ultima REAL NOT NULL,
    expira REAL NOT NULL,
    ip TEXT,
    agente TEXT,
    consola_hasta REAL NOT NULL DEFAULT 0,
    revocada INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sesiones_usuario ON sesiones(usuario_id);
CREATE TABLE IF NOT EXISTS accesos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    ip TEXT,
    usuario TEXT,
    evento TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0,
    detalle TEXT
);
CREATE INDEX IF NOT EXISTS accesos_ts ON accesos(ts);
CREATE TABLE IF NOT EXISTS consola_tickets (
    id TEXT PRIMARY KEY,               -- sha256 del ticket
    sesion_id TEXT NOT NULL,
    terminal TEXT NOT NULL,
    expira REAL NOT NULL
);
"""


def _h(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def conectar(ruta):
    con = sqlite3.connect(ruta, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def preparar(ruta, usuario_inicial, hash_inicial, clave_entorno=None, hash_entorno=None):
    """Crea las tablas y, si no hay ningún usuario, el administrador inicial.

    Si la contraseña viene del entorno (LINKMANAGER_PASSWORD o _HASH), manda
    el entorno: se sincroniza en cada arranque. Si no, la base es la que
    manda y se cambia con tools/usuarios.py.
    """
    con = conectar(ruta)
    try:
        con.executescript(ESQUEMA)
        hay = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        if not hay:
            try:
                con.execute("INSERT INTO usuarios (nombre, hash, rol) VALUES (?, ?, 'admin')",
                            (usuario_inicial, hash_inicial))
            except sqlite3.IntegrityError:
                pass  # otro worker se adelantó
        elif clave_entorno or hash_entorno:
            fila = con.execute("SELECT id, hash FROM usuarios WHERE nombre = ?",
                               (usuario_inicial,)).fetchone()
            if fila:
                igual = (check_password_hash(fila["hash"], clave_entorno) if clave_entorno
                         else fila["hash"] == hash_entorno)
                if not igual:
                    con.execute("UPDATE usuarios SET hash = ? WHERE id = ?",
                                (hash_inicial, fila["id"]))
        # Limpieza: sesiones muertas, tickets caducados y registro de más de 90 días
        ahora = time.time()
        con.execute("DELETE FROM sesiones WHERE expira < ? OR revocada = 1 AND ultima < ?",
                    (ahora, ahora - 86400 * 7))
        con.execute("DELETE FROM consola_tickets WHERE expira < ?", (ahora,))
        con.execute("DELETE FROM accesos WHERE ts < ?", (ahora - 86400 * 90,))
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------
#  Registro y límites
# --------------------------------------------------------------------------

def registrar(con, ip, usuario, evento, ok, detalle=""):
    con.execute("INSERT INTO accesos (ts, ip, usuario, evento, ok, detalle) VALUES (?,?,?,?,?,?)",
                (time.time(), ip, usuario, evento, 1 if ok else 0, (detalle or "")[:300]))
    con.commit()


def bloqueado_ip(con, ip) -> bool:
    n = con.execute("SELECT COUNT(*) FROM accesos WHERE ip = ? AND ok = 0 AND ts > ? "
                    "AND evento IN ('login', '2fa', 'consola')",
                    (ip, time.time() - IP_VENTANA)).fetchone()[0]
    return n >= IP_FALLOS


def bloqueado_2fa(con, usuario) -> bool:
    n = con.execute("SELECT COUNT(*) FROM accesos WHERE usuario = ? AND ok = 0 AND ts > ? "
                    "AND evento IN ('2fa', 'consola')",
                    (usuario, time.time() - USUARIO_2FA_VENTANA)).fetchone()[0]
    return n >= USUARIO_2FA_FALLOS


# --------------------------------------------------------------------------
#  Usuarios y contraseñas
# --------------------------------------------------------------------------

def usuario_por_nombre(con, nombre):
    return con.execute("SELECT * FROM usuarios WHERE nombre = ?", (nombre,)).fetchone()


def comprobar_clave(con, nombre, clave):
    """Devuelve la fila del usuario si nombre y clave valen. Tiempo constante."""
    fila = usuario_por_nombre(con, nombre) if nombre else None
    hash_ = fila["hash"] if fila else _HASH_SEÑUELO
    valida = check_password_hash(hash_, clave or "")
    if fila and valida and fila["activo"]:
        return fila
    return None


def validar_clave_nueva(clave: str):
    """Para la CLI: una contraseña que va a proteger una consola."""
    if len(clave) < 12:
        return "Mínimo 12 caracteres."
    if clave.lower() in {"contraseña1234", "password1234", "123456789012"}:
        return "Demasiado común."
    return None


# --------------------------------------------------------------------------
#  TOTP (RFC 6238) — SHA1, 6 dígitos, 30 s, como cualquier app de códigos
# --------------------------------------------------------------------------

def totp_nuevo_secreto() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_uri(secreto, usuario, emisor="LinkManager"):
    etiqueta = quote(f"{emisor}:{usuario}")
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(emisor)}&algorithm=SHA1&digits=6&period=30"


def _totp_en(secreto, paso):
    relleno = "=" * (-len(secreto) % 8)
    clave = base64.b32decode(secreto.upper() + relleno)
    resumen = hmac.new(clave, struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = resumen[-1] & 0x0F
    numero = struct.unpack(">I", resumen[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return f"{numero % 1_000_000:06d}"


def totp_paso_valido(secreto, codigo, ultimo_paso=0, ventana=1):
    """Devuelve el paso usado si el código vale y no se había usado; si no, None."""
    codigo = "".join(c for c in str(codigo or "") if c.isdigit())
    if len(codigo) != 6 or not secreto:
        return None
    actual = int(time.time()) // 30
    for paso in range(actual - ventana, actual + ventana + 1):
        if paso > ultimo_paso and hmac.compare_digest(_totp_en(secreto, paso), codigo):
            return paso
    return None


def verificar_totp(con, usuario_fila, codigo) -> bool:
    """Comprueba el código y lo «quema» (no vale dos veces). Atómico entre workers."""
    paso = totp_paso_valido(usuario_fila["totp"], codigo, usuario_fila["totp_paso"])
    if paso is None:
        return False
    cur = con.execute("UPDATE usuarios SET totp_paso = ? WHERE id = ? AND totp_paso < ?",
                      (paso, usuario_fila["id"], paso))
    con.commit()
    return cur.rowcount == 1


# --------------------------------------------------------------------------
#  Sesiones
# --------------------------------------------------------------------------

def crear_sesion(con, usuario_id, ip, agente):
    """Devuelve el identificador en claro (va a la cookie firmada). En la base, su hash."""
    sid = secrets.token_urlsafe(32)
    ahora = time.time()
    con.execute("INSERT INTO sesiones (id, usuario_id, creada, ultima, expira, ip, agente) "
                "VALUES (?,?,?,?,?,?,?)",
                (_h(sid), usuario_id, ahora, ahora, ahora + SESION_DIAS * 86400,
                 ip, (agente or "")[:200]))
    con.commit()
    return sid


def leer_sesion(con, sid, ip=None):
    """Fila de sesión + usuario, o None si no vale. Renueva `ultima` de vez en cuando."""
    if not sid:
        return None
    fila = con.execute(
        "SELECT s.id AS sid_hash, s.usuario_id, s.creada, s.ultima, s.expira, "
        "s.consola_hasta, s.revocada, u.nombre, u.rol, u.activo, u.totp "
        "FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id WHERE s.id = ?",
        (_h(sid),)).fetchone()
    if not fila:
        return None
    ahora = time.time()
    if (fila["revocada"] or not fila["activo"] or fila["expira"] < ahora
            or ahora - fila["ultima"] > SESION_INACTIVA_DIAS * 86400):
        return None
    if ahora - fila["ultima"] > TOQUE_SESION:
        con.execute("UPDATE sesiones SET ultima = ?, ip = COALESCE(?, ip) WHERE id = ?",
                    (ahora, ip, fila["sid_hash"]))
        con.commit()
    return fila


def cerrar_sesion(con, sid):
    if sid:
        con.execute("UPDATE sesiones SET revocada = 1 WHERE id = ?", (_h(sid),))
        con.commit()


def cerrar_sesiones_usuario(con, usuario_id, excepto_sid=None):
    if excepto_sid:
        cur = con.execute("UPDATE sesiones SET revocada = 1 WHERE usuario_id = ? AND id != ? "
                          "AND revocada = 0", (usuario_id, _h(excepto_sid)))
    else:
        cur = con.execute("UPDATE sesiones SET revocada = 1 WHERE usuario_id = ? AND revocada = 0",
                          (usuario_id,))
    con.commit()
    return cur.rowcount


def sesiones_usuario(con, usuario_id):
    ahora = time.time()
    return con.execute("SELECT id, creada, ultima, expira, ip, agente, consola_hasta FROM sesiones "
                       "WHERE usuario_id = ? AND revocada = 0 AND expira > ? ORDER BY ultima DESC",
                       (usuario_id, ahora)).fetchall()


# --------------------------------------------------------------------------
#  Consola: desbloqueo y tickets de un solo uso para el websocket
# --------------------------------------------------------------------------

def desbloquear_consola(con, sid_hash):
    hasta = time.time() + CONSOLA_HORAS * 3600
    con.execute("UPDATE sesiones SET consola_hasta = ? WHERE id = ?", (hasta, sid_hash))
    con.commit()
    return hasta


def bloquear_consola(con, sid_hash):
    con.execute("UPDATE sesiones SET consola_hasta = 0 WHERE id = ?", (sid_hash,))
    con.commit()


def emitir_ticket(con, sid_hash, terminal):
    ticket = secrets.token_urlsafe(32)
    con.execute("INSERT INTO consola_tickets (id, sesion_id, terminal, expira) VALUES (?,?,?,?)",
                (_h(ticket), sid_hash, terminal, time.time() + 30))
    con.commit()
    return ticket


def canjear_ticket(con, ticket, sid_hash, terminal) -> bool:
    """Un ticket vale una vez, 30 segundos, para esa sesión y ese terminal."""
    if not ticket:
        return False
    cur = con.execute("DELETE FROM consola_tickets WHERE id = ? AND sesion_id = ? AND terminal = ? "
                      "AND expira > ?", (_h(ticket), sid_hash, terminal, time.time()))
    con.commit()
    return cur.rowcount == 1
