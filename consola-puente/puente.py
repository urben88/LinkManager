#!/usr/bin/env python3
"""
consola-puente — terminales del servidor para la consola de LinkManager.

Corre EN EL HOST como el usuario `urben` (servicio systemd de usuario) y
escucha en un socket UNIX que se monta dentro del contenedor del portal. No
abre ningún puerto de red: lo único que llega aquí es el portal, que es quien
autentica (sesión + rol admin + 2FA reciente + ticket de un solo uso).

Cada petición va firmada con HMAC-SHA256 con un secreto compartido
(~/.config/consola-puente/secreto, 600) y caduca a los 60 segundos.

Los terminales viven aquí, no en el navegador: si se cierra la pestaña o se
corta la conexión, Claude u OpenCode siguen trabajando, y al volver se
reengancha con lo último que salió por pantalla.

Protocolo (sobre el socket):
  1. El cliente envía UNA línea JSON: {"peticion": {...}, "firma": "hex"}.
     peticion = {"op": "listar"|"crear"|"cerrar"|"adjuntar", "exp": ts,
                 "usuario": "...", ...}
  2. El puente responde UNA línea JSON {"ok": bool, ...}.
  3. Solo en "adjuntar": después vienen tramas binarias en los dos sentidos.
     Trama = 1 byte de tipo + 4 bytes de longitud (big-endian) + datos.
       cliente → puente: b"i" entrada del teclado, b"r" tamaño {"cols","rows"}
       puente → cliente: b"o" salida del terminal, b"x" fin {"codigo": n}

Además, la operación "info" responde a CONSULTAS DE SOLO LECTURA de un
catálogo cerrado (CONSULTAS, abajo). Es lo que usa el asistente de IA para
saber qué CPU, discos o servicios tiene el servidor. Nunca recibe un comando:
recibe el NOMBRE de una consulta, y cada consulta es una lista fija de
programas con sus argumentos fijos, ejecutados sin shell, sin sudo, con
tiempo máximo y con la salida recortada y limpia de posibles secretos.

Solo biblioteca estándar.
"""

import fcntl
import hashlib
import hmac
import json
import logging
import os
import pty
import secrets
import signal
import socket
import re
import struct
import subprocess
import termios
import threading
import time
from collections import deque

RUTA_SOCKET = os.environ.get("PUENTE_SOCKET", os.path.expanduser("~/.local/share/consola-puente/consola.sock"))
RUTA_SECRETO = os.environ.get("PUENTE_SECRETO", os.path.expanduser("~/.config/consola-puente/secreto"))
CARPETA_INICIAL = os.environ.get("PUENTE_CARPETA", os.path.expanduser("~"))
MAX_TERMINALES = int(os.environ.get("PUENTE_MAX_TERMINALES", "8"))
BUFFER_BYTES = 512 * 1024          # lo que se reenvía al reengancharse
INACTIVO_MAX = int(os.environ.get("PUENTE_INACTIVO_HORAS", "72")) * 3600

# Qué se puede lanzar. Nada de órdenes libres por aquí: el navegador elige
# un tipo, no un comando. Al salir del programa queda una shell normal.
PROGRAMAS = {
    "shell":    {"nombre": "Terminal", "orden": "exec bash -l"},
    "claude":   {"nombre": "Claude",   "orden": "claude; exec bash -l"},
    "opencode": {"nombre": "OpenCode", "orden": "opencode; exec bash -l"},
}

# ---------------------------------------------------------------- consultas
#
# Reglas para añadir una consulta aquí:
#   · solo programas que LEEN (nada que cambie estado, ni con flags raros)
#   · ruta absoluta y argumentos fijos: el que pregunta no elige nada
#   · sin sudo y sin leer ficheros de configuración o de entorno
#   · nada que enseñe argumentos de procesos o variables (pueden llevar claves)
# Cada paso es (título, ["/ruta/programa", "arg", ...]) o (título, "fichero:/ruta")
# o (título, "dmi") para los datos de placa legibles sin root.

