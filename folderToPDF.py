#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convierte TODO el contenido de un directorio (sin filtrar por extensión) a:
    • PDF  – índice + contenido por archivo
    • TXT  – índice + contenido
    • CSV  – columnas: ruta, nº línea, contenido

Requisito opcional:
    pip install fpdf2        # sólo si vas a generar PDF
"""

import os
import csv
from pathlib import Path

try:
    from fpdf import FPDF          # solo si elegimos PDF
except ImportError:
    FPDF = None                    # permitimos TXT/CSV aunque no esté fpdf2


# --------------------------------------------------------------------------- #
# Escaneo de proyecto (¡sin filtro de extensiones!)
# --------------------------------------------------------------------------- #
def scan_project(base: Path):
    """
    Devuelve:
      1) arbol:  { carpeta: { … "__files__": [nombres] } }
      2) files:  [(ruta_relativa, [líneas de texto]), …]
    """
    arbol, files = {}, []

    for root, _, filenames in os.walk(base):
        rel_root = Path(root).relative_to(base)
        nodo = arbol
        if rel_root != Path("."):
            for parte in rel_root.parts:
                nodo = nodo.setdefault(parte, {})

        for name in filenames:                       # ← ¡ya no filtramos!
            nodo.setdefault("__files__", []).append(name)
            ruta = Path(root) / name
            try:
                with ruta.open("r", encoding="utf-8", errors="ignore") as fh:
                    files.append((ruta.relative_to(base), fh.readlines()))
            except Exception as e:
                print(f"⚠️  No se pudo leer {ruta}: {e}")

    return arbol, files


# --------------------------------------------------------------------------- #
# Exportar PDF
# --------------------------------------------------------------------------- #
def dibujar_arbol(pdf: "FPDF", nodo: dict, indent: int = 0):
    for k, v in sorted(nodo.items()):
        if k == "__files__":
            for f in sorted(v):
                pdf.multi_cell(0, 5, " " * indent + f"- {f}",
                               new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.multi_cell(0, 5, " " * indent + f"[{k}]/",
                           new_x="LMARGIN", new_y="NEXT")
            dibujar_arbol(pdf, v, indent + 4)


def export_pdf(base: Path, output: Path, arbol: dict, files: list):
    if FPDF is None:
        raise RuntimeError("❗  Instala primero fpdf2 →  pip install fpdf2")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Courier", size=10)

    # Portada con árbol
    pdf.add_page()
    pdf.set_font("Courier", style="B", size=12)
    pdf.multi_cell(0, 8, f"Resumen de archivos en:\n{base}\n",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier", size=10)
    dibujar_arbol(pdf, arbol)

    # Contenido
    for rel_path, lines in files:
        pdf.add_page()
        pdf.set_font("Courier", style="B", size=11)
        pdf.multi_cell(0, 7, f"{rel_path}\n", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", size=9)
        for ln in lines:
            pdf.multi_cell(0, 5,
                           ln.encode("latin-1", "replace").decode("latin-1"),
                           new_x="LMARGIN", new_y="NEXT")

    pdf.output(output)
    print(f"✅ PDF generado en {output}")


# --------------------------------------------------------------------------- #
# Exportar TXT
# --------------------------------------------------------------------------- #
def export_txt(output: Path, arbol: dict, files: list):
    def arbol_txt(nodo, indent=0):
        for k, v in sorted(nodo.items()):
            if k == "__files__":
                for f in sorted(v):
                    yield " " * indent + f"- {f}"
            else:
                yield " " * indent + f"[{k}]/"
                yield from arbol_txt(v, indent + 4)

    with output.open("w", encoding="utf-8") as fh:
        fh.write("# Árbol de archivos\n")
        fh.write("\n".join(arbol_txt(arbol)))
        fh.write("\n\n# Contenido de archivos\n\n")
        for rel_path, lines in files:
            fh.write(f"## {rel_path}\n")
            fh.writelines(lines)
            fh.write("\n")
    print(f"✅ TXT generado en {output}")


# --------------------------------------------------------------------------- #
# Exportar CSV
# --------------------------------------------------------------------------- #
def export_csv(output: Path, files: list):
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["path", "line_no", "content"])
        for rel_path, lines in files:
            for i, ln in enumerate(lines, 1):
                writer.writerow([str(rel_path), i, ln.rstrip("\n")])
    print(f"✅ CSV generado en {output}")


# --------------------------------------------------------------------------- #
# Programa principal
# --------------------------------------------------------------------------- #
def main():
    print("📦 Convertidor universal  (PDF / TXT / CSV)\n")

    # ── Ejemplo visible ────────────────────────────────────────────────────
    print("Ejemplo rápido:")
    print("  Ruta proyecto ➜ Ejemplo/src")
    print("  Nombre salida ➜ listado")
    print("  Formato       ➜ pdf\n")
    # ──────────────────────────────────────────────────────────────────────

    ruta = input("📂 Ruta de la carpeta del proyecto: ").strip('"')
    base = Path(ruta).expanduser().resolve()
    if not base.is_dir():
        print("❌  Ruta no válida.")
        return

    out_name = input("💾 Nombre de salida (sin extensión): ").strip()
    fmt = input("📄 Formato (pdf / txt / csv): ").lower().strip()

    arbol, files = scan_project(base)
    output = Path.cwd() / f"{out_name}.{fmt}"

    try:
        if fmt == "pdf":
            export_pdf(base, output, arbol, files)
        elif fmt == "txt":
            export_txt(output, arbol, files)
        elif fmt == "csv":
            export_csv(output, files)
        else:
            print("⚠️  Formato no reconocido. Elige pdf, txt o csv.")
    except Exception as e:
        print(f"❌  Error generando salida: {e}")


if __name__ == "__main__":
    main()
