"""
vigilante.py — los cortes de luz y los registros del vigilante, dentro del portal.

QUÉ HACE
    Lee los logs que escribe el vigilante del servidor (~/watchdog, con systemd
    de usuario) y los resume: si el vigilante sigue latiendo, desde cuándo está
    encendido el equipo y conectado el router, cuándo fue el último corte de
    corriente, el veredicto del último post-mortem y la lista de sucesos.

DE DÓNDE SALE CADA DATO
    logs/health.log    un latido por minuto: arranque, uptime, contador del router
    logs/fastbeat.log  un latido cada 10 s: el pulso fino
    logs/events.log    avisos y veredictos (CORTE-DE-LUZ?, POST-MORTEM, REINICIO…)

    La carpeta se monta en solo lectura en VIGILANTE_DIR (por defecto /vigilante).
    Si no está montada, el panel lo dice y el resto del portal sigue igual.

LO QUE NO HACE, A PROPÓSITO
    · No escribe nada ni arranca nada: el vigilante vive fuera y sigue solo.
    · Solo sirve los tres ficheros de arriba, por nombre fijo: nada de rutas
      que lleguen de la petición.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

# --------------------------------------------------------------------------
#  Configuración
# --------------------------------------------------------------------------

FICHEROS = {
    "events": "events.log",
    "health": "health.log",
    "fastbeat": "fastbeat.log",
}

# Cada tipo de suceso del vigilante va a una de estas familias. Lo que no esté
# aquí se trata como «aviso», para que un tipo nuevo no desaparezca del panel.
FAMILIAS = {
    "CORTE-DE-LUZ?": "corte",
    "CORTE-DE-LUZ": "corte",
    "POST-MORTEM": "veredicto",
    "REINICIO": "reinicio",
    "SALTO-DE-RELOJ": "reinicio",
    "TEMPERATURA-ALTA": "aviso",
    "JOURNAL-GRANDE": "aviso",
    # muy frecuentes: se cuentan, no se listan uno a uno
    "BUCLE-CONTENEDOR": "ruido",
    "REINICIOS-DOCKER": "ruido",
}

# Pasado este tiempo sin latido, el vigilante se da por retrasado o parado
LATIDO_RETRASADO = 90    # s (el fino late cada 10 s, el normal cada 60 s)
LATIDO_PARADO = 300      # s

_EVENTO = re.compile(r"^(\S+)\s+EVENT\s+(\S+)\s+(.*)$")
_CACHE = {"firma": None, "eventos": []}


def activo() -> bool:
    return os.environ.get("VIGILANTE_ACTIVO", "1").strip().lower() not in ("0", "false", "no")


def carpeta() -> str:
    return os.path.join(os.environ.get("VIGILANTE_DIR", "/vigilante"), "logs")


def _ruta(clave: str) -> str:
    return os.path.join(carpeta(), FICHEROS[clave])


def _epoch(iso: str) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
#  Lectura de ficheros
# --------------------------------------------------------------------------

def cola(clave: str, lineas: int = 80, max_bytes: int = 256 * 1024) -> list[str]:
    """Las últimas `lineas` líneas de un log, leyendo solo el final del fichero."""
    try:
        with open(_ruta(clave), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            tam = fh.tell()
            fh.seek(max(0, tam - max_bytes))
            bruto = fh.read()
    except OSError:
        return []
    # Los cuelgues dejan huecos de bytes nulos en los logs: se quitan
    texto = bruto.replace(b"\x00", b"").decode("utf-8", "replace")
    filas = texto.splitlines()
    if tam > max_bytes and filas:
        filas = filas[1:]  # la primera puede venir cortada
    return [f for f in filas if f.strip()][-lineas:]


def _campos(linea: str) -> dict:
    """`clave=valor clave=valor …` → dict."""
    salida = {}
    for trozo in linea.split():
        if "=" in trozo:
            k, v = trozo.split("=", 1)
            salida[k] = v
    return salida


def _eventos() -> list[dict]:
    """Todos los sucesos de events.log, ya agrupados con sus líneas de detalle.

    El fichero ronda el megabyte, así que se relee solo si cambió.
    """
    ruta = _ruta("events")
    try:
        st = os.stat(ruta)
    except OSError:
        return []
    firma = (st.st_size, st.st_mtime)
    if _CACHE["firma"] == firma:
        return _CACHE["eventos"]

    eventos: list[dict] = []
    try:
        with open(ruta, "rb") as fh:
            texto = fh.read().replace(b"\x00", b"").decode("utf-8", "replace")
    except OSError:
        return []
    for linea in texto.splitlines():
        m = _EVENTO.match(linea)
        if m:
            ts, tipo, mensaje = m.groups()
            eventos.append({"ts": ts, "epoch": _epoch(ts), "tipo": tipo,
                            "familia": FAMILIAS.get(tipo, "aviso"),
                            "mensaje": mensaje.strip(), "detalle": []})
        elif linea.strip() and eventos:
            eventos[-1]["detalle"].append(linea.strip())

    for ev in eventos:
        if ev["tipo"] == "POST-MORTEM":
            veredicto, _, explicacion = ev["mensaje"].partition(" | ")
            ev["veredicto"] = veredicto.strip()
            ev["explicacion"] = explicacion.strip()
            if "CORTE DE CORRIENTE" in veredicto:
                ev["familia"] = "corte"

    # Un «CORTE-DE-LUZ?» solo dice que el router rehízo su conexión. Si el
    # servidor no se reinició cerca de esa hora, siguió encendido: o fue un
    # microcorte que aguantó, o el router se reinició por su cuenta.
    reinicios = [e["epoch"] for e in eventos if e["tipo"] == "REINICIO" and e["epoch"]]
    for ev in eventos:
        if ev["tipo"].startswith("CORTE-DE-LUZ") and ev["epoch"]:
            ev["servidor_cayo"] = any(abs(r - ev["epoch"]) <= 600 for r in reinicios)

    _CACHE.update(firma=firma, eventos=eventos)
    return eventos


# --------------------------------------------------------------------------
#  El resumen
# --------------------------------------------------------------------------

def _ultimo(eventos: list[dict], condicion) -> dict | None:
    for ev in reversed(eventos):
        if condicion(ev):
            return ev
    return None


def _publico(ev: dict | None) -> dict | None:
    if not ev:
        return None
    return {k: ev[k] for k in ("ts", "tipo", "familia", "mensaje", "detalle",
                               "veredicto", "explicacion", "servidor_cayo") if k in ev}


def datos() -> dict:
    """Estado del vigilante y sus sucesos. Nunca lanza: si algo falta, lo cuenta."""
    if not activo():
        return {"disponible": False, "motivo": "El vigilante está desactivado (VIGILANTE_ACTIVO=0)."}
    if not os.path.isdir(carpeta()):
        return {"disponible": False,
                "motivo": "No veo los logs del vigilante: falta montar ~/watchdog en el contenedor."}

    ahora = time.time()

    # --- pulso: el latido más reciente de los dos
    salud = cola("health", 1)
    fino = cola("fastbeat", 1)
    ultimo_salud = _campos(salud[-1]) if salud else {}
    ultimo_fino = _campos(fino[-1]) if fino else {}
    epochs = [e for e in (_epoch(ultimo_salud.get("ts")), _epoch(ultimo_fino.get("ts"))) if e]
    ultimo = max(epochs) if epochs else None
    hace = round(ahora - ultimo) if ultimo else None
    if hace is None:
        pulso = "sin-datos"
    elif hace > LATIDO_PARADO:
        pulso = "parado"
    elif hace > LATIDO_RETRASADO:
        pulso = "retrasado"
    else:
        pulso = "vivo"

    # --- equipo y router, del último latido de minuto
    rwan = re.match(r"^(\d+)\((.*)\)$", ultimo_salud.get("rwan", ""))
    router = None
    if rwan:
        # el contador se tomó con ese latido, no ahora
        segundos = int(rwan.group(1))
        medido = _epoch(ultimo_salud.get("ts")) or ahora
        router = {"conectado_s": segundos, "estado": rwan.group(2),
                  "desde": round(medido - segundos)}
    equipo = {
        "arranque": ultimo_salud.get("boot"),
        "uptime_s": int(ultimo_salud["up"].rstrip("s")) if ultimo_salud.get("up", "").rstrip("s").isdigit() else None,
        "cpu_temp": ultimo_salud.get("cpu"),
        "carga": ultimo_salud.get("load"),
        "contenedores": ultimo_salud.get("cont"),
        "io": ultimo_salud.get("io"),
    }

    # --- sucesos
    eventos = _eventos()
    hace_30d = ahora - 30 * 86400
    hace_24h = ahora - 86400
    recientes = [e for e in eventos if (e["epoch"] or 0) >= hace_30d]

    ultimo_corte = _ultimo(eventos, lambda e: e["familia"] == "corte")
    ultimo_reinicio = _ultimo(eventos, lambda e: e["tipo"] == "REINICIO")
    ultimo_veredicto = _ultimo(eventos, lambda e: e["tipo"] == "POST-MORTEM")

    ruido_24h: dict[str, int] = {}
    for e in eventos:
        if e["familia"] == "ruido" and (e["epoch"] or 0) >= hace_24h:
            ruido_24h[e["tipo"]] = ruido_24h.get(e["tipo"], 0) + 1

    # --- semáforo: lo peor que haya pasado en las últimas 24 h
    def reciente(ev):
        return ev and (ev["epoch"] or 0) >= hace_24h

    if pulso in ("parado", "sin-datos"):
        estado = {"nivel": "alto", "texto": "el vigilante no late"}
    elif reciente(ultimo_corte):
        estado = {"nivel": "alto", "texto": "corte de corriente en las últimas 24 h"}
    elif reciente(ultimo_reinicio):
        estado = {"nivel": "atencion", "texto": "reinicio en las últimas 24 h"}
    elif pulso == "retrasado":
        estado = {"nivel": "atencion", "texto": "el vigilante va con retraso"}
    else:
        estado = {"nivel": "ok", "texto": "sin cortes en las últimas 24 h"}

    importantes = [e for e in eventos if e["familia"] != "ruido"][-60:]

    return {
        "disponible": True,
        "tomado": round(ahora, 1),
        "estado": estado,
        "pulso": {"estado": pulso, "hace_s": hace,
                  "ultimo": ultimo_fino.get("ts") or ultimo_salud.get("ts")},
        "equipo": equipo,
        "router": router,
        "ultimo_corte": _publico(ultimo_corte),
        "ultimo_reinicio": _publico(ultimo_reinicio),
        "ultimo_veredicto": _publico(ultimo_veredicto),
        "cuentas_30d": {
            "cortes": sum(1 for e in recientes if e["tipo"].startswith("CORTE-DE-LUZ")),
            "reinicios": sum(1 for e in recientes if e["tipo"] == "REINICIO"),
            "paradas": sum(1 for e in recientes if e["tipo"] == "SALTO-DE-RELOJ"),
        },
        "ruido_24h": ruido_24h,
        "eventos": [_publico(e) for e in reversed(importantes)],
    }


def registro(clave: str, lineas: int = 80) -> dict:
    """Las últimas líneas de uno de los tres logs, tal cual."""
    if clave not in FICHEROS:
        return {"disponible": False, "motivo": "Registro desconocido."}
    lineas = max(10, min(int(lineas or 80), 400))
    filas = cola(clave, lineas)
    return {"disponible": bool(filas), "fichero": FICHEROS[clave], "lineas": filas,
            "motivo": None if filas else "El registro está vacío o no se puede leer."}


def latidos_cerca(momento: str, minutos: int = 15, maximo: int = 60) -> list[str]:
    """Latidos de minuto (health.log y sus rotaciones) alrededor de un instante.

    Sirve para ver cómo estaba la máquina justo antes de un corte o un reinicio:
    temperatura, carga, memoria, presión de E/S, procesos atascados…
    """
    centro = _epoch(momento)
    if centro is None:
        return []
    margen = max(1, min(int(minutos or 15), 120)) * 60
    salida: list[tuple[float, str]] = []
    base = _ruta("health")
    for ruta in [base] + [f"{base}.{n}" for n in range(1, 6)]:
        try:
            with open(ruta, "rb") as fh:
                texto = fh.read().replace(b"\x00", b"").decode("utf-8", "replace")
        except OSError:
            continue
        for linea in texto.splitlines():
            if not linea.startswith("ts="):
                continue
            t = _epoch(linea[3:linea.find(" ")] if " " in linea else linea[3:])
            if t is not None and abs(t - centro) <= margen:
                salida.append((t, linea))
    salida.sort()
    filas = [l for _, l in salida]
    if len(filas) > maximo:  # se quedan las más cercanas al instante
        filas = sorted(salida, key=lambda x: abs(x[0] - centro))[:maximo]
        filas = [l for _, l in sorted(filas)]
    return filas