CONSULTAS = {
    "resumen": ("Sistema operativo, kernel, nombre del equipo, tiempo encendido y carga", [
        ("hostnamectl", ["/usr/bin/hostnamectl"]),
        ("os-release", "fichero:/etc/os-release"),
        ("uname", ["/usr/bin/uname", "-srvmo"]),
        ("uptime", ["/usr/bin/uptime"]),
    ]),
    "cpu": ("Modelo de CPU, núcleos, hilos, frecuencias, cachés y virtualización", [
        ("lscpu", ["/usr/bin/lscpu"]),
        ("carga", "fichero:/proc/loadavg"),
    ]),
    "memoria": ("RAM y swap: total, usada, libre y dispositivos de swap", [
        ("free", ["/usr/bin/free", "-h", "--si"]),
        ("swap", ["/usr/sbin/swapon", "--show"]),
    ]),
    "placa": ("Fabricante, modelo de placa base y versión/fecha de BIOS", [
        ("dmi", "dmi"),
    ]),
    "gpu": ("Tarjetas gráficas y dispositivos PCI", [
        ("lspci", ["/usr/bin/lspci", "-nn"]),
    ]),
    "usb": ("Dispositivos USB conectados", [
        ("lsusb", ["/usr/bin/lsusb"]),
    ]),
    "temperaturas": ("Sensores: temperaturas de CPU/GPU/discos, ventiladores y voltajes", [
        ("sensors", ["/usr/bin/sensors"]),
    ]),
    "discos": ("Discos y particiones (modelo, tamaño, tipo SSD/HDD) y espacio libre", [
        ("lsblk", ["/usr/bin/lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,ROTA,TRAN"]),
        ("df", ["/usr/bin/df", "-hT", "-x", "tmpfs", "-x", "overlay", "-x", "squashfs",
                "-x", "devtmpfs", "-x", "efivarfs"]),
    ]),
    "montajes": ("Sistemas de ficheros montados (sin los de Docker)", [
        ("findmnt", ["/usr/bin/findmnt", "-D", "-t", "ext4,btrfs,xfs,vfat,ntfs,ntfs3,exfat,nfs,nfs4,cifs,fuseblk"]),
    ]),
    "red": ("Interfaces, IPs, rutas y puertos que escuchan", [
        ("interfaces", ["/usr/sbin/ip", "-br", "addr"]),
        ("rutas", ["/usr/sbin/ip", "route"]),
        ("puertos", ["/usr/bin/ss", "-tulnH"]),
    ]),
    "procesos": ("Los procesos que más CPU y memoria gastan (solo nombre, sin argumentos)", [
        ("por CPU", ["/usr/bin/ps", "-eo", "pid,user,pcpu,pmem,etime,comm", "--sort=-pcpu"]),
        ("por memoria", ["/usr/bin/ps", "-eo", "pid,user,pcpu,pmem,rss,comm", "--sort=-rss"]),
    ]),
    "servicios": ("Servicios systemd en marcha y los que han fallado (sistema y usuario)", [
        ("fallidos", ["/usr/bin/systemctl", "--failed", "--no-pager", "--plain"]),
        ("en marcha", ["/usr/bin/systemctl", "list-units", "--type=service", "--state=running",
                       "--no-pager", "--plain", "--no-legend"]),
        ("de usuario", ["/usr/bin/systemctl", "--user", "list-units", "--type=service",
                        "--no-pager", "--plain", "--no-legend"]),
        ("temporizadores", ["/usr/bin/systemctl", "list-timers", "--no-pager"]),
    ]),
    "docker": ("Todos los contenedores con su imagen y estado", [
        ("contenedores", ["/usr/bin/docker", "ps", "-a", "--format", "{{.Names}} | {{.Image}} | {{.Status}}"]),
    ]),
    "docker_puertos": ("Puertos que publica cada contenedor", [
        ("puertos", ["/usr/bin/docker", "ps", "--format", "{{.Names}} | {{.Ports}}"]),
    ]),
    "docker_consumo": ("CPU, memoria y E/S de cada contenedor ahora, y espacio que ocupa Docker", [
        ("consumo", ["/usr/bin/docker", "stats", "--no-stream", "--format",
                     "{{.Name}} | cpu {{.CPUPerc}} | mem {{.MemUsage}} | red {{.NetIO}} | disco {{.BlockIO}}"]),
        ("espacio", ["/usr/bin/docker", "system", "df"]),
    ]),
    "errores": ("Errores del sistema desde el último arranque (journal, prioridad error o peor)", [
        ("journal", ["/usr/bin/journalctl", "-p", "3", "-b", "-n", "60", "--no-pager", "-o", "short-iso"]),
    ]),
    "kernel": ("Avisos del kernel desde el último arranque (hardware, discos, drivers)", [
        ("kernel", ["/usr/bin/journalctl", "-k", "-p", "4", "-b", "-n", "60", "--no-pager", "-o", "short-iso"]),
    ]),
    "arranques": ("Últimos arranques del equipo", [
        ("arranques", ["/usr/bin/journalctl", "--list-boots", "--no-pager"]),
    ]),
    "hora": ("Hora, zona horaria y sincronización NTP", [
        ("timedatectl", ["/usr/bin/timedatectl"]),
    ]),
    "sesiones": ("Quién tiene sesión abierta en el equipo", [
        ("who", ["/usr/bin/who"]),
    ]),
    "actualizaciones": ("Paquetes con actualización pendiente (según la última lista descargada)", [
        ("apt", ["/usr/bin/apt", "list", "--upgradable"]),
    ]),
    "ia": ("Modelos de Ollama descargados y cargados en memoria", [
        ("modelos", ["/usr/local/bin/ollama", "list"]),
        ("cargados", ["/usr/local/bin/ollama", "ps"]),
    ]),
}

