"""
monitor.py — el estado del ordenador dentro de LinkManager.

QUÉ HACE
    Habla con Glances (contenedor `glances`, API REST v4, red docker `proxy`)
    y devuelve un resumen pequeño y normalizado: CPU, RAM, GPU, temperaturas,
    disco y red. La interfaz lo pinta con la tipografía y la paleta del portal,
    así que no hay una segunda aplicación distinta dentro de la primera.

POR QUÉ GLANCES Y NO CÓDIGO PROPIO
    Medir bien un Linux (por núcleo, iowait, swap, sensores, GPU, uptime) es un
    trabajo que ya está hecho y probado. Aquí solo se recoge, se recorta y se
    le pone forma. Si mañana Glances no está, el portal sigue funcionando y el
    panel dice «sin datos».

LO QUE NO HACE, A PROPÓSITO
    · No ejecuta órdenes, no abre una consola y no toca el motor de Docker.
    · El contenedor de Glances no publica puertos: solo se llega desde la red
      `proxy`, o sea, desde este portal y con sesión iniciada.
    · Nada de esto escribe: es todo lectura.
"""

from __future__ import annotations

import glob
import json
import os
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------
#  Configuración
# --------------------------------------------------------------------------

UMBRALES = {
    # a partir de aquí se enciende el ámbar y luego el rojo
    "cpu_atencion": 70.0, "cpu_alto": 88.0,
    "ram_atencion": 80.0, "ram_alto": 92.0,
    "temp_atencion": 75.0, "temp_alto": 88.0,
    "disco_atencion": 85.0, "disco_alto": 93.0,
}

_CACHE = {"cuando": 0.0, "datos": None}
CACHE_SEGUNDOS = 2.0  # varias pestañas abiertas no deben martillear a Glances


def activo() -> bool:
    return os.environ.get("MONITOR_ACTIVO", "1").strip().lower() not in ("0", "false", "no")


def url_base() -> str:
    return os.environ.get("MONITOR_URL", "http://glances:61208").rstrip("/")


