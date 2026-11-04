"""
LinkManager — portal de enlaces de urbenserver.

Reescritura (2026-10-15) con estas mejoras respecto a la versión original:

  · AUTENTICACIÓN: la edición exige sesión. Antes CUALQUIERA con la URL podía
    añadir, editar y borrar. La aplicación está publicada en Internet.
  · CSRF: todos los POST llevan token. El original no tenía ninguno.
  · SECRET_KEY estable: antes era `os.urandom(24)`, distinta en cada uno de los
    4 workers de gunicorn → las sesiones y los mensajes flash se rompían al azar.
  · XSS: el modal de edición inyectaba título/descripción/enlaces con innerHTML
    sin escapar. Ahora se escapa en el cliente y se sirve JSON.
  · SSRF: la carga de metadatos descargaba CUALQUIER URL, incluidas direcciones
    internas (127.0.0.1, 169.254.169.254…). Ahora se valida el destino.
  · SUBIDAS: se guardaban en /app/static/uploads, FUERA del volumen → se perdían
    al recrear el contenedor. Ahora van a la carpeta persistente y se comprueba
    el contenido real del fichero, no solo la extensión.
"""

import hmac
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import time
import uuid
from functools import wraps
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# El asistente es opcional: si langchain no está instalado o la clave falta, el
# portal tiene que arrancar igual. Nunca un import que tumbe la aplicación.
try:
    import agente