MAX_SALIDA_PASO = 11000
MAX_SALIDA_TOTAL = 12000
FILAS_PROCESOS = 25
CAMPOS_DMI = ("sys_vendor", "product_name", "product_version", "product_family",
              "board_vendor", "board_name", "board_version",
              "bios_vendor", "bios_version", "bios_date", "chassis_type")

# Por si algo se cuela en un log: claves, tokens y contraseñas fuera.
_SECRETOS = re.compile(
    r"(?i)((?:pass(?:word)?|passwd|token|secret|api[_-]?key|authorization|bearer|cookie)"
    r"[\"']?\s*[:=]\s*[\"']?)[^\s\"',;]+")
_CLAVES_LARGAS = re.compile(r"\b(?:sk|ghp|gho|glpat|xox[abp])[-_][A-Za-z0-9_\-]{16,}\b")


def _limpiar(texto: str) -> str:
    texto = _SECRETOS.sub(r"\1[oculto]", texto)
    return _CLAVES_LARGAS.sub("[oculto]", texto)


def _paso(fuente):
    if fuente == "dmi":
        filas = []
        for campo in CAMPOS_DMI:
            try:
                valor = open(f"/sys/class/dmi/id/{campo}").read().strip()
            except OSError:
                continue
            if valor:
                filas.append(f"{campo}: {valor}")
        return "\n".join(filas) or "(sin datos DMI)"
    if isinstance(fuente, str) and fuente.startswith("fichero:"):
        try:
            return open(fuente[8:], encoding="utf-8", errors="replace").read(MAX_SALIDA_PASO)
        except OSError as exc:
            return f"(no se pudo leer: {exc.strerror})"
    if not os.path.exists(fuente[0]):
        return "(no instalado en el servidor)"
    entorno = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C.UTF-8",
               "LC_ALL": "C.UTF-8", "HOME": os.path.expanduser("~"),
               "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
               "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""),
               "SYSTEMD_COLORS": "0", "SYSTEMD_PAGER": "", "NO_COLOR": "1"}
    try:
        r = subprocess.run(fuente, capture_output=True, stdin=subprocess.DEVNULL, timeout=15,
                           env=entorno, cwd="/", text=True, errors="replace")
    except subprocess.TimeoutExpired:
        return "(tardó demasiado: cancelado)"
    except OSError as exc:
        return f"(no se pudo ejecutar: {exc.strerror})"
    salida = r.stdout.strip()
    if r.returncode != 0 and r.stderr.strip():
        salida += ("\n" if salida else "") + "(aviso) " + r.stderr.strip()[:500]
    return salida or "(sin salida)"


