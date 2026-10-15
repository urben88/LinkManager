#!/usr/bin/env python3
"""
imagenes.py — completa las imágenes de LinkManager con criterio de CALIDAD.

Cada entrada acaba con dos imágenes distintas:

  · logo_url  → un logo PEQUEÑO (favicon del servicio), para el avatar de la tarjeta.
  · image_url → una portada GRANDE, solo si es de calidad; si no se encuentra una
                buena, se hace una CAPTURA del propio servicio.

Regla dura: no se guarda como portada nada que no llegue al mínimo de anchura
ni que sea un fichero diminuto. Antes de poner una imagen pixelada, se deja sin
portada y la tarjeta usa el logo.

Se ejecuta DENTRO del contenedor:
    docker exec linkmanager_web python3 /app/tools/imagenes.py [--forzar] [--seco] [--detalle]

Variables:
    LINKMANAGER_CAPTURAS   URL del servicio de capturas (p. ej. http://capturas:3000)
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
import re
import shutil
import socket
import sqlite3
import ssl
import struct
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

BASE_DATOS = os.environ.get("LINKMANAGER_DB", "/app/database/database.db")
SUBDIDAS = os.environ.get(
    "LINKMANAGER_UPLOADS", os.path.join(os.path.dirname(BASE_DATOS), "uploads"))
DOMINIO_PUBLICO = os.environ.get("LINKMANAGER_DOMINIO", "urbenserver.com")
IP_LAN = os.environ.get("LINKMANAGER_LAN", "192.168.0.100")
CAPTURAS = os.environ.get("LINKMANAGER_CAPTURAS", "").rstrip("/")

PUERTOS_HTTPS = {"443", "8443", "9443", "10000"}
MAX_BYTES = 4_000_000
TIEMPO = 15
ANCHO_MINIMO_PORTADA = 480      # por debajo de esto, la portada se descarta
ALTO_MINIMO_PORTADA = 150
LADO_MINIMO_LOGO = 24

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 LinkManager/2.0")

# Sitios oficiales: dan el logo bueno cuando el servicio local no ofrece ninguno
SERVICIOS_CONOCIDOS = {
    "jellyfin": "jellyfin.org", "n8n": "n8n.io", "gitlab": "about.gitlab.com",
    "coolify": "coolify.io", "portainer": "portainer.io", "qbittorrent": "qbittorrent.org",
    "webmin": "webmin.com", "transmission": "transmissionbt.com",
    "open webui": "openwebui.com", "open-webui": "openwebui.com",
    "cloudflare": "cloudflare.com", "hostalia": "hostalia.com",
    "proxy manager": "nginxproxymanager.com", "nginx": "nginx.org",
    "visual studio code": "code.visualstudio.com", "code-server": "coder.com",
    "wordpress": "wordpress.org", "monica": "monicahq.com", "dify": "dify.ai",
    "langfuse": "langfuse.com", "supabase": "supabase.com", "jellyseerr": "jellyseerr.dev",
    "adguard": "adguard.com", "wireguard": "wireguard.com", "filebrowser": "filebrowser.org",
    "gitea": "gitea.com", "nextcloud": "nextcloud.com", "immich": "immich.app",
    "fmhy": "fmhy.net",
}

_sin_verificar = ssl.create_default_context()
_sin_verificar.check_hostname = False
_sin_verificar.verify_mode = ssl.CERT_NONE


# --------------------------------------------------------------------- red

def _es_privada(host: str) -> bool:
    try:
        for *_, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback:
                return True
    except Exception:
        return False
    return False


def _permitida(url: str) -> bool:
    try:
        partes = urllib.parse.urlparse(url)
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
        if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _descargar(url: str, motivo: list | None = None):
    if not _permitida(url):
        if motivo is not None:
            motivo.append("destino no permitido")
        return None
    host = urllib.parse.urlparse(url).hostname or ""
    # Certificado autofirmado: normal en los servicios internos (Portainer, Webmin…)
    contexto = _sin_verificar if _es_privada(host) else None
    try:
        pet = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(pet, timeout=TIEMPO, context=contexto) as r:
            datos = r.read(MAX_BYTES + 1)
            if len(datos) > MAX_BYTES:
                if motivo is not None:
                    motivo.append("demasiado grande")
                return None
            return datos, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        if motivo is not None:
            motivo.append(f"HTTP {exc.code}")
    except Exception as exc:
        if motivo is not None:
            motivo.append(type(exc).__name__)
    return None


# --------------------------------------------------------------------- imágenes

def tipo_de(datos: bytes) -> str | None:
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if datos[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "webp"
    if datos[:4] == b"\x00\x00\x01\x00":
        return "ico"
    if datos[:2] == b"BM":
        return "bmp"
    recorte = datos.lstrip()[:6].lower()
    if recorte.startswith(b"<svg") or recorte.startswith(b"<?xml"):
        return "svg"
    return None


def dimensiones(datos: bytes, tipo: str) -> tuple[int, int]:
    """Anchura y altura reales, sin dependencias externas."""
    try:
        if tipo == "png":
            return struct.unpack(">II", datos[16:24])
        if tipo == "gif":
            return struct.unpack("<HH", datos[6:10])
        if tipo == "bmp":
            ancho, alto = struct.unpack("<ii", datos[18:26])
            return abs(ancho), abs(alto)
        if tipo == "jpg":
            i = 2
            while i < len(datos) - 9:
                if datos[i] != 0xFF:
                    i += 1
                    continue
                marca = datos[i + 1]
                if marca in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    alto, ancho = struct.unpack(">HH", datos[i + 5:i + 9])
                    return ancho, alto
                if marca in (0xD8, 0xD9) or 0xD0 <= marca <= 0xD7:
                    i += 2
                    continue
                largo = struct.unpack(">H", datos[i + 2:i + 4])[0]
                i += 2 + largo
            return 0, 0
        if tipo == "webp":
            if datos[12:16] == b"VP8X":
                ancho = (datos[24] | datos[25] << 8 | datos[26] << 16) + 1
                alto = (datos[27] | datos[28] << 8 | datos[29] << 16) + 1
                return ancho, alto
            if datos[12:16] == b"VP8L":
                bits = struct.unpack("<I", datos[21:25])[0]
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if datos[12:16] == b"VP8 ":
                return struct.unpack("<HH", datos[26:30])
            return 0, 0
        if tipo == "ico":
            return (datos[6] or 256), (datos[7] or 256)
        if tipo == "svg":
            texto = datos[:4000].decode("utf-8", "replace")
            a = re.search(r'width=["\']?(\d+)', texto)
            h = re.search(r'height=["\']?(\d+)', texto)
            if a and h:
                return int(a.group(1)), int(h.group(1))
            vb = re.search(r'viewBox=["\']?[\d.\s]*?([\d.]+)[\s,]+([\d.]+)', texto)
            if vb:
                return int(float(vb.group(1))), int(float(vb.group(2)))
            return 512, 512
    except Exception:
        pass
    return 0, 0


def vale_como_portada(datos: bytes, tipo: str) -> bool:
    """¿Da esto para portada?

    Un SVG de icono (viewBox pequeño) NO vale como portada: es un logotipo, no
    una imagen de cabecera. Por eso los SVG pasan por el mismo filtro de tamaño
    que los mapas de bits en vez de colarse sin más.
    """
    ancho, alto = dimensiones(datos, tipo)
    if ancho < ANCHO_MINIMO_PORTADA or alto < ALTO_MINIMO_PORTADA:
        return False
    return len(datos) >= 4000        # por debajo, es un icono diminuto


def texto(url: str) -> str:
    r = _descargar(url)
    return r[0].decode("utf-8", "replace") if r else ""


def candidatas_de_pagina(url: str) -> tuple[list[str], list[str]]:
    """(posibles portadas, posibles logos) que ofrece una web."""
    html = texto(url)
    portadas: list[str] = []
    logos: list[str] = []
    if html:
        for m in re.finditer(r"<link[^>]+>", html, re.I):
            etiqueta = m.group(0)
            if re.search(r'rel=["\'][^"\']*apple-touch-icon', etiqueta, re.I):
                href = re.search(r'href=["\']([^"\']+)', etiqueta)
                if href:
                    logos.append(urllib.parse.urljoin(url, href.group(1)))
        for m in re.finditer(r"<meta[^>]+>", html, re.I):
            etiqueta = m.group(0)
            if re.search(r'(property|name)=["\'](og:image|og:image:url|twitter:image)["\']',
                         etiqueta, re.I):
                cont = re.search(r'content=["\']([^"\']+)', etiqueta)
                if cont:
                    portadas.append(urllib.parse.urljoin(url, cont.group(1)))
        for m in re.finditer(r"<link[^>]+>", html, re.I):
            etiqueta = m.group(0)
            if re.search(r'rel=["\'][^"\']*icon', etiqueta, re.I):
                href = re.search(r'href=["\']([^"\']+)', etiqueta)
                if href:
                    logos.append(urllib.parse.urljoin(url, href.group(1)))

    base = urllib.parse.urlparse(url)
    if base.hostname:
        logos += [
            f"{base.scheme}://{base.netloc}/apple-touch-icon.png",
            f"{base.scheme}://{base.netloc}/favicon.ico",
            f"https://icons.duckduckgo.com/ip3/{base.hostname}.ico",
            f"https://www.google.com/s2/favicons?domain={base.hostname}&sz=128",
        ]
    return portadas, logos


# --------------------------------------------------------------------- capturas

def hay_navegador() -> bool:
    """¿Podemos hacer capturas? Chromium local en la imagen o servicio externo."""
    return bool(navegador_local() or CAPTURAS)


def navegador_local() -> str | None:
    """Ruta a Chromium si está instalado."""
    return (os.environ.get("CHROME_BIN")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome"))


def capturar(url: str) -> bytes | None:
    """Captura del servicio con Chromium headless.

    Primero intenta el Chromium local (viene en la imagen); si no estuviera,
    usa el servicio HTTP de LINKMANAGER_CAPTURAS.
    """
    chrome = navegador_local()
    if chrome:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                destino = os.path.join(tmp, "captura.png")
                orden = [
                    chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--disable-dev-shm-usage", "--hide-scrollbars", "--mute-audio",
                    "--no-first-run", "--disable-extensions",
                    "--window-size=1200,675", "--virtual-time-budget=8000",
                    f"--screenshot={destino}", url,
                ]
                subprocess.run(orden, capture_output=True, timeout=90)
                if os.path.exists(destino):
                    with open(destino, "rb") as fh:
                        datos = fh.read(MAX_BYTES)
                    if tipo_de(datos):
                        return datos
        except Exception as exc:
            print(f"        (captura local falló: {type(exc).__name__})")

    if not CAPTURAS:
        return None
    destino_url = f"{CAPTURAS}/screenshot?" + urllib.parse.urlencode(
        {"url": url, "width": 1200, "height": 675, "wait": 2500})
    try:
        pet = urllib.request.Request(destino_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(pet, timeout=90) as r:
            datos = r.read(MAX_BYTES)
        return datos if tipo_de(datos) else None
    except Exception:
        return None


# --------------------------------------------------------------------- principal

def guardar(datos: bytes, extension: str, titulo: str, sufijo: str) -> str:
    limpio = re.sub(r"[^a-zA-Z0-9]+", "-", titulo).strip("-").lower()[:36] or "imagen"
    nombre = f"{sufijo}_{hashlib.sha1(datos).hexdigest()[:8]}_{limpio}.{extension}"
    os.makedirs(SUBDIDAS, exist_ok=True)
    with open(os.path.join(SUBDIDAS, nombre), "wb") as fh:
        fh.write(datos)
    return f"uploads/{nombre}"


def sirve(valor: str | None) -> bool:
    return bool(valor) and (valor.startswith("http")
                            or os.path.exists(os.path.join(SUBDIDAS, os.path.basename(valor))))


def portada_suficiente(valor: str | None) -> bool:
    """¿La portada actual vale, o es pequeña/pixelada y hay que rehacerla?"""
    if not valor:
        return False
    if valor.startswith("http"):
        return True
    ruta = os.path.join(SUBDIDAS, os.path.basename(valor))
    if not os.path.exists(ruta):
        return False
    try:
        with open(ruta, "rb") as fh:
            datos = fh.read(MAX_BYTES)
        tipo = tipo_de(datos)
        return bool(tipo) and vale_como_portada(datos, tipo)
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar", action="store_true", help="rehace también lo que ya funciona")
    ap.add_argument("--seco", action="store_true", help="no escribe nada")
    ap.add_argument("--detalle", action="store_true", help="explica los descartes")
    args = ap.parse_args()

    con = sqlite3.connect(BASE_DATOS)
    con.row_factory = sqlite3.Row
    if "logo_url" not in {f[1] for f in con.execute("PRAGMA table_info(link_entries)")}:
        print("  ✗ falta la columna logo_url: arranca la aplicación una vez primero")
        return 2

    nuevas_portadas = nuevos_logos = capturas = sin_imagen = retiradas = 0

    for entrada in con.execute(
            "select id, title, image_url, logo_url from link_entries order by id"):
        enlaces = [(u["link_type"], u["value"]) for u in con.execute(
            "select link_type, value from entry_urls where link_entry_id = ?", (entrada["id"],))]
        objetivos = []
        for tipo, valor in enlaces:
            if tipo == "external_url":
                objetivos.append(valor)
            elif tipo == "subdomain":
                objetivos.append(f"https://{valor}.{DOMINIO_PUBLICO}")
            elif tipo == "internal_app":
                esquema = "https" if str(valor) in PUERTOS_HTTPS else "http"
                objetivos.append(f"{esquema}://{IP_LAN}:{valor}")

        # el sitio oficial primero: da mejor logo que el servicio interno
        texto_busqueda = (entrada["title"] + " " + " ".join(v for _, v in enlaces)).lower()
        for clave, dominio in SERVICIOS_CONOCIDOS.items():
            if clave in texto_busqueda:
                objetivos = [f"https://{dominio}"] + objetivos
                break

        if not objetivos:
            print(f"  ✗ {entrada['title']}: no apunta a ninguna dirección")
            sin_imagen += 1
            continue

        necesita_logo = args.forzar or not sirve(entrada["logo_url"])
        necesita_portada = args.forzar or not portada_suficiente(entrada["image_url"])
        if not (necesita_logo or necesita_portada):
            continue

        portadas: list[str] = []
        logos: list[str] = []
        for objetivo in objetivos[:3]:
            p, l = candidatas_de_pagina(objetivo)
            portadas += [x for x in p if x not in portadas]
            logos += [x for x in l if x not in logos]

        cambios: dict[str, tuple] = {}
        quitar_portada = False

        if necesita_logo:
            for url in logos:
                r = _descargar(url)
                if not r:
                    continue
                tipo = tipo_de(r[0])
                if not tipo:
                    continue
                ancho, alto = dimensiones(r[0], tipo)
                if tipo != "svg" and (ancho < LADO_MINIMO_LOGO or alto < LADO_MINIMO_LOGO):
                    continue
                cambios["logo_url"] = ("logo", r[0], tipo)
                break

        if necesita_portada:
            for url in portadas:
                r = _descargar(url)
                if not r:
                    continue
                tipo = tipo_de(r[0])
                if not tipo or not vale_como_portada(r[0], tipo):
                    if args.detalle:
                        a, h = dimensiones(r[0], tipo or "?")
                        print(f"        descartada {url[:54]} → {a}x{h}")
                    continue
                cambios["image_url"] = ("portada", r[0], tipo)
                break

            if "image_url" not in cambios and hay_navegador():
                for objetivo in objetivos[:2]:
                    datos = capturar(objetivo)
                    if datos and vale_como_portada(datos, tipo_de(datos) or ""):
                        cambios["image_url"] = ("captura", datos, tipo_de(datos))
                        capturas += 1
                        break

            # La que había tampoco daba la talla y no hay nada mejor: se retira.
            # Antes una tarjeta sin portada que una tarjeta con una imagen mala.
            if "image_url" not in cambios and entrada["image_url"]:
                quitar_portada = True

        if not cambios and not quitar_portada:
            print(f"  · {entrada['title']}: se queda como está (sin imagen nueva válida)")
            sin_imagen += 1
            continue

        if args.seco:
            resumen = ", ".join(
                f"{k.replace('_url', '')}={len(v[1]) // 1024}KB.{v[2]}" for k, v in cambios.items())
            if quitar_portada:
                resumen = (resumen + " " if resumen else "") + "retirar-portada"
            print(f"  (seco) {entrada['title']}: {resumen}")
            continue

        if quitar_portada:
            con.execute("update link_entries set image_url = null where id = ?",  # noqa: S608
                        (entrada["id"],))
            con.commit()
            retiradas += 1
            print(f"  – {entrada['title']}: portada retirada (la que había no daba la talla)")

        for campo, (sufijo, datos, tipo) in cambios.items():
            ruta = guardar(datos, tipo, entrada["title"], sufijo)
            con.execute(f"update link_entries set {campo} = ? where id = ?",  # noqa: S608
                        (ruta, entrada["id"]))
        con.commit()
        if cambios:
            print(f"  ✓ {entrada['title']}: " + " ".join(
                f"{k.replace('_url', '')}({len(v[1]) // 1024}KB .{v[2]})" for k, v in cambios.items()))
        nuevas_portadas += "image_url" in cambios
        nuevos_logos += "logo_url" in cambios

    print(f"\n  portadas: {nuevas_portadas} · logos: {nuevos_logos} · capturas: {capturas} "
          f"· retiradas: {retiradas} · sin cambios: {sin_imagen}")
    if not hay_navegador():
        print("  (sin navegador: instala Chromium en la imagen o define LINKMANAGER_CAPTURAS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