except Exception as _exc_agente:  # noqa: BLE001
    agente = None
    print(f"[linkmanager] asistente desactivado: {_exc_agente}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

# --------------------------------------------------------------------------
#  Configuración y secreto
# --------------------------------------------------------------------------

DATABASE = os.environ.get("LINKMANAGER_DB", os.path.join(BASE_DIR, "database", "database.db"))
UPLOAD_FOLDER = os.environ.get(
    "LINKMANAGER_UPLOADS", os.path.join(os.path.dirname(DATABASE), "uploads"))
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# Ficheros antiguos: se movieron de static/uploads (no persistente) a la carpeta nueva
UPLOAD_FOLDER_ANTIGUO = os.path.join(app.static_folder, "uploads")

PRIVADO = os.environ.get("LINKMANAGER_PRIVATE", "0").strip().lower() in ("1", "true", "yes")
USUARIO = os.environ.get("LINKMANAGER_USER", "admin").strip()
METADATOS_ACTIVOS = os.environ.get("LINKMANAGER_METADATA", "1").strip().lower() not in ("0", "false", "no")
CATALOGO = os.environ.get("CATALOGO_JSON", "/app/servicios.json")
MAX_REINTENTOS_LOGIN = 8


def _cargar_secreto():
    """Secreto ESTABLE: si no, cada worker de gunicorn firma con una clave distinta."""
    entorno = os.environ.get("LINKMANAGER_SECRET")
    if entorno:
        return entorno.encode()
    ruta = os.environ.get("LINKMANAGER_SECRET_FILE",
                          os.path.join(os.path.dirname(DATABASE), "secret.key"))
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    if os.path.exists(ruta):
        datos = open(ruta, "rb").read().strip()
        if datos:
            return datos
    nuevo = secrets.token_hex(32).encode()
    with open(ruta, "wb") as fh:
        fh.write(nuevo)
    os.chmod(ruta, 0o600)
    return nuevo


def _cargar_clave():
    """Hash de la contraseña de administración.

    Prioridad: hash explícito > contraseña en claro > fichero generado la primera vez.
    Nunca se arranca sin protección: si no hay nada configurado se genera una
    contraseña aleatoria y se deja anotada en database/ADMIN_PASSWORD.txt (chmod 600).
    """
    propio = os.environ.get("LINKMANAGER_PASSWORD_HASH")
    if propio:
        return propio
    claro = os.environ.get("LINKMANAGER_PASSWORD")
    if claro:
        return generate_password_hash(claro)
    ruta = os.path.join(os.path.dirname(DATABASE), "ADMIN_PASSWORD.txt")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    if os.path.exists(ruta):
        clave = open(ruta, encoding="utf-8").read().strip()
    else:
        clave = secrets.token_urlsafe(15)
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(clave + "\n")
        os.chmod(ruta, 0o600)
        print(f"[linkmanager] contraseña de administración generada en {ruta}")
    return generate_password_hash(clave)


app.secret_key = _cargar_secreto()
CLAVE_HASH = _cargar_clave()

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("LINKMANAGER_COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=int(os.environ.get("LINKMANAGER_MAX_UPLOAD_MB", "8")) * 1024 * 1024,
)

# El JSON de las propuestas se lee mejor con el orden en que se escribe
# (resumen, secciones, entradas…). `JSON_SORT_KEYS` ya no existe en Flask 2.3+.
app.json.sort_keys = False

for carpeta in (os.path.dirname(DATABASE), UPLOAD_FOLDER):
    os.makedirs(carpeta, exist_ok=True)


# --------------------------------------------------------------------------
#  Base de datos
# --------------------------------------------------------------------------

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")  # varios workers leyendo a la vez
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource("schema.sql", mode="r") as f:
            db.cursor().executescript(f.read())
        db.commit()


# --------------------------------------------------------------------------
#  Autenticación y CSRF
# --------------------------------------------------------------------------

_intentos = {}


def logueado() -> bool:
    return bool(session.get("usuario"))


def login_required(vista):
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        if not logueado():
            # full_path añade un '?' suelto cuando no hay query string
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return vista(*args, **kwargs)
    return envoltorio


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def _csrf_valido() -> bool:
    enviado = (request.form.get("_csrf")
               or request.headers.get("X-CSRF-Token")
               or (request.get_json(silent=True) or {}).get("_csrf")
               or "")
    esperado = session.get("_csrf", "")
    return bool(enviado) and bool(esperado) and hmac.compare_digest(str(enviado), str(esperado))


@app.before_request
def _guardia():
    # 1) Todo POST necesita token CSRF (incluido /login).
    if request.method == "POST" and not _csrf_valido():
        abort(400, "Token CSRF ausente o inválido. Recarga la página e inténtalo de nuevo.")
    # 2) Si la app está en modo privado, todo exige sesión.
    if PRIVADO and not logueado():
        publicas = {"login", "static", "salud", "favicon"}
        if request.endpoint not in publicas:
            return redirect(url_for("login", next=request.path))


@app.after_request
def _cabeceras(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


@app.context_processor
def _inyectar():
    return {"logueado": logueado(), "csrf_token": csrf_token, "privado": PRIVADO,
            "agente_disponible": bool(agente is not None and agente.disponible())}


def tono(texto: str) -> int:
    """Tono de color estable a partir de un texto. Para el monograma de las tarjetas."""
    return sum(ord(c) * (i + 7) for i, c in enumerate(texto or "?")) % 360


def iniciales(texto: str) -> str:
    """Hasta dos iniciales, para cuando una entrada no tiene imagen."""
    palabras = [p for p in (texto or "?").replace("-", " ").split() if p]
    if not palabras:
        return "?"
    if len(palabras) == 1:
        return palabras[0][:2].upper()
    return (palabras[0][0] + palabras[1][0]).upper()


app.jinja_env.globals["tono"] = tono
app.jinja_env.globals["iniciales"] = iniciales


def etiqueta_enlace(link_type: str, valor: str) -> str:
    """Texto corto para el chip de un enlace, cuando no tiene etiqueta propia."""
    if link_type == "external_url":
        host = urlparse(valor).hostname or valor
        return host[4:] if host.startswith("www.") else host
    if link_type == "subdomain":
        return valor
    return f"puerto {valor}"


app.jinja_env.globals["etiqueta_enlace"] = etiqueta_enlace


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        ahora = time.time()
        intentos = [t for t in _intentos.get(ip, []) if ahora - t < 300]
        if len(intentos) >= MAX_REINTENTOS_LOGIN:
            flash("Demasiados intentos fallidos. Espera unos minutos.", "error")
            _intentos[ip] = intentos
            return render_template("login.html", next=request.args.get("next", "")), 429

        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        if usuario == USUARIO and check_password_hash(CLAVE_HASH, clave):
            session.clear()
            session["usuario"] = usuario
            csrf_token()
            _intentos.pop(ip, None)
            destino = request.args.get("next") or ""
            if not destino.startswith("/"):
                destino = url_for("index")
            return redirect(destino)

        intentos.append(ahora)
        _intentos[ip] = intentos
        time.sleep(0.4)  # freno a la fuerza bruta
        flash("Usuario o contraseña incorrectos.", "error")

    return render_template("login.html", next=request.args.get("next", ""))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/salud")
def salud():
    return jsonify({"ok": True, "logueado": logueado()})


# --------------------------------------------------------------------------
#  Utilidades
# --------------------------------------------------------------------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _parece_imagen(datos: bytes) -> bool:
    """Comprueba el CONTENIDO real, no la extensión."""
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if datos.startswith(b"\xff\xd8\xff"):
        return True
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return True
    return False


def guardar_imagen(fichero):
    """Guarda una imagen validando contenido y tamaño. Devuelve la ruta relativa o None."""
    if not fichero or not fichero.filename:
        return None
    if not allowed_file(fichero.filename):
        return None
    datos = fichero.read()
    fichero.seek(0)
    if not datos or not _parece_imagen(datos):
        return None
    nombre = f"{uuid.uuid4().hex[:8]}_{secure_filename(fichero.filename)}"
    ruta = os.path.join(UPLOAD_FOLDER, nombre)
    with open(ruta, "wb") as fh:
        fh.write(datos)
    return f"uploads/{nombre}"


def _url_permitida(url: str) -> bool:
    """Bloquea SSRF: solo http/https, y nunca hacia direcciones internas."""
    try:
        partes = urlparse(url)
    except Exception:
        return False
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return False
    try:
        direcciones = socket.getaddrinfo(partes.hostname, None)
    except Exception:
        return False
    for *_, sockaddr in direcciones:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def fetch_metadata(url_to_fetch):
    """Título/descripción/imagen de una URL externa. Con guarda anti-SSRF y límite de tamaño."""
    metadatos = {"title": url_to_fetch, "description": "", "image_url": ""}
    if not METADATOS_ACTIVOS:
        return metadatos
    try:
        objetivo = url_to_fetch
        if not objetivo.startswith(("http://", "https://")):
            objetivo = "http://" + objetivo
        if not _url_permitida(objetivo):
            return metadatos

        respuesta = requests.get(
            objetivo, timeout=8, allow_redirects=False,
            stream=True,
            headers={"User-Agent": "LinkManager/2.0 (+https://urbenserver.com)"})
        # Si redirige, se valida el destino antes de seguir (evita saltarse la guarda)
        if respuesta.is_redirect:
            destino = urljoin(objetivo, respuesta.headers.get("Location", ""))
            if not _url_permitida(destino):
                return metadatos
            respuesta = requests.get(destino, timeout=8, allow_redirects=False,
                                     headers={"User-Agent": "LinkManager/2.0"})

        respuesta.raise_for_status()
        trozos, tam = [], 0
        for trozo in respuesta.iter_content(16384):
            trozos.append(trozo)
            tam += len(trozo)
            if tam > 512_000:  # 512 KB sobra para leer el <head>
                break
        sopa = BeautifulSoup(b"".join(trozos), "html.parser")

        def meta(propiedad=None, nombre=None, defecto=""):
            etiqueta = (sopa.find("meta", property=propiedad) if propiedad
                        else sopa.find("meta", attrs={"name": nombre}))
            valor = etiqueta.get("content") if etiqueta else None
            return (valor or defecto).strip()

        titulo = meta("og:title") or (sopa.find("title").string or "").strip()
        metadatos["title"] = titulo or url_to_fetch
        metadatos["description"] = meta("og:description") or meta(nombre="description")

        imagen = meta("og:image")
        if imagen:
            base = urlparse(objetivo)
            if not urlparse(imagen).scheme:
                camino = imagen if imagen.startswith("/") else "/" + imagen
                imagen = f"{base.scheme}://{base.netloc}{camino}"
            metadatos["image_url"] = imagen
    except Exception as exc:
        print(f"[linkmanager] fetch_metadata({url_to_fetch}): {exc}")
    return metadatos


# --------------------------------------------------------------------------
#  Vistas
# --------------------------------------------------------------------------

@app.route("/")
def index():
    db = get_db()
    secciones = {s["id"]: dict(s) for s in
                 db.execute("SELECT * FROM sections ORDER BY order_index, name")}
    for s in secciones.values():
        s["link_entries"] = []

    entradas = {e["id"]: dict(e) for e in
                db.execute("SELECT * FROM link_entries ORDER BY order_index, created_at DESC")}
    for e in entradas.values():
        e["urls"] = []
        e["hijos"] = []

    for u in db.execute("SELECT * FROM entry_urls ORDER BY id"):
        if u["link_entry_id"] in entradas:
            entradas[u["link_entry_id"]]["urls"].append(dict(u))

    # Árbol de DOS niveles. Una entrada con parent_id válido cuelga de su padre;
    # el resto son de primer nivel. Si el padre no existe, está en otra sección
    # o es a su vez hijo, el hijo se queda suelto en lugar de desaparecer: nunca
    # se pierde una tarjeta por un dato incoherente.
    for e in entradas.values():
        padre = entradas.get(e["parent_id"]) if e["parent_id"] else None
        if (padre is not None and padre["id"] != e["id"]
                and padre["section_id"] == e["section_id"] and not padre["parent_id"]):
            padre["hijos"].append(e)
        else:
            e["parent_id"] = None
            if e["section_id"] in secciones:
                secciones[e["section_id"]]["link_entries"].append(e)

    todas = list(secciones.values())
    resumen = {
        "secciones": len(todas),
        "entradas": len(entradas),
        "enlaces": sum(len(e["urls"]) for e in entradas.values()),
        "grupos": sum(1 for e in entradas.values() if e["hijos"]),
        "portadas": sum(1 for e in entradas.values() if e.get("image_url")),
    }

    return render_template(
        "index.html",
        sections_with_data=todas,
        all_sections=[dict(s) for s in
                      db.execute("SELECT * FROM sections ORDER BY order_index, name")],
        # solo las entradas de primer nivel pueden ser padre
        padres_disponibles=[dict(e) for e in entradas.values() if not e["parent_id"]],
        resumen=resumen,
        app_domains=get_app_settings())


def get_app_settings():
    filas = get_db().execute("SELECT setting_key, setting_value FROM settings").fetchall()
    ajustes = {f["setting_key"]: f["setting_value"] for f in filas}
    return {"public": ajustes.get("domain_public", ""),
            "lan": ajustes.get("domain_lan", ""),
            "local": ajustes.get("domain_local", "")}


@app.route("/update_settings", methods=["POST"])
@login_required
def update_settings():
    db = get_db()
    try:
        def formatear(valor):
            valor = valor.strip()
            if not valor:
                return ""
            return valor if valor.startswith(("http://", "https://")) else "http://" + valor

        for clave in ("domain_public", "domain_lan", "domain_local"):
            db.execute("INSERT OR REPLACE INTO settings (setting_key, setting_value) VALUES (?, ?)",
                       (clave, formatear(request.form.get(clave, ""))))
        db.commit()
        flash("Configuración de entorno actualizada.", "success")
    except sqlite3.Error as exc:
        db.rollback()
        flash(f"Error al actualizar la configuración: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/update_order", methods=["POST"])
@login_required
def update_order():
    data = request.get_json() or {}
    tipo = data.get("type")
    orden = data.get("order", [])
    if tipo not in ("sections", "entries") or not orden:
        return jsonify({"status": "error", "message": "Datos inválidos"}), 400

    tabla = "sections" if tipo == "sections" else "link_entries"
    db = get_db()
    try:
        if tipo == "entries" and "section_id" in data and "entry_id" in data:
            db.execute("UPDATE link_entries SET section_id = ? WHERE id = ?",
                       (int(data["section_id"]), int(data["entry_id"])))
            # si lo que se mueve es un grupo, sus hijos van con él: si no,
            # quedarían huérfanos en la sección antigua
            db.execute("UPDATE link_entries SET section_id = ? WHERE parent_id = ?",
                       (int(data["section_id"]), int(data["entry_id"])))
        for indice, item in enumerate(orden):
            db.execute(f"UPDATE {tabla} SET order_index = ? WHERE id = ?",  # noqa: S608
                       (indice, int(item)))
        db.commit()
        return jsonify({"status": "success"})
    except (sqlite3.Error, ValueError) as exc:
        db.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/add_section", methods=["POST"])
@login_required
def add_section():
    nombre = request.form.get("section_name", "").strip()
    if not nombre:
        flash("El nombre de la sección no puede estar vacío.", "error")
        return redirect(url_for("index"))
    db = get_db()
    try:
        db.execute("INSERT INTO sections (name) VALUES (?)", (nombre,))
        db.commit()
        flash(f"Sección '{nombre}' creada.", "success")
    except sqlite3.IntegrityError:
        flash(f"La sección '{nombre}' ya existe.", "warning")
    return redirect(url_for("index"))


@app.route("/edit_section/<int:section_id>", methods=["POST"])
@login_required
def edit_section(section_id):
    nuevo = request.form.get("edit_section_name", "").strip()
    if not nuevo:
        flash("El nuevo nombre de la sección no puede estar vacío.", "error")
        return redirect(url_for("index"))
    db = get_db()
    try:
        cur = db.execute("UPDATE sections SET name = ? WHERE id = ?", (nuevo, section_id))
        db.commit()
        flash(f"Sección actualizada a '{nuevo}'." if cur.rowcount
              else "No se encontró la sección.", "success" if cur.rowcount else "error")
    except sqlite3.IntegrityError:
        flash(f"Ya existe una sección con el nombre '{nuevo}'.", "warning")
    except sqlite3.Error as exc:
        flash(f"Error al actualizar la sección: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/delete_section/<int:section_id>", methods=["POST"])
@login_required
def delete_section(section_id):
    db = get_db()
    try:
        for fila in db.execute("SELECT image_url FROM link_entries WHERE section_id = ?",
                               (section_id,)).fetchall():
            _borrar_imagen(fila["image_url"])
        db.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        db.commit()
        flash("Sección eliminada.", "success")
    except sqlite3.Error as exc:
        db.rollback()
        flash(f"Error al eliminar la sección: {exc}", "error")
    return redirect(url_for("index"))


def _borrar_imagen(ruta_relativa):
    if ruta_relativa and ruta_relativa.startswith("uploads/"):
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, os.path.basename(ruta_relativa)))
        except OSError:
            pass