def _recortar(titulo, texto):
    """Quita ruido que no aporta y gasta contexto del modelo."""
    filas = texto.splitlines()
    if titulo == "interfaces":       # una veth por contenedor: no dicen nada
        filas = [f for f in filas if not f.startswith(("veth", "br-"))]
    elif titulo == "puertos" and filas and "|" not in filas[0]:
        # ss: sin duplicar IPv4/IPv6 ni los puertos efímeros del resolvedor
        vistos, limpio = set(), []
        for f in filas:
            partes = f.split()
            clave = (partes[0], partes[4].rsplit(":", 1)[-1]) if len(partes) > 4 else f
            if clave not in vistos:
                vistos.add(clave)
                limpio.append(f)
        filas = limpio
    elif titulo == "lscpu":            # la lista de flags es enorme y no aporta
        filas = [f for f in filas if not f.startswith(("Flags:", "Vulnerability"))]
    elif titulo == "puertos" and "|" in (filas[0] if filas else ""):
        filas = [f for f in filas if not f.rstrip().endswith("|")]  # contenedores sin puertos
    return "\n".join(f[:300] for f in filas)


def consultar(clave):
    if clave not in CONSULTAS:
        return None
    descripcion, pasos = CONSULTAS[clave]
    partes = []
    for titulo, fuente in pasos:
        texto = _recortar(titulo, _paso(fuente))
        if clave == "procesos":
            texto = "\n".join(texto.splitlines()[:FILAS_PROCESOS + 1])
        if len(texto) > MAX_SALIDA_PASO:
            texto = texto[:MAX_SALIDA_PASO] + "\n…(recortado)"
        partes.append(f"### {titulo}\n{texto}")
    return _limpiar("\n\n".join(partes))[:MAX_SALIDA_TOTAL]


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("consola-puente")


# ---------------------------------------------------------------- secreto

def cargar_secreto() -> bytes:
    os.makedirs(os.path.dirname(RUTA_SECRETO), mode=0o700, exist_ok=True)
    if not os.path.exists(RUTA_SECRETO):
        viejo = os.umask(0o077)
        try:
            with open(RUTA_SECRETO, "w") as fh:
                fh.write(secrets.token_hex(32) + "\n")
        finally:
            os.umask(viejo)
        log.info("secreto nuevo en %s", RUTA_SECRETO)
    os.chmod(RUTA_SECRETO, 0o600)
    return open(RUTA_SECRETO, "rb").read().strip()


SECRETO = cargar_secreto()


def firma_valida(peticion: dict, firma: str) -> bool:
    cuerpo = json.dumps(peticion, sort_keys=True, separators=(",", ":")).encode()
    esperada = hmac.new(SECRETO, cuerpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperada, str(firma or "")):
        return False
    exp = peticion.get("exp", 0)
    ahora = time.time()
    return isinstance(exp, (int, float)) and ahora <= exp <= ahora + 120


# ---------------------------------------------------------------- tramas

def enviar_trama(sock, tipo: bytes, datos: bytes):
    sock.sendall(tipo + struct.pack(">I", len(datos)) + datos)


def leer_exacto(sock, n):
    trozos = b""
    while len(trozos) < n:
        t = sock.recv(n - len(trozos))
        if not t:
            raise ConnectionError("cerrado")
        trozos += t
    return trozos


def leer_trama(sock):
    cab = leer_exacto(sock, 5)
    tipo, largo = cab[:1], struct.unpack(">I", cab[1:])[0]
    if largo > 1024 * 1024:
        raise ConnectionError("trama demasiado grande")
    return tipo, leer_exacto(sock, largo)


# ---------------------------------------------------------------- terminales

