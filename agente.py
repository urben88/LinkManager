"""
agente.py — el asistente de LinkManager.

POR QUÉ EXISTE
--------------
El portal solo sabía recibir entradas a mano, una por una: título, sección y
enlaces. Lo pesado no es rellenar el formulario, es LEER los enlaces y decidir
dónde va cada cosa. Este módulo añade un agente que hace ese trabajo y que
NUNCA escribe en la base de datos por su cuenta:

    1. el usuario cuenta lo que quiere y pega URLs;
    2. el agente las lee (herramientas de LangChain) y mira qué hay ya en el
       portal para no duplicar nada;
    3. cuando lo tiene claro, llama a `proponer_plan`, que solo GUARDA una
       propuesta pendiente;
    4. la interfaz enseña la propuesta y el usuario pulsa «Aplicar» o
       «Descartar». Solo entonces `aplicar_propuesta()` toca la base de datos,
       en una única transacción.

Es decir: el modelo propone, la persona aprueba. Nunca hay un DELETE en el
camino del agente, y una propuesta no se puede aplicar dos veces.

DECISIONES QUE CONVIENE NO DESHACER
-----------------------------------
· El estado de la conversación vive en SQLite, no en memoria: gunicorn corre
  4 workers y cada petición puede caer en uno distinto. Con memoria, el hilo
  se cortaría al azar.
· El bucle de herramientas es explícito (bind_tools + tool_calls), no un
  AgentExecutor: hay que poder cortar por número de pasos, por tiempo y por
  error de la API sin que el portal se caiga. Un fallo del modelo devuelve un
  mensaje de error, jamás una excepción que rompa la vista.
· Los nombres de sección se resuelven por nombre (sin distinguir mayúsculas),
  porque el modelo razona con nombres, no con ids. Si la sección no existe, se
  crea: una propuesta nunca queda a medias por un id inventado.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Callable, Literal, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langchain_core.messages import (AIMessage, HumanMessage, SystemMessage,
                                     ToolMessage)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
#  Límites (todos deliberadamente bajos: es un portal, no un chat general)
# --------------------------------------------------------------------------

MAX_TEXTO_ENLACE = 4000          # caracteres de texto útil por enlace
MAX_ENLACES_POR_LLAMADA = 6      # el modelo puede pedir varios de golpe
MAX_PASOS = 8                    # vueltas de herramientas por mensaje
MAX_INTENTOS_PLAN = 3            # validaciones de la propuesta antes de rendirse
MAX_HISTORIAL = 20               # mensajes que se le pasan al modelo
MAX_MENSAJE = 8000               # longitud máxima de un mensaje del usuario
MAX_ENTRADAS_PLAN = 40
MAX_SECCIONES_PLAN = 12
MAX_URLS_ENTRADA = 8
TIPOS_ENLACE = ("external_url", "internal_app", "subdomain")


# --------------------------------------------------------------------------
#  Configuración (por entorno; todo se puede apagar sin tocar código)
# --------------------------------------------------------------------------

def activo() -> bool:
    return os.environ.get("AGENTE_ACTIVO", "1").strip().lower() not in ("0", "false", "no")


def clave_api() -> str:
    return (os.environ.get("AGENTE_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or "").strip()


def disponible() -> bool:
    """¿Se puede usar el asistente? Sin clave, el panel no se ofrece."""
    return activo() and bool(clave_api())


def modelo() -> str:
    return os.environ.get("AGENTE_MODELO", "deepseek-chat").strip()


def base_url() -> str:
    return os.environ.get("AGENTE_BASE_URL", "https://api.deepseek.com/v1").strip()


def leer_internas() -> bool:
    """Permite al agente leer URLs de la LAN (192.168.0.100:puerto, etc.).

    Va activado por defecto A PROPÓSITO: el portal es el índice de los
    servicios de la casa y la mitad de sus enlaces son internos. Solo se llega
    aquí con sesión iniciada. Nunca se leen direcciones link-local
    (169.254.169.254 y compañía), ni esquemas que no sean http/https.
    """
    return os.environ.get("AGENTE_LEER_INTERNAS", "1").strip().lower() not in ("0", "false", "no")


def _segundos(nombre: str, defecto: float) -> float:
    try:
        return float(os.environ.get(nombre, defecto))
    except (TypeError, ValueError):
        return defecto


# --------------------------------------------------------------------------
#  Esquema de la conversación y de las propuestas
# --------------------------------------------------------------------------

ESQUEMA = """
CREATE TABLE IF NOT EXISTS agente_conversaciones (
    id          TEXT PRIMARY KEY,
    creada      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizada TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agente_mensajes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversacion_id TEXT NOT NULL,
    rol             TEXT NOT NULL,          -- 'user' | 'assistant'
    contenido       TEXT NOT NULL,
    traza           TEXT,                   -- JSON con las herramientas usadas
    creada          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agente_propuestas (
    id               TEXT PRIMARY KEY,
    conversacion_id  TEXT NOT NULL,
    plan_json        TEXT NOT NULL,
    estado           TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente|aplicada|descartada
    resultado_json   TEXT,
    creada           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resuelta         TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agente_mensajes_conv
    ON agente_mensajes (conversacion_id, id);
"""


def preparar(db_path: str) -> None:
    """Crea las tablas del agente si faltan. Idempotente y seguro entre workers."""
    db = sqlite3.connect(db_path, timeout=15)
    try:
        db.executescript(ESQUEMA)
        db.commit()
    finally:
        db.close()


def _conectar(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(db_path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 15000")
    return db


# --------------------------------------------------------------------------
#  Entorno: lo que el agente necesita del resto de la aplicación
# --------------------------------------------------------------------------

@dataclass
class Entorno:
    """Lo que app.py presta al agente para no duplicar la guarda anti-SSRF."""
    db_path: str
    permitir_url: Optional[Callable[[str], bool]] = None

    def url_permitida(self, url: str) -> bool:
        if not url or not isinstance(url, str):
            return False
        if not url.startswith(("http://", "https://")):
            return False
        partes = urlparse(url)
        if not partes.hostname:
            return False
        if self.permitir_url is not None and not leer_internas():
            return bool(self.permitir_url(url))
        # Nunca link-local / metadata de nube, aunque se lean internas.
        host = partes.hostname.lower()
        if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return True
        if host.startswith("169.254.") or host in ("metadata.google.internal",):
            return False
        return True


# --------------------------------------------------------------------------
#  Lectura de una página (solo texto útil, con límites)
# --------------------------------------------------------------------------

def _limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def leer_pagina(url: str, entorno: Entorno) -> dict:
    """Devuelve título, descripción, imagen y texto de una URL. Nunca lanza."""
    salida = {"url": url, "ok": False, "titulo": "", "descripcion": "",
              "imagen": "", "texto": "", "error": ""}
    if not entorno.url_permitida(url):
        salida["error"] = "dirección no permitida (solo http/https, sin metadata interna)"
        return salida
    try:
        respuesta = requests.get(
            url, timeout=_segundos("AGENTE_TIMEOUT_WEB", 12), allow_redirects=True,
            headers={"User-Agent": "LinkManager/2.0 (+https://urbenserver.com)"},
            stream=True)
        respuesta.raise_for_status()
        tipo = respuesta.headers.get("Content-Type", "")
        if "html" not in tipo and "text" not in tipo:
            salida["error"] = f"no es una página de texto ({tipo or 'sin tipo'})"
            return salida

        trozos, tam = [], 0
        for trozo in respuesta.iter_content(16384):
            trozos.append(trozo)
            tam += len(trozo)
            if tam > 400_000:
                break
        sopa = BeautifulSoup(b"".join(trozos), "html.parser")

        def meta(propiedad=None, nombre=None):
            etiqueta = (sopa.find("meta", property=propiedad) if propiedad
                        else sopa.find("meta", attrs={"name": nombre}))
            return _limpiar(etiqueta.get("content", "")) if etiqueta else ""

        for ruido in sopa(["script", "style", "noscript", "svg", "iframe"]):
            ruido.decompose()
        titulo = meta(propiedad="og:title") or _limpiar(sopa.title.string if sopa.title and sopa.title.string else "")

        # og:image puede venir relativa ("/img/foto.png"): sin resolverla contra
        # la URL final, la tarjeta se queda sin portada y parece rota.
        imagen = meta(propiedad="og:image")
        if imagen:
            imagen = urljoin(respuesta.url or url, imagen)
            if not imagen.startswith(("http://", "https://")):
                imagen = ""

        salida.update({
            "ok": True,
            "titulo": titulo,
            "descripcion": meta(propiedad="og:description") or meta(nombre="description"),
            "imagen": imagen,
            "texto": _limpiar(sopa.get_text(" "))[:MAX_TEXTO_ENLACE],
            "final": respuesta.url,
        })
        return salida
    except Exception as exc:  # red, TLS, DNS, timeouts…
        salida["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return salida


# --------------------------------------------------------------------------
#  Instantánea del portal (para que el modelo no invente secciones)
# --------------------------------------------------------------------------

def _secciones(db_path: str) -> list[dict]:
    db = _conectar(db_path)
    try:
        filas = db.execute(
            "SELECT s.id, s.name, (SELECT COUNT(*) FROM link_entries e WHERE e.section_id = s.id) AS n "
            "FROM sections s ORDER BY s.order_index, s.name").fetchall()
        return [dict(f) for f in filas]
    finally:
        db.close()


def _resumen_portal(db_path: str) -> str:
    secciones = _secciones(db_path)
    if not secciones:
        return "El portal está vacío: no hay ninguna sección todavía."
    partes = [f"- {s['name']} ({s['n']} entradas)" for s in secciones]
    return "Secciones actuales del portal:\n" + "\n".join(partes)


def _buscar(db_path: str, texto: str, limite: int = 12) -> list[dict]:
    aguja = f"%{(texto or '').lower()}%"
    db = _conectar(db_path)
    try:
        filas = db.execute(
            "SELECT e.id, e.title, e.description, s.name AS seccion, e.parent_id "
            "FROM link_entries e LEFT JOIN sections s ON s.id = e.section_id "
            "WHERE lower(e.title) LIKE ? OR lower(coalesce(e.description,'')) LIKE ? "
            "   OR EXISTS (SELECT 1 FROM entry_urls u WHERE u.link_entry_id = e.id "
            "              AND lower(u.value) LIKE ?) "
            "ORDER BY e.title LIMIT ?", (aguja, aguja, aguja, limite)).fetchall()
        return [dict(f) for f in filas]
    finally:
        db.close()


def _inventario(db_path: str, limite: int = 200) -> list[dict]:
    db = _conectar(db_path)
    try:
        filas = db.execute(
            "SELECT e.id, e.title, s.name AS seccion, e.parent_id "
            "FROM link_entries e LEFT JOIN sections s ON s.id = e.section_id "
            "ORDER BY s.order_index, e.order_index LIMIT ?", (limite,)).fetchall()
        return [dict(f) for f in filas]
    finally:
        db.close()


# --------------------------------------------------------------------------
#  Plan que propone el modelo
# --------------------------------------------------------------------------

class UrlPropuesta(BaseModel):
    """Un enlace dentro de una entrada."""

    valor: str = Field(description="URL completa, puerto (solo el número) o subdominio")
    etiqueta: str = Field(default="", description="Texto del chip; vacío = el que salga del valor")
    tipo: Literal["external_url", "internal_app", "subdomain"] = Field(
        default="external_url",
        description=("external_url = URL http(s) completa; internal_app = solo el PUERTO de un "
                     "servicio de la LAN (ej. '8096'); subdomain = host exacto del proxy "
                     "(ej. 'jellyfin.urbenserver.com')"))


class EntradaPropuesta(BaseModel):
    """Una tarjeta nueva del portal."""

    titulo: str = Field(description="Título corto de la tarjeta")
    seccion: str = Field(description="Nombre EXACTO de una sección existente o de las nuevas")
    descripcion: str = Field(default="", description="Una frase: para qué sirve")
    dentro_de: str = Field(default="", description=(
        "Título de la entrada (de esta misma propuesta o ya existente en la sección) que la "
        "contendrá, para hacer un grupo/carpeta. Vacío = entrada de primer nivel."))
    urls: list[UrlPropuesta] = Field(default_factory=list)


class Movimiento(BaseModel):
    """Mover una entrada (y lo que cuelga de ella) a otra sección."""

    entrada: str = Field(description="Título exacto o id de la entrada que se mueve")
    seccion_destino: str = Field(description="Nombre de la sección de destino")


class PlanPropuesta(BaseModel):
    """El cambio completo que se propone al usuario."""

    resumen: str = Field(description="Dos o tres frases: qué se va a crear y por qué")
    secciones_nuevas: list[str] = Field(default_factory=list,
                                        description="Nombres de secciones que hay que crear")
    entradas: list[EntradaPropuesta] = Field(default_factory=list)
    movimientos: list[Movimiento] = Field(default_factory=list)


# --------------------------------------------------------------------------
#  Herramientas
# --------------------------------------------------------------------------

def _herramientas(entorno: Entorno, caja: dict) -> list:
    """Las herramientas que ve el modelo. `caja` recoge la propuesta creada."""

    @tool
    def leer_enlaces(urls: list[str]) -> str:
        """Lee el contenido de una o varias URLs (máx. 6) y devuelve su título,
        descripción, imagen social y texto útil. Úsalo antes de proponer nada."""
        if not isinstance(urls, list):
            urls = [str(urls)]
        urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()][:MAX_ENLACES_POR_LLAMADA]
        if not urls:
            return "No has pasado ninguna URL."
        salida = []
        for url in urls:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            datos = leer_pagina(url, entorno)
            if datos["ok"]:
                salida.append(
                    f"### {datos['url']}\n"
                    f"título: {datos['titulo']}\n"
                    f"descripción: {datos['descripcion']}\n"
                    f"imagen: {datos['imagen']}\n"
                    f"texto: {datos['texto'][:MAX_TEXTO_ENLACE]}")
            else:
                salida.append(f"### {url}\nNo se pudo leer: {datos['error']}")
        return "\n\n".join(salida)

    @tool
    def consultar_portal() -> str:
        """Devuelve las secciones del portal y lo que hay dentro de cada una.
        Úsalo para decidir dónde encaja algo o si ya existe."""
        db = _conectar(entorno.db_path)
        try:
            secciones = db.execute(
                "SELECT id, name FROM sections ORDER BY order_index, name").fetchall()
            if not secciones:
                return "El portal está vacío: no hay secciones ni entradas."
            lineas = []
            for s in secciones:
                lineas.append(f"## {s['name']} (id {s['id']})")
                entradas = db.execute(
                    "SELECT id, title, description, parent_id FROM link_entries "
                    "WHERE section_id = ? ORDER BY order_index", (s["id"],)).fetchall()
                if not entradas:
                    lineas.append("  (vacía)")
                for e in entradas:
                    marca = "  · (dentro de otra)" if e["parent_id"] else "  ·"
                    desc = f" — {e['description']}" if e["description"] else ""
                    lineas.append(f"{marca} [{e['id']}] {e['title']}{desc}")
                    for u in db.execute("SELECT label, link_type, value FROM entry_urls "
                                        "WHERE link_entry_id = ?", (e["id"],)).fetchall():
                        lineas.append(f"      - {u['link_type']}: {u['value']}")
            return "\n".join(lineas)
        finally:
            db.close()

    @tool
    def buscar_en_portal(texto: str) -> str:
        """Busca entradas por título, descripción o URL. Para no duplicar tarjetas."""
        filas = _buscar(entorno.db_path, texto)
        if not filas:
            return f"Nada coincide con «{texto}»."
        return "\n".join(
            f"- [{f['id']}] {f['title']} (sección: {f['seccion']})"
            for f in filas)

    @tool
    def proponer_plan(resumen: str = "", secciones_nuevas: list[str] = [],
                      entradas: list[EntradaPropuesta] = [],
                      movimientos: list[Movimiento] = []) -> str:
        """Guarda una PROPUESTA que el usuario aprobará con un botón. No escribe
        nada todavía. Llama a esta herramienta solo cuando tengas claro el plan;
        si falta información, pregunta antes en el chat.

        Cada entrada lleva: titulo, seccion, descripcion, dentro_de (opcional,
        título de la entrada que la contiene para hacer una carpeta) y urls, una
        lista de {"valor": "...", "etiqueta": "...", "tipo": "external_url" |
        "internal_app" | "subdomain"}.
        Cada movimiento es {"entrada": "título o id", "seccion_destino": "nombre"}.
        No existe la opción de borrar: no la ofrezcas.

        La propuesta se VALIDA: si algo no cumple, esta herramienta te devuelve
        los errores y puedes corregirla y volver a llamarla, pero solo hay unos
        pocos intentos. Cuando se agoten, no hay propuesta."""
        maximo = intentos_max()
        intentos = int(caja.get("intentos", 0))
        if intentos >= maximo:
            caja["fallido"] = "sin-intentos"
            return ("No quedan intentos de validación. No vuelvas a llamar a esta herramienta: "
                    "dile al usuario que no has podido generar una propuesta válida.")

        intentos += 1
        caja["intentos"] = intentos

        try:
            plan = PlanPropuesta(
                resumen=str(resumen or "")[:600],
                secciones_nuevas=[str(s).strip() for s in (secciones_nuevas or []) if str(s).strip()],
                entradas=[EntradaPropuesta(**e) if isinstance(e, dict) else e for e in (entradas or [])],
                movimientos=[Movimiento(**m) if isinstance(m, dict) else m for m in (movimientos or [])])
        except Exception as exc:
            caja["ultimos_errores"] = [str(exc)[:200]]
            return (f"Intento {intentos}/{maximo} fallido: la propuesta no cumple el esquema "
                    f"({str(exc)[:300]}). Corrige la estructura y vuelve a llamar a proponer_plan.")

        limpio, errores, avisos = _validar_plan(entorno.db_path, plan)
        if errores:
            caja["ultimos_errores"] = errores
            detalle = "; ".join(errores[:6])
            if intentos >= maximo:
                caja["fallido"] = "validacion"
                return (f"Intento {intentos}/{maximo} fallido, y no quedan más: {detalle}. "
                        f"No se ha guardado ninguna propuesta: avisa al usuario.")
            return (f"Intento {intentos}/{maximo} fallido. La propuesta NO pasa la validación: "
                    f"{detalle}. Corrige exactamente eso y vuelve a llamar a proponer_plan.")

        propuesta_id = uuid.uuid4().hex[:12]
        db = _conectar(entorno.db_path)
        try:
            db.execute("INSERT INTO agente_propuestas (id, conversacion_id, plan_json) VALUES (?, ?, ?)",
                       (propuesta_id, caja.get("conversacion_id", ""),
                        json.dumps(limpio, ensure_ascii=False)))
            db.commit()
        finally:
            db.close()
        caja["propuesta_id"] = propuesta_id
        caja["propuesta"] = limpio
        caja["avisos"] = avisos
        avisos_txt = (" Avisos: " + "; ".join(avisos[:5])) if avisos else ""
        return (f"Propuesta {propuesta_id} válida y guardada, enviada al usuario para que la "
                f"apruebe.{avisos_txt} Resume en una línea qué has propuesto y no llames a más "
                f"herramientas.")

    return [leer_enlaces, consultar_portal, buscar_en_portal, proponer_plan]


# --------------------------------------------------------------------------
#  Validación del plan (server-side: el modelo no manda)
# --------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto)


VERSION_PLAN = 1


def intentos_max() -> int:
    """Cuántas veces se le puede pedir al modelo que arregle su propuesta."""
    try:
        n = int(os.environ.get("AGENTE_INTENTOS", MAX_INTENTOS_PLAN))
    except (TypeError, ValueError):
        n = MAX_INTENTOS_PLAN
    return max(1, min(n, 6))


def _problema_url(tipo: str, valor: str) -> str:
    """Motivo por el que un enlace no vale. Cadena vacía = vale."""
    if tipo == "internal_app":
        if not valor.isdigit() or not 1 <= int(valor) <= 65535:
            return "el puerto tiene que ser un número entre 1 y 65535"
        return ""
    if tipo == "subdomain":
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", valor):
            return "un subdominio tiene que llevar al menos un punto (ej. jellyfin.urbenserver.com)"
        return ""
    partes = urlparse(valor)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return "la URL externa no empieza por http:// o https://"
    if "." not in partes.hostname and partes.hostname != "localhost":
        return f"«{partes.hostname}» no es un dominio"
    return ""


def _validar_plan(db_path: str, plan: PlanPropuesta) -> tuple[dict, list[str], list[str]]:
    """Valida y sanea la propuesta.

    Devuelve (plan_limpio, errores, avisos):

      · `errores` → lo que el modelo tiene que CORREGIR. Si hay alguno, la
        propuesta no se guarda y se le devuelve la lista para que lo reintente
        (hasta `intentos_max()` veces).
      · `avisos`  → cosas que dependen de lo que ya hay en el portal y que
        reintentar no arregla: la sección ya existe, la entrada está duplicada,
        el grupo no aparece… Se aplican igual y se le enseñan al usuario.
    """
    errores: list[str] = []
    avisos: list[str] = []
    existentes = {_normalizar(s["name"]): s["name"] for s in _secciones(db_path)}

    resumen = re.sub(r"\s+", " ", (plan.resumen or "")).strip()[:600]
    if not resumen:
        errores.append("falta el resumen: una o dos frases con lo que propones")

    if len(plan.entradas) > MAX_ENTRADAS_PLAN:
        errores.append(f"demasiadas entradas ({len(plan.entradas)}); el máximo es "
                       f"{MAX_ENTRADAS_PLAN}: divide la propuesta en varias")
    if len(plan.secciones_nuevas) > MAX_SECCIONES_PLAN:
        errores.append(f"demasiadas secciones nuevas (máximo {MAX_SECCIONES_PLAN})")

    nuevas: list[str] = []
    for nombre in plan.secciones_nuevas[:MAX_SECCIONES_PLAN]:
        nombre = re.sub(r"\s+", " ", nombre).strip()
        if not nombre:
            errores.append("hay una sección nueva sin nombre")
            continue
        if len(nombre) > 60:
            errores.append(f"el nombre de sección «{nombre[:30]}…» pasa de 60 caracteres")
            continue
        if _normalizar(nombre) in existentes:
            avisos.append(f"la sección «{nombre}» ya existe, se usa la que hay")
            continue
        if _normalizar(nombre) not in {_normalizar(n) for n in nuevas}:
            nuevas.append(nombre)
            existentes[_normalizar(nombre)] = nombre

    entradas: list[dict] = []
    vistas: dict[tuple[str, str], int] = {}
    # Una entrada que solo hace de carpeta no necesita enlace propio: se acepta
    # sin `urls` si otra entrada de la propuesta cuelga de ella con `dentro_de`.
    # Así el modelo no tiene que repetir en el grupo los enlaces de sus hijas.
    padres_usados = {_normalizar(e.dentro_de) for e in plan.entradas if (e.dentro_de or "").strip()}
    for indice, entrada in enumerate(plan.entradas, 1):
        titulo = re.sub(r"\s+", " ", (entrada.titulo or "")).strip()
        etiqueta = f"entrada {indice} («{titulo or 'sin título'}»)"
        if not titulo:
            errores.append(f"{etiqueta}: falta el título")
        elif len(titulo) > 90:
            errores.append(f"{etiqueta}: el título pasa de 90 caracteres")

        seccion = re.sub(r"\s+", " ", (entrada.seccion or "")).strip()
        if not seccion:
            errores.append(f"{etiqueta}: falta la sección")
            continue
        if len(seccion) > 60:
            errores.append(f"{etiqueta}: el nombre de sección pasa de 60 caracteres")
            continue
        if _normalizar(seccion) not in existentes:
            if len(nuevas) < MAX_SECCIONES_PLAN:
                nuevas.append(seccion)
                existentes[_normalizar(seccion)] = seccion
                avisos.append(f"la sección «{seccion}» no existía: se creará")
            else:
                errores.append(f"{etiqueta}: la sección «{seccion}» no existe y ya hay "
                               f"{MAX_SECCIONES_PLAN} secciones nuevas")
                continue

        es_carpeta = _normalizar(titulo) in padres_usados
        if not entrada.urls and not es_carpeta:
            errores.append(f"{etiqueta}: no tiene ningún enlace")
            continue
        if len(entrada.urls) > MAX_URLS_ENTRADA:
            errores.append(f"{etiqueta}: tiene más de {MAX_URLS_ENTRADA} enlaces")

        urls = []
        for url in (entrada.urls or [])[:MAX_URLS_ENTRADA]:
            valor = (url.valor or "").strip()[:500]
            tipo = url.tipo if url.tipo in TIPOS_ENLACE else "external_url"
            if tipo == "internal_app":
                valor = re.sub(r"\D", "", valor)
            elif tipo == "external_url" and not valor.startswith(("http://", "https://")):
                valor = "https://" + valor.lstrip("/")
            if not valor:
                if tipo == "internal_app":
                    errores.append(f"{etiqueta}: el puerto tiene que ser un número "
                                   f"(llegó «{(url.valor or '')[:20]}»)")
                else:
                    errores.append(f"{etiqueta}: hay un enlace vacío")
                continue
            problema = _problema_url(tipo, valor.lower() if tipo != "external_url" else valor)
            if problema:
                errores.append(f"{etiqueta}: {problema} (valor: «{valor[:40]}»)")
                continue
            urls.append({"valor": valor, "etiqueta": (url.etiqueta or "").strip()[:40], "tipo": tipo})

        if not urls and not es_carpeta:
            errores.append(f"{etiqueta}: ningún enlace válido")
            continue

        clave = (_normalizar(seccion), _normalizar(titulo))
        if clave in vistas:
            errores.append(f"{etiqueta}: ya hay otra entrada con ese título en la misma sección")
            continue
        vistas[clave] = indice

        entradas.append({
            "titulo": titulo,
            "seccion": existentes[_normalizar(seccion)],
            "descripcion": re.sub(r"\s+", " ", (entrada.descripcion or "")).strip()[:220],
            "dentro_de": re.sub(r"\s+", " ", (entrada.dentro_de or "")).strip()[:90],
            "urls": urls,
        })

    movimientos = []
    for indice, mov in enumerate(plan.movimientos[:20], 1):
        entrada = re.sub(r"\s+", " ", (mov.entrada or "")).strip()[:90]
        destino = re.sub(r"\s+", " ", (mov.seccion_destino or "")).strip()[:60]
        if not entrada or not destino:
            errores.append(f"movimiento {indice}: hacen falta la entrada y la sección de destino")
            continue
        movimientos.append({"entrada": entrada, "seccion_destino": destino})

    if not entradas and not movimientos and not errores:
        errores.append("la propuesta no crea ni mueve nada")

    limpio = {
        "version": VERSION_PLAN,
        "resumen": resumen,
        "secciones_nuevas": nuevas,
        "entradas": entradas,
        "movimientos": movimientos,
    }
    return limpio, errores, avisos


# --------------------------------------------------------------------------
#  Aplicar una propuesta (única escritura real)
# --------------------------------------------------------------------------

def _resolver_entrada(db: sqlite3.Connection, referencia: str) -> Optional[sqlite3.Row]:
    referencia = (referencia or "").strip()
    if not referencia:
        return None
    if referencia.isdigit():
        fila = db.execute("SELECT * FROM link_entries WHERE id = ?", (int(referencia),)).fetchone()
        if fila:
            return fila
    fila = db.execute("SELECT * FROM link_entries WHERE lower(title) = lower(?) "
                      "ORDER BY id LIMIT 1", (referencia,)).fetchone()
    if fila:
        return fila
    # último intento: coincidencia parcial, sin acentos
    for candidata in db.execute("SELECT * FROM link_entries").fetchall():
        if _normalizar(candidata["title"]) == _normalizar(referencia):
            return candidata
    return None


def _siguiente_orden(db: sqlite3.Connection, tabla: str, seccion: Optional[int] = None) -> int:
    if tabla == "sections":
        fila = db.execute("SELECT COALESCE(MAX(order_index), 0) FROM sections").fetchone()
    else:
        fila = db.execute("SELECT COALESCE(MAX(order_index), 0) FROM link_entries WHERE section_id = ?",
                          (seccion,)).fetchone()
    return int(fila[0]) + 1


def _imagen_de(urls: list[dict], entorno: Optional[Entorno]) -> str:
    """Portada a partir de la primera URL externa, como hace el alta manual."""
    if entorno is None:
        return ""
    for url in urls:
        if url["tipo"] == "external_url":
            datos = leer_pagina(url["valor"], entorno)
            if datos["ok"] and datos["imagen"]:
                return datos["imagen"][:500]
    return ""


def _portadas_previas(plan: dict, entorno: Entorno, limite: int = 12) -> dict[str, str]:
    """Busca una portada para cada entrada ANTES de abrir la transacción.

    Es una petición de red por enlace: si se hiciera dentro del BEGIN IMMEDIATE,
    el candado de escritura de SQLite se quedaría esperando a una web ajena y
    otro worker no podría guardar nada. Se limita a `limite` para que aplicar
    40 tarjetas no se convierta en cuarenta descargas.
    """
    salida: dict[str, str] = {}
    if not entorno or not activo():
        return salida
    for entrada in plan.get("entradas", [])[:limite]:
        urls = entrada.get("urls") or []
        if not any(u.get("tipo") == "external_url" for u in urls):
            continue
        imagen = _imagen_de(urls, entorno)
        if imagen:
            salida[_normalizar(entrada.get("titulo", ""))] = imagen
    return salida


def aplicar_propuesta(db_path: str, propuesta_id: str,
                      entorno: Optional[Entorno] = None) -> dict:
    """Escribe la propuesta aprobada. Idempotente: la segunda vez no hace nada."""
    entorno = entorno or Entorno(db_path)
    db = _conectar(db_path)
    try:
        fila = db.execute("SELECT * FROM agente_propuestas WHERE id = ?", (propuesta_id,)).fetchone()
        if not fila:
            return {"ok": False, "error": "La propuesta no existe."}
        if fila["estado"] != "pendiente":
            return {"ok": False, "error": f"Esa propuesta ya está {fila['estado']}."}
        plan = json.loads(fila["plan_json"])

        # Red primero, candado después (ver _portadas_previas).
        portadas = _portadas_previas(plan, entorno)

        db.execute("BEGIN IMMEDIATE")
        # Se relee bajo el candado: otro worker podría haberla aplicado mientras
        # se descargaban las portadas.
        fila = db.execute("SELECT estado FROM agente_propuestas WHERE id = ?",
                          (propuesta_id,)).fetchone()
        if not fila or fila["estado"] != "pendiente":
            db.rollback()
            return {"ok": False, "error": "Esa propuesta ya se había resuelto."}

        resultado: dict = {"secciones": [], "entradas": [], "movidas": [], "omitidas": [], "avisos": []}

        # 1) Secciones: se reutiliza la que ya exista con ese nombre normalizado
        mapa_secciones = {_normalizar(s["name"]): s["id"]
                         for s in db.execute("SELECT id, name FROM sections").fetchall()}
        for nombre in plan.get("secciones_nuevas", []):
            clave = _normalizar(nombre)
            if clave in mapa_secciones:
                continue
            cur = db.execute("INSERT INTO sections (name, order_index) VALUES (?, ?)",
                             (nombre, _siguiente_orden(db, "sections")))
            mapa_secciones[clave] = cur.lastrowid
            resultado["secciones"].append(nombre)

        # 2) Entradas (primero todas, para poder resolver los padres después)
        creadas: dict[str, int] = {}
        for entrada in plan.get("entradas", []):
            clave_seccion = _normalizar(entrada["seccion"])
            seccion_id = mapa_secciones.get(clave_seccion)
            if seccion_id is None:
                resultado["omitidas"].append(f"{entrada['titulo']}: la sección no existe")
                continue
            repetida = db.execute(
                "SELECT id FROM link_entries WHERE section_id = ? AND lower(title) = lower(?)",
                (seccion_id, entrada["titulo"])).fetchone()
            if repetida:
                resultado["omitidas"].append(f"{entrada['titulo']}: ya existe en esa sección")
                creadas[_normalizar(entrada["titulo"])] = repetida["id"]
                continue
            imagen = portadas.get(_normalizar(entrada["titulo"]), "")
            cur = db.execute(
                "INSERT INTO link_entries (title, description, image_url, section_id, parent_id, order_index) "
                "VALUES (?, ?, ?, ?, NULL, ?)",
                (entrada["titulo"], entrada["descripcion"], imagen or None, seccion_id,
                 _siguiente_orden(db, "link_entries", seccion_id)))
            nuevo_id = cur.lastrowid
            creadas[_normalizar(entrada["titulo"])] = nuevo_id or 0
            for url in entrada["urls"]:
                db.execute("INSERT INTO entry_urls (link_entry_id, label, link_type, value) "
                           "VALUES (?, ?, ?, ?)",
                           (nuevo_id, url["etiqueta"], url["tipo"], url["valor"]))
            resultado["entradas"].append(entrada["titulo"])

        # 3) Grupos: «dentro_de» puede apuntar a una entrada de esta propuesta o a una ya existente
        for entrada in plan.get("entradas", []):
            padre_ref = (entrada.get("dentro_de") or "").strip()
            if not padre_ref:
                continue
            hijo_id = creadas.get(_normalizar(entrada["titulo"]))
            if not hijo_id:
                continue
            padre_id = creadas.get(_normalizar(padre_ref))
            if padre_id is None:
                padre = _resolver_entrada(db, padre_ref)
                padre_id = padre["id"] if padre else None
            if not padre_id or padre_id == hijo_id:
                resultado["avisos"].append(f"{entrada['titulo']}: no se encontró «{padre_ref}»")
                continue
            padre = db.execute("SELECT id, section_id, parent_id FROM link_entries WHERE id = ?",
                               (padre_id,)).fetchone()
            hijo = db.execute("SELECT section_id FROM link_entries WHERE id = ?", (hijo_id,)).fetchone()
            # solo dos niveles, y siempre dentro de la misma sección
            if padre["parent_id"] or padre["section_id"] != hijo["section_id"]:
                resultado["avisos"].append(f"{entrada['titulo']}: «{padre_ref}» no puede ser su grupo")
                continue
            db.execute("UPDATE link_entries SET parent_id = ? WHERE id = ?", (padre_id, hijo_id))

        # 4) Movimientos entre secciones (arrastrando a los hijos del grupo)
        for mov in plan.get("movimientos", []):
            entrada = _resolver_entrada(db, mov["entrada"])
            if not entrada:
                resultado["omitidas"].append(f"{mov['entrada']}: no se encontró esa entrada")
                continue
            destino_id = mapa_secciones.get(_normalizar(mov["seccion_destino"]))
            if destino_id is None:
                resultado["omitidas"].append(
                    f"{mov['entrada']}: la sección «{mov['seccion_destino']}» no existe")
                continue
            if entrada["section_id"] == destino_id:
                continue
            db.execute("UPDATE link_entries SET section_id = ?, order_index = ? WHERE id = ?",
                       (destino_id, _siguiente_orden(db, "link_entries", destino_id), entrada["id"]))
            db.execute("UPDATE link_entries SET section_id = ? WHERE parent_id = ?",
                       (destino_id, entrada["id"]))
            resultado["movidas"].append(f"{entrada['title']} → {mov['seccion_destino']}")

        db.execute("UPDATE agente_propuestas SET estado = 'aplicada', resuelta = CURRENT_TIMESTAMP, "
                   "resultado_json = ? WHERE id = ?",
                   (json.dumps(resultado, ensure_ascii=False), propuesta_id))
        db.commit()
        resultado["ok"] = True
        return resultado
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        db.close()


def descartar_propuesta(db_path: str, propuesta_id: str) -> dict:
    db = _conectar(db_path)
    try:
        cur = db.execute("UPDATE agente_propuestas SET estado = 'descartada', "
                         "resuelta = CURRENT_TIMESTAMP WHERE id = ? AND estado = 'pendiente'",
                         (propuesta_id,))
        db.commit()
        return {"ok": bool(cur.rowcount)}
    finally:
        db.close()


# --------------------------------------------------------------------------
#  Prompt
# --------------------------------------------------------------------------

INSTRUCCIONES = """Eres el asistente de LinkManager, el portal de enlaces de urbsenserver.
Ayudas a su dueño a mantenerlo: lee los enlaces que te pasa y le propone entradas
nuevas, secciones nuevas y grupos (carpetas). Escribes en español de España,
breve y concreto, sin florituras ni listas interminables.

CÓMO TRABAJAS
1. Si el mensaje trae URLs, léelas con `leer_enlaces` antes de opinar.
2. Mira qué hay ya con `consultar_portal` o `buscar_en_portal` para no duplicar
   tarjetas y para reutilizar las secciones que ya existen.
3. Si falta un dato que cambia el resultado (en qué sección va, cómo agrupar,
   qué título prefiere), PREGUNTA en el chat y espera. No propongas a ciegas.
4. Cuando lo tengas claro, llama a `proponer_plan` UNA vez con el plan completo
   y luego contesta con dos o tres frases: qué propones y por qué. El usuario
   verá la propuesta con botones Aplicar / Descartar: no le pidas que confirme
   por escrito, ya tiene el botón.

TEXTO DESORDENADO
El usuario puede pegarte texto sin ordenar —notas, una lista de la compra de
apps, un copiar y pegar de un chat, nombres sueltos con enlaces a mitad—. Eso es
lo normal, no un error: tu trabajo es REORGANIZARLO.
- Saca de ahí las entradas: un nombre y sus enlaces.
- Agrupa por tema y elige el nombre de sección que mejor encaje con las que ya
  hay; crea una nueva solo si ninguna sirve.
- Cuando varias cosas son del mismo tipo (por ejemplo, varios servicios de
  descargas), conviértelas en un grupo: una entrada-carpeta y las demás
  `dentro_de` ella.
- Normaliza títulos y descripciones; no copies la frase entera del texto pegado.
- Si el texto no trae NI UN enlace, no inventes URLs ni puertos: pregunta por
  ellas. Una entrada sin enlace no vale y la validación la rechaza.
- Excepción: si una entrada es SOLO una carpeta (otras cuelgan de ella con
  `dentro_de`), puede ir sin `urls`. No le repitas los enlaces de sus hijas.

LA PROPUESTA ES UN JSON CON ESTA FORMA FIJA
{
  "version": 1,
  "resumen": "una o dos frases",
  "secciones_nuevas": ["Nombre"],
  "entradas": [
    {"titulo": "...", "seccion": "...", "descripcion": "...",
     "dentro_de": "",
     "urls": [{"valor": "...", "etiqueta": "...", "tipo": "external_url"}]}
  ],
  "movimientos": [{"entrada": "título o id", "seccion_destino": "Nombre"}]
}
Todos los campos son obligatorios salvo `dentro_de`, `descripcion` y
`etiqueta` (pueden ir vacíos), y `movimientos`/`secciones_nuevas` (pueden ir
vacíos). No añadas claves nuevas.

VALIDACIÓN E INTENTOS
`proponer_plan` valida ese JSON en el servidor. Si algo no cumple, te devuelve
la lista exacta de errores y puedes corregir y volver a llamarla, pero hay un
número LIMITADO de intentos (te lo dirá cada respuesta). Si se agotan, no habrá
propuesta: en ese caso dilo con claridad ("no he podido generar una propuesta
válida") y no te inventes que la has creado.

REGLAS DURAS
- No puedes borrar nada. No ofrezcas borrar, ni vaciar secciones. Solo crear y mover.
- Un `tipo` de enlace se elige así: `external_url` para una URL completa;
  `internal_app` cuando es un puerto de un servicio de este servidor (valor = solo
  el número, ej. "8096"); `subdomain` para un host del proxy (ej.
  "jellyfin.urbenserver.com"). Nunca inventes puertos ni subdominios.
- Los títulos son cortos (2-4 palabras) y las descripciones una sola frase.
- Usa los nombres de sección EXACTOS que devuelva `consultar_portal`. Puedes
  crear una sección nueva solo si de verdad no encaja en ninguna.
- Si una web no se puede leer, dilo y propón la entrada con lo que sepas por la
  URL; no te inventes su contenido.
- No repitas enlaces ni tarjetas que ya estén en el portal: si ya existe, dilo.
"""


# --------------------------------------------------------------------------
#  Conversación
# --------------------------------------------------------------------------

def _historial(db_path: str, conversacion_id: str) -> list[dict]:
    db = _conectar(db_path)
    try:
        filas = db.execute(
            "SELECT rol, contenido, traza FROM agente_mensajes WHERE conversacion_id = ? "
            "ORDER BY id DESC LIMIT ?", (conversacion_id, MAX_HISTORIAL)).fetchall()
        return [dict(f) for f in reversed(filas)]
    finally:
        db.close()


def _guardar_mensaje(db_path: str, conversacion_id: str, rol: str, contenido: str,
                     traza: Optional[list] = None) -> None:
    db = _conectar(db_path)
    try:
        db.execute("INSERT INTO agente_mensajes (conversacion_id, rol, contenido, traza) "
                   "VALUES (?, ?, ?, ?)",
                   (conversacion_id, rol, contenido,
                    json.dumps(traza, ensure_ascii=False) if traza else None))
        db.execute("UPDATE agente_conversaciones SET actualizada = CURRENT_TIMESTAMP WHERE id = ?",
                   (conversacion_id,))
        db.commit()
    finally:
        db.close()


def historial_visible(db_path: str, conversacion_id: str) -> dict:
    db = _conectar(db_path)
    try:
        mensajes = [dict(f) for f in db.execute(
            "SELECT rol, contenido, traza, creada FROM agente_mensajes "
            "WHERE conversacion_id = ? ORDER BY id", (conversacion_id,)).fetchall()]
        propuestas = [dict(f) for f in db.execute(
            "SELECT id, plan_json, estado FROM agente_propuestas "
            "WHERE conversacion_id = ? ORDER BY creada", (conversacion_id,)).fetchall()]
    finally:
        db.close()
    for m in mensajes:
        m["traza"] = json.loads(m["traza"]) if m["traza"] else []
    for p in propuestas:
        p["plan"] = json.loads(p["plan_json"])
        p.pop("plan_json", None)
    return {"mensajes": mensajes, "propuestas": propuestas}


def _crear_llm() -> ChatOpenAI:
    """El cliente del modelo. En una función aparte para poder sustituirlo en
    las pruebas sin tocar la red (monkeypatch de `agente._crear_llm`)."""
    return ChatOpenAI(model=modelo(), base_url=base_url(), api_key=clave_api(),
                      temperature=0.2, timeout=_segundos("AGENTE_TIMEOUT", 60),
                      max_retries=1)


def responder(db_path: str, conversacion_id: str, mensaje: str, entorno: Entorno) -> dict:
    """Un turno de conversación. Devuelve siempre un dict; nunca lanza."""
    mensaje = (mensaje or "").strip()
    if not mensaje:
        return {"ok": False, "error": "El mensaje está vacío."}
    if len(mensaje) > MAX_MENSAJE:
        return {"ok": False, "error": f"El mensaje es demasiado largo (máximo {MAX_MENSAJE} caracteres)."}
    if not disponible():
        return {"ok": False, "error": "El asistente no está configurado (falta AGENTE_API_KEY)."}

    caja: dict = {"conversacion_id": conversacion_id}
    herramientas = _herramientas(entorno, caja)
    por_nombre = {h.name: h for h in herramientas}

    try:
        llm_con_tools = _crear_llm().bind_tools(herramientas)
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo preparar el modelo: {exc}"[:300]}

    mensajes = [SystemMessage(INSTRUCCIONES + "\n\n" + _resumen_portal(db_path))]
    for m in _historial(db_path, conversacion_id):
        mensajes.append(HumanMessage(m["contenido"]) if m["rol"] == "user"
                        else AIMessage(m["contenido"]))
    mensajes.append(HumanMessage(mensaje))

    _guardar_mensaje(db_path, conversacion_id, "user", mensaje)

    traza: list[dict] = []
    respuesta_texto = ""
    error = ""
    for paso in range(MAX_PASOS):
        try:
            ai = llm_con_tools.invoke(mensajes)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            break

        mensajes.append(ai)
        llamadas = getattr(ai, "tool_calls", None) or []
        if not llamadas:
            respuesta_texto = (ai.content or "").strip()
            break

        for llamada in llamadas:
            nombre = llamada.get("name", "")
            argumentos = llamada.get("args") or {}
            herramienta = por_nombre.get(nombre)
            if herramienta is None:
                contenido = f"Herramienta desconocida: {nombre}"
            else:
                try:
                    contenido = herramienta.invoke(argumentos)
                except Exception as exc:
                    contenido = f"Error al ejecutar {nombre}: {type(exc).__name__}: {exc}"[:300]
            contenido = str(contenido)
            traza.append({"herramienta": nombre,
                          "resumen": _resumen_herramienta(nombre, argumentos, contenido)})
            mensajes.append(ToolMessage(content=contenido[:12000],
                                        tool_call_id=llamada.get("id", "")))
        if caja.get("propuesta_id"):
            # Ya hay propuesta guardada: se cierra el turno sin gastar más pasos
            if not respuesta_texto and (ai.content or "").strip():
                respuesta_texto = ai.content.strip()
            break
        if caja.get("fallido"):
            # Se agotaron los intentos de validación: no hay propuesta que enseñar
            break

    if error:
        texto = ("No he podido terminar la consulta. El modelo respondió con un error: "
                 f"{error}")
        _guardar_mensaje(db_path, conversacion_id, "assistant", texto, traza)
        return {"ok": False, "error": texto, "traza": traza}

    if caja.get("fallido") and not caja.get("propuesta_id"):
        detalle = "; ".join((caja.get("ultimos_errores") or [])[:5])
        respuesta_texto = (
            f"No he podido generar una propuesta válida después de {caja.get('intentos', 0)} "
            f"intento(s), así que no hay nada que aplicar y no he tocado el portal."
            + (f" Lo que no cumplía: {detalle}." if detalle else "")
            + " Prueba a dármelo en trozos más pequeños, con los enlaces uno a uno,"
              " o dime tú en qué sección va cada cosa.")
        _guardar_mensaje(db_path, conversacion_id, "assistant", respuesta_texto, traza)
        return {"ok": False, "fallido": True, "respuesta": respuesta_texto,
                "intentos": caja.get("intentos", 0), "traza": traza,
                "propuesta": None, "propuesta_id": None}

    if not respuesta_texto:
        if caja.get("propuesta_id"):
            respuesta_texto = "He preparado esta propuesta. Revísala y dime si la aplico."
        else:
            respuesta_texto = ("Me he quedado sin pasos para responder. Prueba a pedírmelo "
                              "con menos enlaces a la vez.")
    if caja.get("propuesta_id"):
        # el id viaja en la traza del mensaje: así el historial sabe qué tarjeta
        # de propuesta colgar de qué respuesta
        traza.append({"propuesta_id": caja["propuesta_id"]})
    _guardar_mensaje(db_path, conversacion_id, "assistant", respuesta_texto, traza)

    return {"ok": True, "respuesta": respuesta_texto, "traza": traza,
            "intentos": caja.get("intentos", 0),
            "propuesta": caja.get("propuesta"), "propuesta_id": caja.get("propuesta_id")}


def _resumen_herramienta(nombre: str, argumentos: dict, contenido: str) -> str:
    """Frase corta para enseñar en la interfaz qué hizo el agente."""
    if nombre == "leer_enlaces":
        urls = argumentos.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        hosts = []
        for u in urls[:6]:
            host = urlparse(u if str(u).startswith("http") else "https://" + str(u)).hostname
            if host:
                hosts.append(host)
        return "leyó " + (", ".join(hosts[:4]) or "0 enlaces")
    if nombre == "consultar_portal":
        return "consultó el portal"
    if nombre == "buscar_en_portal":
        return f"buscó «{argumentos.get('texto', '')}»"
    if nombre == "proponer_plan":
        if "válida y guardada" in contenido:
            return "propuesta validada"
        if "no quedan más" in contenido:
            return "propuesta inválida: sin más intentos"
        if "No quedan intentos" in contenido:
            return "sin intentos de validación"
        return "propuesta rechazada: la corrige"
    return f"usó {nombre}"


def nueva_conversacion(db_path: str) -> str:
    conversacion_id = uuid.uuid4().hex[:16]
    db = _conectar(db_path)
    try:
        db.execute("INSERT INTO agente_conversaciones (id) VALUES (?)", (conversacion_id,))
        db.commit()
    finally:
        db.close()
    return conversacion_id


def conversacion_valida(db_path: str, conversacion_id: str) -> bool:
    if not conversacion_id:
        return False
    db = _conectar(db_path)
    try:
        return db.execute("SELECT 1 FROM agente_conversaciones WHERE id = ?",
                          (conversacion_id,)).fetchone() is not None
    finally:
        db.close()