def _leer_urls_formulario(con_id=False):
    salida, i = [], 0
    while (f"urls[{i}][id]" in request.form) if con_id else (f"urls[{i}][type]" in request.form):
        valor = request.form.get(f"urls[{i}][value]", "").strip()
        if valor:
            elemento = {"label": request.form.get(f"urls[{i}][label]", "").strip(),
                        "link_type": request.form.get(f"urls[{i}][type]"),
                        "value": valor}
            if con_id:
                elemento["id"] = request.form.get(f"urls[{i}][id]")
            salida.append(elemento)
        i += 1
    return salida


def _padre_valido(valor, seccion, excluir=None):
    """Devuelve un parent_id utilizable, o None.

    Un padre tiene que existir, estar en la MISMA sección, no ser hijo de otro
    (solo dos niveles) y no ser la propia entrada ni colgar de ella.
    """
    try:
        pid = int(valor)
    except (TypeError, ValueError):
        return None
    try:
        sec = int(seccion)
    except (TypeError, ValueError):
        return None

    db = get_db()
    fila = db.execute("SELECT id, section_id, parent_id FROM link_entries WHERE id = ?",
                      (pid,)).fetchone()
    if not fila or fila["section_id"] != sec or fila["parent_id"] or pid == excluir:
        return None
    if excluir is not None:
        # no puede ser padre de sí misma ni de quien ya es su hijo
        if db.execute("SELECT 1 FROM link_entries WHERE id = ? AND parent_id = ?",
                      (pid, excluir)).fetchone():
            return None
    return pid