def _num(valor, defecto: float = 0.0) -> float:
    """Convierte a número lo que venga (None, cadena, dict) sin romperse."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return defecto


def _segundos(nombre: str, defecto: float) -> float:
    try:
        return float(os.environ.get(nombre, defecto))
    except (TypeError, ValueError):
        return defecto


def _leer_api(ruta: str) -> object:
    peticion = urllib.request.Request(
        f"{url_base()}/api/4/{ruta}",
        headers={"Accept": "application/json", "User-Agent": "LinkManager/2.0"})
    with urllib.request.urlopen(peticion, timeout=_segundos("MONITOR_TIMEOUT", 2.5)) as respuesta:
        return json.loads(respuesta.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------
#  Piezas que Glances no da y se leen aquí
# --------------------------------------------------------------------------

def _gpu_sysfs() -> dict:
    """Uso y temperatura de la GPU integrada leyendo el núcleo.

    Glances conoce la GPU por su plugin (nombre y temperatura), pero en las
    Radeon integradas no siempre saca el % de uso: ese dato está en
    /sys/class/drm/card0/device/gpu_busy_percent y leerlo es gratis.
    """
    salida: dict = {"pct": None, "temp": None}
    for ruta in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        try:
            with open(ruta, encoding="ascii") as fh:
                salida["pct"] = int(fh.read().strip())
            break
        except (OSError, ValueError):
            continue
    for ruta in glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input"):
        try:
            with open(ruta, encoding="ascii") as fh:
                salida["temp"] = round(int(fh.read().strip()) / 1000.0, 1)
            break
        except (OSError, ValueError):
            continue
    return salida


def _disco(ruta: str = "/app/database") -> dict:
    """Disco del ANFITRIÓN.

    `/app/database` es un volumen de Docker, o sea, una carpeta del disco real
    del servidor. Midiendo ahí se obtiene el uso del disco de la máquina sin
    montar medio host dentro del contenedor.
    """
    try:
        datos = os.statvfs(ruta)
    except OSError:
        return {"pct": None, "usado_gb": None, "total_gb": None}
    total = datos.f_blocks * datos.f_frsize
    libre = datos.f_bavail * datos.f_frsize
    if total <= 0:
        return {"pct": None, "usado_gb": None, "total_gb": None}
    usado = total - libre
    return {"pct": round(usado / total * 100, 1),
            "usado_gb": round(usado / 1e9, 1),
            "total_gb": round(total / 1e9, 1)}


def _estado(resumen: dict) -> dict:
    """Un semáforo con el peor de los indicadores, y el motivo."""
    peores = []
    for clave, etiqueta in (("cpu", "CPU"), ("ram", "memoria"), ("temp", "temperatura"),
                            ("disco", "disco")):
        valor = resumen.get(clave)
        if valor is None:
            continue
        if valor >= UMBRALES[f"{clave}_alto"]:
            peores.append((2, f"{etiqueta} al {valor:.0f}%"))
        elif valor >= UMBRALES[f"{clave}_atencion"]:
            peores.append((1, f"{etiqueta} al {valor:.0f}%"))
    if not peores:
        return {"nivel": "ok", "texto": "todo en orden"}
    peores.sort(reverse=True)
    nivel = "alto" if peores[0][0] == 2 else "atencion"
    return {"nivel": nivel, "texto": ", ".join(p[1] for p in peores[:3])}


# --------------------------------------------------------------------------
#  La lectura completa
# --------------------------------------------------------------------------

def datos(usar_cache: bool = True) -> dict:
    """Resumen del estado del ordenador. Nunca lanza: si algo falla, lo cuenta."""
    if not activo():
        return {"disponible": False, "motivo": "El monitor está desactivado (MONITOR_ACTIVO=0)."}

    ahora = time.time()
    if usar_cache and _CACHE["datos"] and ahora - _CACHE["cuando"] < CACHE_SEGUNDOS:
        return _CACHE["datos"]

    try:
        todo = _leer_api("all")
        if not isinstance(todo, dict):
            raise ValueError("respuesta inesperada de Glances")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        resultado = {"disponible": False,
                     "motivo": f"No se pudo hablar con Glances: {type(exc).__name__}"}
        _CACHE.update(cuando=ahora, datos=resultado)
        return resultado

    cpu = todo.get("cpu") or {}
    mem = todo.get("mem") or {}
    swap = todo.get("memswap") or {}
    carga = todo.get("load") or {}
    sistema = todo.get("system") or {}
    sensores = todo.get("sensors") or []
    gpus = todo.get("gpu") or []
    fs = todo.get("fs") or []

    # Temperatura de la CPU: Glances etiqueta en AMD como Tctl; si no, la primera
    temperatura = next((s for s in sensores if str(s.get("label", "")).lower() in ("tctl", "package id 0")),
                       next((s for s in sensores if s.get("type") == "temperature_core"), None))
    temp_cpu = None
    if temperatura and isinstance(temperatura.get("value"), (int, float)):
        temp_cpu = round(float(temperatura["value"]), 1)

    gpu_sysfs = _gpu_sysfs()
    gpu = None
    if gpus:
        principal = gpus[0]
        pct = gpu_sysfs["pct"]
        if pct is None and isinstance(principal.get("proc"), (int, float)) and principal["proc"] > 0:
            pct = round(float(principal["proc"]), 1)
        gpu = {"nombre": principal.get("name") or "GPU",
               "pct": pct,
               "temp": gpu_sysfs["temp"] if gpu_sysfs["temp"] is not None
                       else (principal.get("temperature") or None),
               "mem_mb": principal.get("mem") or None}
    elif gpu_sysfs["pct"] is not None:
        gpu = {"nombre": "GPU integrada", "pct": gpu_sysfs["pct"],
               "temp": gpu_sysfs["temp"], "mem_mb": None}

    # La red NO se muestra: Glances corre en su propio contenedor, así que la
    # interfaz que ve (eth0) es la suya, no la del servidor. Enseñar ese dato
    # sería mentir con una cifra. Para tener la del anfitrión habría que darle
    # `network_mode: host`, y eso publicaría su API fuera de la red del portal.
    red = None

    disco = _disco()
    # Si el volumen del portal no diese datos, se usa el fs que vea Glances
    if disco["pct"] is None and fs:
        try:
            raiz = max(fs, key=lambda f: f.get("size") or 0)
            disco = {"pct": round(float(raiz.get("percent") or 0), 1),
                     "usado_gb": round((raiz.get("used") or 0) / 1e9, 1),
                     "total_gb": round((raiz.get("size") or 0) / 1e9, 1)}
        except (TypeError, ValueError, AttributeError):
            pass

    resumen = {
        "cpu": round(float(cpu.get("total") or 0.0), 1),
        "ram": round(float(mem.get("percent") or 0.0), 1),
        "temp": temp_cpu,
        "disco": disco.get("pct"),
    }

    resultado = {
        "disponible": True,
        "tomado": round(ahora, 1),
        "equipo": {
            "nombre": os.environ.get("MONITOR_EQUIPO", "urbenserver"),
            "so": sistema.get("linux_distro") or sistema.get("os_name") or "",
            "kernel": sistema.get("os_version") or "",
            "nucleos": int(carga.get("cpucore") or len(todo.get("percpu") or []) or 0),
            "arranque": todo.get("uptime") or "",
        },
        "cpu": {
            "pct": resumen["cpu"],
            "nucleos": [round(_num(c.get("total") if isinstance(c, dict) else c), 1)
                        for c in (todo.get("percpu") or [])],
            "carga": [round(float(carga.get(k) or 0), 2) for k in ("min1", "min5", "min15")],
            "temp": temp_cpu,
        },
        "ram": {
            "pct": resumen["ram"],
            "usada_gb": round((mem.get("used") or 0) / 1e9, 1),
            "total_gb": round((mem.get("total") or 0) / 1e9, 1),
            "swap_pct": round(float(swap.get("percent") or 0.0), 1),
            "swap_gb": round((swap.get("used") or 0) / 1e9, 1),
        },
        "gpu": gpu,
        "disco": disco,
        "red": red,
        "estado": _estado(resumen),
        "umbrales": UMBRALES,
    }
    _CACHE.update(cuando=ahora, datos=resultado)
    return resultado
