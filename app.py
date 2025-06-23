import sqlite3
import requests # type: ignore
from bs4 import BeautifulSoup # type: ignore
from flask import Flask, render_template, request, redirect, url_for, jsonify, g, flash
from urllib.parse import urlparse
import os
import uuid 
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24) # Necesario para flash messages
DATABASE = 'database.db'

UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER)
    except OSError as e:
        print(f"Error al crear la carpeta de subidas {UPLOAD_FOLDER}: {e}")

# --- Funciones de Base de Datos ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        try:
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()
            print("Base de datos inicializada con el esquema.")
        except Exception as e:
            print(f"Error al inicializar la base de datos desde schema.sql: {e}")

# --- Funciones de Ayuda ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def fetch_metadata(url_to_fetch):
    metadata = {'title': url_to_fetch, 'description': '', 'image_url': ''}
    try:
        processed_url = url_to_fetch
        if not processed_url.startswith(('http://', 'https://')):
            processed_url = 'http://' + processed_url
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8', 'DNT': '1', 'Upgrade-Insecure-Requests': '1'
        }
        response = requests.get(processed_url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        og_title = soup.find('meta', property='og:title')
        metadata['title'] = (og_title['content'].strip() if og_title and og_title.get('content') 
                             else (soup.find('title').string.strip() if soup.find('title') and soup.find('title').string else url_to_fetch))
        og_description = soup.find('meta', property='og:description')
        metadata['description'] = (og_description['content'].strip() if og_description and og_description.get('content')
                                   else (soup.find('meta', attrs={'name': 'description'})['content'].strip() 
                                         if soup.find('meta', attrs={'name': 'description'}) and soup.find('meta', attrs={'name': 'description'}).get('content') else ''))
        og_image = soup.find('meta', property='og:image')
        img_url_meta = og_image['content'] if og_image and og_image.get('content') else None
        if img_url_meta:
            parsed_original_url = urlparse(processed_url)
            if not urlparse(img_url_meta).scheme:
                img_path = img_url_meta if img_url_meta.startswith('/') else ('/' + img_url_meta)
                img_url_meta = f"{parsed_original_url.scheme}://{parsed_original_url.netloc}{img_path}"
            metadata['image_url'] = img_url_meta
        else:
            icon_tags_priority = [
                {'tag': 'link', 'attrs': {'rel': 'apple-touch-icon', 'href': True}},
                {'tag': 'link', 'attrs': {'rel': 'icon', 'sizes': True, 'href': True}},
                {'tag': 'link', 'attrs': {'rel': 'shortcut icon', 'href': True}},
                {'tag': 'link', 'attrs': {'rel': 'icon', 'href': True}}
            ]
            for tag_info in icon_tags_priority:
                icon_link = soup.find(tag_info['tag'], attrs=tag_info['attrs'])
                if icon_link and icon_link.get('href'):
                    img_url_icon = icon_link['href']
                    parsed_original_url = urlparse(processed_url)
                    if not urlparse(img_url_icon).scheme:
                        img_path = img_url_icon if img_url_icon.startswith('/') else ('/' + img_url_icon)
                        img_url_icon = f"{parsed_original_url.scheme}://{parsed_original_url.netloc}{img_path}"
                    metadata['image_url'] = img_url_icon
                    break
    except Exception as e:
        print(f"Error en fetch_metadata para {url_to_fetch}: {e}")
    return metadata

# --- Rutas CRUD ---
@app.route('/')
def index():
    db = get_db()
    cur_sections = db.cursor()
    cur_sections.execute("SELECT * FROM sections ORDER BY name")
    sections_data_raw = cur_sections.fetchall()
    sections_with_data = []
    for section_row_raw in sections_data_raw:
        section = dict(section_row_raw)
        cur_entries = db.cursor()
        cur_entries.execute("SELECT * FROM link_entries WHERE section_id = ? ORDER BY created_at DESC", (section['id'],))
        link_entries_for_section = []
        for entry_row_raw in cur_entries.fetchall():
            entry = dict(entry_row_raw)
            cur_urls = db.cursor()
            cur_urls.execute("SELECT * FROM entry_urls WHERE link_entry_id = ? ORDER BY id", (entry['id'],))
            entry['urls'] = [dict(url_row_raw) for url_row_raw in cur_urls.fetchall()]
            link_entries_for_section.append(entry)
        section['link_entries'] = link_entries_for_section
        sections_with_data.append(section)
    all_sections_for_dropdown = [dict(s) for s in sections_data_raw] # Reutilizar para dropdown
    return render_template('index.html', sections_with_data=sections_with_data, all_sections=all_sections_for_dropdown)

@app.route('/add_section', methods=['POST'])
def add_section():
    name = request.form.get('section_name', '').strip()
    if name:
        db = get_db()
        try:
            db.execute("INSERT INTO sections (name) VALUES (?)", (name,))
            db.commit()
            flash(f"Sección '{name}' creada.", "success")
        except sqlite3.IntegrityError:
            flash(f"La sección '{name}' ya existe.", "warning")
    else:
        flash("El nombre de la sección no puede estar vacío.", "error")
    return redirect(url_for('index'))

@app.route('/edit_section/<int:section_id>', methods=['POST'])
def edit_section(section_id):
    new_name = request.form.get('edit_section_name', '').strip()
    if not new_name:
        flash("El nuevo nombre de la sección no puede estar vacío.", "error")
        return redirect(url_for('index'))
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("UPDATE sections SET name = ? WHERE id = ?", (new_name, section_id))
        db.commit()
        if cur.rowcount == 0:
            flash("No se encontró la sección para editar.", "error")
        else:
            flash(f"Sección actualizada a '{new_name}'.", "success")
    except sqlite3.IntegrityError:
        flash(f"Ya existe una sección con el nombre '{new_name}'.", "warning")
    except sqlite3.Error as e:
        flash(f"Error al actualizar la sección: {e}", "error")
    return redirect(url_for('index'))

@app.route('/delete_section/<int:section_id>', methods=['POST'])
def delete_section(section_id):
    db = get_db()
    try:
        db.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        db.commit()
        flash("Sección eliminada (junto con sus entradas).", "success")
    except sqlite3.Error as e:
        flash(f"Error al eliminar la sección: {e}", "error")
    return redirect(url_for('index'))

@app.route('/add_link_entry', methods=['POST'])
def add_link_entry():
    title_from_form = request.form.get('link_title', '').strip()
    description_from_form = request.form.get('link_description', '').strip()
    section_id = request.form.get('section_id')
    urls_data = []
    i = 0
    while True:
        url_field_name = f'urls[{i}][url]'
        if url_field_name not in request.form: break
        url_val = request.form.get(url_field_name)
        label_val = request.form.get(f'urls[{i}][label]', '')
        if url_val is not None:
            url_val_stripped = url_val.strip()
            if url_val_stripped: urls_data.append({'url': url_val_stripped, 'label': label_val.strip()})
        i += 1
        if i > 50: break
    if not section_id or not urls_data:
        flash("Sección y al menos una URL válida son requeridas.", "error")
        return redirect(url_for('index'))

    image_url_to_save = None
    custom_image_file = request.files.get('custom_image_file')
    if custom_image_file and custom_image_file.filename != '' and allowed_file(custom_image_file.filename):
        filename_base = secure_filename(custom_image_file.filename)
        unique_filename = str(uuid.uuid4().hex[:8]) + "_" + filename_base
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        try:
            custom_image_file.save(filepath)
            image_url_to_save = os.path.join('uploads', unique_filename).replace("\\", "/")
        except Exception as e: print(f"Error al guardar imagen: {e}")
    
    metadata = fetch_metadata(urls_data[0]['url'])
    if not image_url_to_save and metadata.get('image_url'): image_url_to_save = metadata['image_url']
    title_to_save = title_from_form if title_from_form else metadata.get('title', urls_data[0]['url'])
    description_to_save = description_from_form if description_from_form else metadata.get('description', '')
    
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("INSERT INTO link_entries (title, description, image_url, section_id) VALUES (?, ?, ?, ?)",
                    (title_to_save, description_to_save, image_url_to_save, section_id))
        link_entry_id = cur.lastrowid
        for url_item in urls_data:
            if url_item['url']:
                cur.execute("INSERT INTO entry_urls (link_entry_id, url, label) VALUES (?, ?, ?)",
                            (link_entry_id, url_item['url'], url_item['label']))
        db.commit()
        flash("Nueva entrada de enlace añadida.", "success")
    except sqlite3.Error as e:
        db.rollback()
        flash(f"Error de BD al añadir entrada: {e}", "error")
    return redirect(url_for('index'))

@app.route('/edit_link_entry/<int:entry_id>', methods=['POST'])
def edit_link_entry(entry_id):
    title_from_form = request.form.get('edit_link_title', '').strip()
    description_from_form = request.form.get('edit_link_description', '').strip()
    section_id = request.form.get('edit_section_id')
    delete_current_image = request.form.get('delete_current_image') == 'true'

    urls_data = []
    i = 0
    while True:
        url_field_name = f'edit_urls[{i}][url]'
        url_id_field_name = f'edit_urls[{i}][id]' # Para identificar URLs existentes
        if url_field_name not in request.form and url_id_field_name not in request.form : break
        
        url_val = request.form.get(url_field_name, '').strip()
        label_val = request.form.get(f'edit_urls[{i}][label]', '').strip()
        url_id = request.form.get(url_id_field_name) # Puede ser None para nuevas URLs

        if url_val : # Solo procesar si hay una URL
            urls_data.append({'id': url_id, 'url': url_val, 'label': label_val})
        i += 1
        if i > 50: break

    if not section_id or not urls_data:
        flash("Sección y al menos una URL válida son requeridas para editar.", "error")
        return redirect(url_for('index'))

    db = get_db()
    cur = db.cursor()
    
    # Obtener imagen actual para posible eliminación o si no se sube nueva
    cur.execute("SELECT image_url FROM link_entries WHERE id = ?", (entry_id,))
    current_entry_data = cur.fetchone()
    if not current_entry_data:
        flash("Entrada no encontrada.", "error")
        return redirect(url_for('index'))
    current_image_url = current_entry_data['image_url']
    
    image_url_to_save = current_image_url # Mantener imagen actual por defecto
    
    # Manejar subida de nueva imagen
    custom_image_file = request.files.get('edit_custom_image_file')
    if custom_image_file and custom_image_file.filename != '' and allowed_file(custom_image_file.filename):
        # Si se sube nueva imagen, eliminar la anterior si era local
        if current_image_url and not current_image_url.startswith('http') and os.path.exists(os.path.join(app.static_folder, current_image_url)):
            try: os.remove(os.path.join(app.static_folder, current_image_url))
            except OSError as e: print(f"Error al eliminar imagen anterior {current_image_url}: {e}")

        filename_base = secure_filename(custom_image_file.filename)
        unique_filename = str(uuid.uuid4().hex[:8]) + "_" + filename_base
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        try:
            custom_image_file.save(filepath)
            image_url_to_save = os.path.join('uploads', unique_filename).replace("\\", "/")
        except Exception as e:
            print(f"Error al guardar nueva imagen editada: {e}")
            image_url_to_save = current_image_url # Revertir a la actual si falla el guardado
    elif delete_current_image:
        # Si se marca para eliminar y no se sube nueva, y la actual es local
        if current_image_url and not current_image_url.startswith('http') and os.path.exists(os.path.join(app.static_folder, current_image_url)):
            try: os.remove(os.path.join(app.static_folder, current_image_url))
            except OSError as e: print(f"Error al eliminar imagen marcada {current_image_url}: {e}")
        image_url_to_save = None # Marcar para que se re-obtenga de metadatos

    # Si no hay imagen (ni actual, ni nueva, ni marcada para eliminar), o si se eliminó, intentar obtenerla de metadatos
    metadata = {}
    if not image_url_to_save and urls_data:
        metadata = fetch_metadata(urls_data[0]['url'])
        if metadata.get('image_url'):
            image_url_to_save = metadata['image_url']
    
    title_to_save = title_from_form if title_from_form else (metadata.get('title', urls_data[0]['url']) if urls_data and not title_from_form else "Entrada sin título")
    description_to_save = description_from_form if description_from_form else (metadata.get('description', '') if not description_from_form else '')

    try:
        # Actualizar la entrada principal
        cur.execute("""
            UPDATE link_entries SET title = ?, description = ?, image_url = ?, section_id = ?
            WHERE id = ?
        """, (title_to_save, description_to_save, image_url_to_save, section_id, entry_id))

        # Gestionar URLs: eliminar las que ya no están, actualizar las existentes, añadir las nuevas
        cur.execute("SELECT id FROM entry_urls WHERE link_entry_id = ?", (entry_id,))
        existing_url_ids = {row['id'] for row in cur.fetchall()}
        submitted_url_ids = {int(u['id']) for u in urls_data if u['id']} # IDs de URLs existentes que se enviaron

        urls_to_delete = existing_url_ids - submitted_url_ids
        for url_id_to_delete in urls_to_delete:
            cur.execute("DELETE FROM entry_urls WHERE id = ?", (url_id_to_delete,))

        for url_item in urls_data:
            if url_item['id']: # Actualizar URL existente
                cur.execute("UPDATE entry_urls SET url = ?, label = ? WHERE id = ? AND link_entry_id = ?",
                            (url_item['url'], url_item['label'], url_item['id'], entry_id))
            else: # Añadir nueva URL
                cur.execute("INSERT INTO entry_urls (link_entry_id, url, label) VALUES (?, ?, ?)",
                            (entry_id, url_item['url'], url_item['label']))
        db.commit()
        flash("Entrada de enlace actualizada.", "success")
    except sqlite3.Error as e:
        db.rollback()
        flash(f"Error de BD al actualizar entrada: {e}", "error")
    return redirect(url_for('index'))

@app.route('/delete_link_entry/<int:entry_id>', methods=['POST'])
def delete_link_entry(entry_id):
    db = get_db()
    # Eliminar imagen local si existe
    cur = db.cursor()
    cur.execute("SELECT image_url FROM link_entries WHERE id = ?", (entry_id,))
    row = cur.fetchone()
    if row and row['image_url'] and not row['image_url'].startswith('http'):
        image_path = os.path.join(app.static_folder, row['image_url'])
        if os.path.exists(image_path):
            try: os.remove(image_path)
            except OSError as e: print(f"Error al eliminar imagen {image_path}: {e}")
    try:
        db.execute("DELETE FROM link_entries WHERE id = ?", (entry_id,))
        db.commit()
        flash("Entrada de enlace eliminada.", "success")
    except sqlite3.Error as e:
        flash(f"Error al eliminar entrada: {e}", "error")
    return redirect(url_for('index'))

@app.route('/get_link_preview', methods=['GET'])
def get_link_preview_api():
    url_to_preview = request.args.get('url')
    if not url_to_preview: return jsonify({'error': 'URL parameter is missing'}), 400
    metadata = fetch_metadata(url_to_preview)
    return jsonify(metadata)

# Endpoint para obtener datos de una entrada para edición (usado por JS)
@app.route('/get_entry_details/<int:entry_id>', methods=['GET'])
def get_entry_details(entry_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM link_entries WHERE id = ?", (entry_id,))
    entry = cur.fetchone()
    if not entry:
        return jsonify({'error': 'Entrada no encontrada'}), 404
    
    entry_dict = dict(entry)
    cur_urls = db.cursor()
    cur_urls.execute("SELECT * FROM entry_urls WHERE link_entry_id = ? ORDER BY id", (entry_id,))
    entry_dict['urls'] = [dict(url_row) for url_row in cur_urls.fetchall()]
    
    return jsonify(entry_dict)


if __name__ == '__main__':
    # init_db() # Descomentar solo para la primera ejecución o si cambias schema.sql (y borras database.db)
    app.run(debug=True, host='0.0.0.0')