@app.route("/add_link_entry", methods=["POST"])
@login_required
def add_link_entry():
    titulo = request.form.get("link_title", "").strip()
    descripcion = request.form.get("link_description", "").strip()
    seccion = request.form.get("section_id")
    urls = _leer_urls_formulario()
    padre = _padre_valido(request.form.get("parent_id"), seccion)

    if not titulo:
        flash("El título de la entrada es obligatorio.", "error")
        return redirect(url_for("index"))
    if not seccion or not urls:
        flash("Sección y al menos un enlace son requeridos.", "error")
        return redirect(url_for("index"))

    imagen = guardar_imagen(request.files.get("custom_image_file"))
    if not imagen:
        externa = next((u["value"] for u in urls if u["link_type"] == "external_url"), None)
        if externa:
            imagen = fetch_metadata(externa).get("image_url")

    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("INSERT INTO link_entries (title, description, image_url, section_id, "
                    "parent_id, order_index) VALUES (?, ?, ?, ?, ?, "
                    "(SELECT COALESCE(MAX(order_index), 0) + 1 FROM link_entries WHERE section_id = ?))",
                    (titulo, descripcion, imagen, seccion, padre, seccion))
        nuevo_id = cur.lastrowid
        for u in urls:
            cur.execute("INSERT INTO entry_urls (link_entry_id, label, link_type, value) "
                        "VALUES (?, ?, ?, ?)", (nuevo_id, u["label"], u["link_type"], u["value"]))
        db.commit()
        flash("Nueva entrada añadida.", "success")
    except sqlite3.Error as exc:
        db.rollback()
        flash(f"Error de base de datos al añadir la entrada: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/edit_link_entry/<int:entry_id>", methods=["POST"])