class Terminal:
    def __init__(self, tipo, carpeta, usuario, cols, rows):
        self.id = secrets.token_hex(6)
        self.tipo = tipo
        self.carpeta = carpeta
        self.usuario = usuario
        self.creada = time.time()
        self.actividad = time.time()
        self.buffer = deque()
        self.buffer_len = 0
        self.clientes = set()
        self.cerrojo = threading.Lock()
        self.vivo = True
        self.codigo = None

        pid, fd = pty.fork()
        if pid == 0:  # hijo
            try:
                os.chdir(carpeta)
                entorno = dict(os.environ)
                for k in ("PUENTE_SOCKET", "PUENTE_SECRETO", "INVOCATION_ID", "JOURNAL_STREAM"):
                    entorno.pop(k, None)
                entorno.update({"TERM": "xterm-256color", "COLORTERM": "truecolor",
                                "LANG": entorno.get("LANG", "es_ES.UTF-8"),
                                "LINKMANAGER_CONSOLA": "1"})
                os.execvpe("bash", ["bash", "-lc", PROGRAMAS[tipo]["orden"]], entorno)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.redimensionar(cols, rows)
        threading.Thread(target=self._leer, daemon=True).start()
        log.info("terminal %s (%s) creada por %s en %s, pid %s", self.id, tipo, usuario, carpeta, pid)

    def info(self):
        return {"id": self.id, "tipo": self.tipo, "nombre": PROGRAMAS[self.tipo]["nombre"],
                "carpeta": self.carpeta, "creada": self.creada, "actividad": self.actividad,
                "vivo": self.vivo, "clientes": len(self.clientes)}

    def redimensionar(self, cols, rows):
        try:
            cols = max(20, min(500, int(cols)))
            rows = max(5, min(200, int(rows)))
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except (OSError, ValueError, TypeError):
            pass

    def escribir(self, datos: bytes):
        self.actividad = time.time()
        while datos:
            try:
                n = os.write(self.fd, datos)
                datos = datos[n:]
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                return

    def _leer(self):
        while True:
            try:
                datos = os.read(self.fd, 65536)
            except OSError:
                datos = b""
            if not datos:
                break
            self.actividad = time.time()
            with self.cerrojo:
                self.buffer.append(datos)
                self.buffer_len += len(datos)
                while self.buffer_len > BUFFER_BYTES and len(self.buffer) > 1:
                    self.buffer_len -= len(self.buffer.popleft())
                clientes = list(self.clientes)
            for c in clientes:
                try:
                    enviar_trama(c, b"o", datos)
                except OSError:
                    self.soltar(c)
        self._terminar()

    def _terminar(self):
        try:
            _, estado = os.waitpid(self.pid, 0)
            self.codigo = os.waitstatus_to_exitcode(estado)
        except ChildProcessError:
            self.codigo = None
        self.vivo = False
        try:
            os.close(self.fd)
        except OSError:
            pass
        with self.cerrojo:
            clientes = list(self.clientes)
            self.clientes.clear()
        aviso = json.dumps({"codigo": self.codigo}).encode()
        for c in clientes:
            try:
                enviar_trama(c, b"x", aviso)
                c.close()
            except OSError:
                pass
        TERMINALES.pop(self.id, None)
        log.info("terminal %s terminó (código %s)", self.id, self.codigo)

    def adjuntar(self, sock):
        with self.cerrojo:
            pasado = b"".join(self.buffer)
            if pasado:
                enviar_trama(sock, b"o", pasado)
            self.clientes.add(sock)

    def soltar(self, sock):
        with self.cerrojo:
            self.clientes.discard(sock)

    def matar(self):
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            return
        def rematar():
            time.sleep(4)
            if self.vivo:
                try:
                    os.killpg(os.getpgid(self.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        threading.Thread(target=rematar, daemon=True).start()


TERMINALES: dict = {}


def carpeta_valida(carpeta):
    carpeta = os.path.realpath(os.path.expanduser(carpeta or CARPETA_INICIAL))
    return carpeta if os.path.isdir(carpeta) else None


# ---------------------------------------------------------------- servidor

def responder(sock, datos):
    sock.sendall((json.dumps(datos) + "\n").encode())


def atender(sock):
    try:
        sock.settimeout(10)
        linea = b""
        while not linea.endswith(b"\n"):
            t = sock.recv(4096)
            if not t:
                return
            linea += t
            if len(linea) > 16384:
                return
        try:
            mensaje = json.loads(linea)
            peticion, firma = mensaje["peticion"], mensaje["firma"]
        except (ValueError, KeyError, TypeError):
            return responder(sock, {"ok": False, "error": "petición mal formada"})
        if not isinstance(peticion, dict) or not firma_valida(peticion, firma):
            log.warning("petición con firma inválida o caducada")
            return responder(sock, {"ok": False, "error": "firma inválida"})

        op = peticion.get("op")
        usuario = str(peticion.get("usuario", "?"))[:64]

        if op == "listar":
            return responder(sock, {"ok": True, "terminales": [t.info() for t in TERMINALES.values()],
                                    "programas": {k: v["nombre"] for k, v in PROGRAMAS.items()}})

        if op == "info":
            clave = str(peticion.get("consulta", ""))
            if clave == "catalogo":
                return responder(sock, {"ok": True, "consultas": {k: v[0] for k, v in CONSULTAS.items()}})
            sock.settimeout(120)
            texto = consultar(clave)
            if texto is None:
                return responder(sock, {"ok": False, "error": "consulta desconocida",
                                        "consultas": sorted(CONSULTAS)})
            log.info("consulta de solo lectura «%s» (%s)", clave, usuario)
            return responder(sock, {"ok": True, "consulta": clave, "salida": texto})

        if op == "crear":
            tipo = peticion.get("tipo")
            if tipo not in PROGRAMAS:
                return responder(sock, {"ok": False, "error": "tipo desconocido"})
            if len(TERMINALES) >= MAX_TERMINALES:
                return responder(sock, {"ok": False, "error": f"Ya hay {MAX_TERMINALES} terminales abiertas. Cierra alguna."})
            carpeta = carpeta_valida(peticion.get("carpeta"))
            if not carpeta:
                return responder(sock, {"ok": False, "error": "Esa carpeta no existe en el servidor."})
            t = Terminal(tipo, carpeta, usuario, peticion.get("cols", 100), peticion.get("rows", 30))
            TERMINALES[t.id] = t
            return responder(sock, {"ok": True, "terminal": t.info()})

        if op == "cerrar":
            t = TERMINALES.get(peticion.get("id"))
            if not t:
                return responder(sock, {"ok": False, "error": "no existe"})
            log.info("terminal %s cerrada por %s", t.id, usuario)
            t.matar()
            return responder(sock, {"ok": True})

        if op == "adjuntar":
            t = TERMINALES.get(peticion.get("id"))
            if not t or not t.vivo:
                return responder(sock, {"ok": False, "error": "Esa terminal ya no existe."})
            responder(sock, {"ok": True, "terminal": t.info()})
            sock.settimeout(None)
            t.redimensionar(peticion.get("cols", 100), peticion.get("rows", 30))
            t.adjuntar(sock)
            log.info("terminal %s: se engancha %s", t.id, usuario)
            try:
                while True:
                    tipo, datos = leer_trama(sock)
                    if tipo == b"i":
                        t.escribir(datos)
                    elif tipo == b"r":
                        try:
                            tam = json.loads(datos)
                            t.redimensionar(tam.get("cols"), tam.get("rows"))
                        except ValueError:
                            pass
            except (ConnectionError, OSError):
                pass
            finally:
                t.soltar(sock)
            return

        return responder(sock, {"ok": False, "error": "operación desconocida"})
    except OSError:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


def barrendero():
    """Cierra terminales sin nadie enganchado y sin actividad en días."""
    while True:
        time.sleep(600)
        ahora = time.time()
        for t in list(TERMINALES.values()):
            if not t.clientes and ahora - t.actividad > INACTIVO_MAX:
                log.info("terminal %s inactiva desde hace mucho: se cierra", t.id)
                t.matar()


def main():
    os.makedirs(os.path.dirname(RUTA_SOCKET), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(RUTA_SOCKET), 0o700)
    if os.path.exists(RUTA_SOCKET):
        os.unlink(RUTA_SOCKET)
    servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    viejo = os.umask(0o077)
    try:
        servidor.bind(RUTA_SOCKET)
    finally:
        os.umask(viejo)
    servidor.listen(16)
    log.info("escuchando en %s", RUTA_SOCKET)

    def salir(*_):
        for t in list(TERMINALES.values()):
            t.matar()
        try:
            os.unlink(RUTA_SOCKET)
        except OSError:
            pass
        os._exit(0)

    signal.signal(signal.SIGTERM, salir)
    signal.signal(signal.SIGINT, salir)
    threading.Thread(target=barrendero, daemon=True).start()

    while True:
        cliente, _ = servidor.accept()
        threading.Thread(target=atender, args=(cliente,), daemon=True).start()


if __name__ == "__main__":
    main()