@login_required
def edit_link_entry(entry_id):
    titulo = request.form.get("link_title", "").strip()
    if not titulo:
        flash("El título no puede estar vacío.", "error")
        return redirect(url_for("index"))

    db = get_db()
    fila = db.execute("SELECT image_url FROM link_entries WHERE id = ?", (entry_id,)).fetchone()
    if not fila:
        flash("La entrada que intentas editar no existe.", "error")
        return redirect(url_for("index"))

    imagen = fila["image_url"]
    if request.form.get("delete_current_image") == "on":
        _borrar_imagen(imagen)
        imagen = None
    nueva = guardar_imagen(request.files.get("custom_image_file"))
    if nueva:
        _borrar_imagen(fila["image_url"])
        imagen = nueva

    enviadas = _leer_urls_formulario(con_id=True)
    try:
        cur = db.cursor()
        seccion_destino = request.form.get("section_id")
        padre = _padre_valido(request.form.get("parent_id"), seccion_destino, excluir=entry_id)
        cur.execute("UPDATE link_entries SET title = ?, description = ?, image_url = ?, "
                    "section_id = ?, parent_id = ? WHERE id = ?",
                    (titulo, request.form.get("link_description", "").strip(),
                     imagen, seccion_destino, padre, entry_id))

        existentes = {str(f["id"]) for f in
                      cur.execute("SELECT id FROM entry_urls WHERE link_entry_id = ?",
                                  (entry_id,)).fetchall()}
        conservadas = {u["id"] for u in enviadas if u["id"] != "new"}
        for sobrante in existentes - conservadas:
            cur.execute("DELETE FROM entry_urls WHERE id = ?", (sobrante,))
        for u in enviadas:
            if u["id"] == "new":
                cur.execute("INSERT INTO entry_urls (link_entry_id, label, link_type, value) "
                            "VALUES (?, ?, ?, ?)",
                            (entry_id, u["label"], u["link_type"], u["value"]))
            else:
                cur.execute("UPDATE entry_urls SET label = ?, link_type = ?, value = ? "
                            "WHERE id = ? AND link_entry_id = ?",
                            (u["label"], u["link_type"], u["value"], u["id"], entry_id))
        db.commit()
        flash("Entrada actualizada correctamente.", "success")
    except sqlite3.Error as exc:
        db.rollback()
        flash(f"Error de base de datos al actualizar: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/delete_link_entry/<int:entry_id>", methods=["POST"])
@login_required
def delete_link_entry(entry_id):
    db = get_db()
    fila = db.execute("SELECT image_url FROM link_entries WHERE id = ?", (entry_id,)).fetchone()
    if fila:
        _borrar_imagen(fila["image_url"])
    try:
        # los hijos no se borran con el padre: quedan sueltos en su sección
        db.execute("UPDATE link_entries SET parent_id = NULL WHERE parent_id = ?", (entry_id,))
        db.execute("DELETE FROM link_entries WHERE id = ?", (entry_id,))
        db.commit()
        flash("Entrada eliminada. Lo que colgaba de ella ha quedado suelto.", "success")
    except sqlite3.Error as exc:
        db.rollback()
        flash(f"Error al eliminar la entrada: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/get_entry_details/<int:entry_id>")
@login_required
def get_entry_details(entry_id):
    db = get_db()
    entrada = db.execute("SELECT * FROM link_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entrada:
        return jsonify({"error": "Entrada no encontrada"}), 404
    datos = dict(entrada)
    datos["urls"] = [dict(u) for u in db.execute(
        "SELECT * FROM entry_urls WHERE link_entry_id = ? ORDER BY id", (entry_id,))]
    datos["all_sections"] = [dict(s) for s in db.execute(
        "SELECT id, name FROM sections ORDER BY order_index, name")]
    # posibles padres: de primer nivel, de su misma sección y que no sea ella misma
    datos["posibles_padres"] = [dict(f) for f in db.execute(
        "SELECT id, title FROM link_entries WHERE section_id = ? AND parent_id IS NULL "
        "AND id <> ? ORDER BY order_index, title", (datos["section_id"], entry_id))]
    return jsonify(datos)


@app.route("/uploads/<path:nombre>")
def subida(nombre):
    return send_from_directory(UPLOAD_FOLDER, nombre)


@app.route("/servidor")
@login_required  # el catálogo expone puertos y rutas internas: no va en abierto
def servidor():
    try:
        with open(CATALOGO, encoding="utf-8") as fh:
            datos = json.load(fh)
    except Exception as exc:
        datos = {"error": str(exc), "servicios": [], "generado": None,
                 "total_contenedores": 0}

    # Agrupar por proyecto compose para que la página se lea de un vistazo
    grupos = {}
    for s in datos.get("servicios", []):
        grupos.setdefault(s.get("proyecto") or "sin proyecto", []).append(s)
    datos["grupos"] = [{"nombre": k, "servicios": v} for k, v in sorted(grupos.items())]
    datos["en_marcha"] = sum(1 for s in datos.get("servicios", [])
                             if s.get("estado") == "en marcha")
    return render_template("servidor.html", datos=datos,
                           meilisearch=os.environ.get("MEILI_URL", "http://192.168.0.100:7700"),
                           dockge=os.environ.get("DOCKGE_URL", "http://192.168.0.100:5001"),
                           recoll=os.environ.get("RECOLL_URL", "http://192.168.0.100:7800"),
                           wiki=os.environ.get("WIKI_URL", "http://192.168.0.100:5010"))


# --------------------------------------------------------------------------
#  Asistente (LangChain) — propone, nunca escribe sin aprobación
# --------------------------------------------------------------------------

def _contexto_agente():
    """El agente reutiliza la guarda anti-SSRF del portal."""
    return agente.Entorno(db_path=DATABASE, permitir_url=_url_permitida)


def _conversacion_actual():
    """La conversación vive en la sesión firmada, pero el contenido en SQLite:
    con 4 workers de gunicorn, la memoria del proceso no sirve."""
    conv = session.get("agente_conv")
    if not conv or not agente.conversacion_valida(DATABASE, conv):
        conv = agente.nueva_conversacion(DATABASE)
        session["agente_conv"] = conv
    return conv


def _agente_no_disponible():
    return jsonify({"ok": False,
                    "error": "El asistente no está disponible (falta la clave del modelo)."}), 503


@app.route("/agente/historial")
@login_required
def agente_historial():
    if agente is None or not agente.disponible():
        return _agente_no_disponible()
    conv = _conversacion_actual()
    datos = agente.historial_visible(DATABASE, conv)
    return jsonify({"ok": True, "conversacion": conv, **datos})


@app.route("/agente/mensaje", methods=["POST"])
@login_required
def agente_mensaje():
    if agente is None or not agente.disponible():
        return _agente_no_disponible()
    datos = request.get_json(silent=True) or {}
    resultado = agente.responder(DATABASE, _conversacion_actual(),
                                 datos.get("mensaje", ""), _contexto_agente())
    return jsonify(resultado), (200 if resultado.get("ok") else 400)


@app.route("/agente/aplicar/<propuesta_id>", methods=["POST"])
@login_required
def agente_aplicar(propuesta_id):
    if agente is None:
        return _agente_no_disponible()
    resultado = agente.aplicar_propuesta(DATABASE, propuesta_id, _contexto_agente())
    return jsonify(resultado), (200 if resultado.get("ok") else 400)


@app.route("/agente/descartar/<propuesta_id>", methods=["POST"])
@login_required
def agente_descartar(propuesta_id):
    if agente is None:
        return _agente_no_disponible()
    resultado = agente.descartar_propuesta(DATABASE, propuesta_id)
    return jsonify(resultado), (200 if resultado.get("ok") else 400)


@app.route("/agente/nueva", methods=["POST"])
@login_required
def agente_nueva():
    if agente is None:
        return _agente_no_disponible()
    session["agente_conv"] = agente.nueva_conversacion(DATABASE)
    return jsonify({"ok": True, "conversacion": session["agente_conv"]})


# --------------------------------------------------------------------------
#  Arranque
# --------------------------------------------------------------------------

def _migrar_subidas():
    """Trae las imágenes antiguas de static/uploads (no persistente) a la carpeta buena."""
    if not os.path.isdir(UPLOAD_FOLDER_ANTIGUO):
        return
    movidos = 0
    for nombre in os.listdir(UPLOAD_FOLDER_ANTIGUO):
        origen = os.path.join(UPLOAD_FOLDER_ANTIGUO, nombre)
        destino = os.path.join(UPLOAD_FOLDER, nombre)
        if os.path.isfile(origen) and not os.path.exists(destino):
            try:
                os.replace(origen, destino)
                movidos += 1
            except OSError:
                pass
    if movidos:
        print(f"[linkmanager] {movidos} imagen(es) movidas a {UPLOAD_FOLDER}")


COLUMNAS_NUEVAS = (
    # logo pequeño (favicon) separado de la portada: la tarjeta usa el logo
    # como avatar y la portada solo cuando hay una de calidad
    ("link_entries", "logo_url", "TEXT"),
    # convierte una entrada en «padre»: sus hijos se despliegan desde ella
    ("link_entries", "parent_id", "INTEGER"),
)


def _migrar_columnas():
    """Añade columnas que falten, sin tocar los datos existentes.

    Los 4 workers de gunicorn arrancan a la vez y todos llaman aquí: hay que
    tolerar que otro se nos haya adelantado añadiendo la misma columna.
    """
    db = sqlite3.connect(DATABASE)
    try:
        for tabla, columna, tipo in COLUMNAS_NUEVAS:
            existentes = {f[1] for f in db.execute(f"PRAGMA table_info({tabla})")}
            if columna in existentes:
                continue
            try:
                db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
                db.commit()
                print(f"[linkmanager] columna añadida: {tabla}.{columna}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
    finally:
        db.close()


def check_and_create_db():
    if not os.path.exists(DATABASE):
        print(f"[linkmanager] base de datos no encontrada en {DATABASE}; creando…")
        init_db()
    _migrar_columnas()
    if agente is not None:
        try:
            agente.preparar(DATABASE)
        except Exception as exc:  # noqa: BLE001
            print(f"[linkmanager] no se pudieron crear las tablas del asistente: {exc}")


check_and_create_db()
_migrar_subidas()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
