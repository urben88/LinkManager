import sqlite3
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, jsonify, g, flash
from urllib.parse import urlparse
import os
import uuid
from werkzeug.utils import secure_filename

# Ignorar advertencias de tipo para requests y bs4 si usas un linter estricto
# type: ignore

app = Flask(__name__)
app.secret_key = os.urandom(24)
DATABASE = 'database.db'

# Configuración de la carpeta de subidas
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    try:
        os.makedirs(UPLOAD_FOLDER)
    except OSError as e:
        print(f"Error al crear la carpeta de subidas {UPLOAD_FOLDER}: {e}")

# --- Funciones de Base de Datos y Configuración ---
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
            print("Base de datos inicializada con el nuevo esquema.")
        except Exception as e:
            print(f"Error al inicializar la base de datos desde schema.sql: {e}")

def get_app_settings():
    db = get_db()
    settings_rows = db.execute("SELECT setting_key, setting_value FROM settings").fetchall()
    settings = {row['setting_key']: row['setting_value'] for row in settings_rows}
    return {
        'public': settings.get('domain_public', ''),
        'lan': settings.get('domain_lan', ''),
        'local': settings.get('domain_local', '')
    }

# --- Funciones de Ayuda ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def fetch_metadata(url_to_fetch):
    metadata = {'title': url_to_fetch, 'description': '', 'image_url': ''}
    try:
        processed_url = url_to_fetch
        if not processed_url.startswith(('http://', 'https://')):
            processed_url = 'http://' + processed_url
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(processed_url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        og_title = soup.find('meta', property='og:title')
        metadata['title'] = og_title['content'].strip() if og_title and og_title.get('content') else (soup.find('title').string.strip() if soup.find('title') and soup.find('title').string else url_to_fetch)
        og_description = soup.find('meta', property='og:description')
        metadata['description'] = og_description['content'].strip() if og_description and og_description.get('content') else (soup.find('meta', attrs={'name': 'description'})['content'].strip() if soup.find('meta', attrs={'name': 'description'}) and soup.find('meta', attrs={'name': 'description'}).get('content') else '')
        og_image = soup.find('meta', property='og:image')
        img_url_meta = og_image['content'] if og_image and og_image.get('content') else None
        if img_url_meta:
            parsed_original_url = urlparse(processed_url)
            if not urlparse(img_url_meta).scheme:
                img_path = img_url_meta if img_url_meta.startswith('/') else ('/' + img_url_meta)
                img_url_meta = f"{parsed_original_url.scheme}://{parsed_original_url.netloc}{img_path}"
            metadata['image_url'] = img_url_meta
    except Exception as e:
        print(f"Error en fetch_metadata para {url_to_fetch}: {e}")
    return metadata

# --- Rutas CRUD y Principales ---

@app.route('/')
def index():
    db = get_db()
    sections_query = "SELECT * FROM sections ORDER BY order_index, name"
    sections_raw = db.execute(sections_query).fetchall()
    
    sections = {s['id']: dict(s) for s in sections_raw}
    for s_id in sections:
        sections[s_id]['link_entries'] = []

    entries_query = "SELECT * FROM link_entries ORDER BY order_index, created_at DESC"
    entries_raw = db.execute(entries_query).fetchall()
    entries = {e['id']: dict(e) for e in entries_raw}
    for e_id in entries:
        entries[e_id]['urls'] = []
        
    urls_query = "SELECT * FROM entry_urls ORDER BY id"
    urls_raw = db.execute(urls_query).fetchall()
    
    for url in urls_raw:
        if url['link_entry_id'] in entries:
            entries[url['link_entry_id']]['urls'].append(dict(url))

    for entry in entries.values():
        if entry['section_id'] in sections:
            sections[entry['section_id']]['link_entries'].append(entry)

    sections_with_data = list(sections.values())
    all_sections_for_dropdown = [dict(s) for s in sections_raw]

    app_domains = get_app_settings()
    
    return render_template('index.html', sections_with_data=sections_with_data, all_sections=all_sections_for_dropdown, app_domains=app_domains)

@app.route('/update_settings', methods=['POST'])
def update_settings():
    db = get_db()
    try:
        # Aseguramos que las URLs tengan protocolo para un parseo correcto en el frontend
        def format_url(url_string):
            if not url_string.strip():
                return ''
            if not url_string.startswith(('http://', 'https://')):
                return 'http://' + url_string
            return url_string

        db.execute("INSERT OR REPLACE INTO settings (setting_key, setting_value) VALUES (?, ?)", 
                   ('domain_public', format_url(request.form.get('domain_public', ''))))
        db.execute("INSERT OR REPLACE INTO settings (setting_key, setting_value) VALUES (?, ?)", 
                   ('domain_lan', format_url(request.form.get('domain_lan', ''))))
        db.execute("INSERT OR REPLACE INTO settings (setting_key, setting_value) VALUES (?, ?)", 
                   ('domain_local', format_url(request.form.get('domain_local', ''))))
        db.commit()
        flash("Configuración de entorno actualizada.", "success")
    except sqlite3.Error as e:
        db.rollback()
        flash(f"Error al actualizar la configuración: {e}", "error")
    return redirect(url_for('index'))

@app.route('/update_order', methods=['POST'])
def update_order():
    data = request.get_json()
    order_type = data.get('type')
    order_ids = data.get('order', [])
    
    if not order_type or not order_ids:
        return jsonify({'status': 'error', 'message': 'Datos inválidos'}), 400
        
    db = get_db()
    try:
        table_name = ''
        if order_type == 'sections':
            table_name = 'sections'
        elif order_type == 'entries':
            table_name = 'link_entries'
            if 'section_id' in data and 'entry_id' in data:
                db.execute("UPDATE link_entries SET section_id = ? WHERE id = ?", (int(data['section_id']), int(data['entry_id'])))
        else:
            return jsonify({'status': 'error', 'message': 'Tipo inválido'}), 400

        for index, item_id in enumerate(order_ids):
            db.execute(f"UPDATE {table_name} SET order_index = ? WHERE id = ?", (index, int(item_id)))
        
        db.commit()
        return jsonify({'status': 'success'})
        
    except (sqlite3.Error, ValueError) as e:
        db.rollback()
        print(f"Error al actualizar orden: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
        if cur.rowcount == 0: flash("No se encontró la sección para editar.", "error")
        else: flash(f"Sección actualizada a '{new_name}'.", "success")
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
        flash("Sección eliminada.", "success")
    except sqlite3.Error as e:
        flash(f"Error al eliminar la sección: {e}", "error")
    return redirect(url_for('index'))

@app.route('/add_link_entry', methods=['POST'])
def add_link_entry():
    title_from_form = request.form.get('link_title', '').strip()
    description_from_form = request.form.get('link_description', '').strip()
    section_id = request.form.get('section_id')

    # --- VALIDACIÓN DE TÍTULO OBLIGATORIO ---
    if not title_from_form:
        flash("El título de la entrada es obligatorio.", "error")
        return redirect(url_for('index'))

    urls_data = []
    i = 0
    while f'urls[{i}][type]' in request.form:
        link_type = request.form[f'urls[{i}][type]']
        # La etiqueta ahora es opcional
        label = request.form.get(f'urls[{i}][label]', '').strip() 
        value = request.form.get(f'urls[{i}][value]', '').strip()
        # Solo se requiere que el valor (puerto, subdominio o URL) exista
        if value:
            urls_data.append({'label': label, 'link_type': link_type, 'value': value})
        i += 1

    if not section_id or not urls_data:
        flash("Sección y al menos un enlace con valor son requeridos.", "error")
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
        except Exception as e:
            print(f"Error al guardar imagen: {e}")
    
    # Si no hay imagen, intentamos obtenerla de metadatos (solo si hay URL externa)
    if not image_url_to_save:
        first_external_url = next((u['value'] for u in urls_data if u['link_type'] == 'external_url'), None)
        if first_external_url:
            metadata = fetch_metadata(first_external_url)
            image_url_to_save = metadata.get('image_url')

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("INSERT INTO link_entries (title, description, image_url, section_id) VALUES (?, ?, ?, ?)",
                    (title_from_form, description_from_form, image_url_to_save, section_id))
        link_entry_id = cur.lastrowid
        for url_item in urls_data:
            cur.execute("INSERT INTO entry_urls (link_entry_id, label, link_type, value) VALUES (?, ?, ?, ?)",
                        (link_entry_id, url_item['label'], url_item['link_type'], url_item['value']))
        db.commit()
        flash("Nueva entrada añadida.", "success")
    except sqlite3.Error as e:
        db.rollback()
        flash(f"Error de BD al añadir entrada: {e}", "error")
    return redirect(url_for('index'))

@app.route('/edit_link_entry/<int:entry_id>', methods=['POST'])
def edit_link_entry(entry_id):
    title = request.form.get('link_title', '').strip()
    
    # --- VALIDACIÓN DE TÍTULO OBLIGATORIO ---
    if not title:
        flash("El título no puede estar vacío.", "error")
        # Aquí sería ideal recargar el modal, pero por simplicidad redirigimos
        return redirect(url_for('index'))

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT image_url FROM link_entries WHERE id = ?", (entry_id,))
    current_entry = cur.fetchone()
    if not current_entry:
        flash("La entrada que intentas editar no existe.", "error")
        return redirect(url_for('index'))
    current_image_url = current_entry['image_url']

    description = request.form.get('link_description', '').strip()
    section_id = request.form.get('section_id')
    delete_image = request.form.get('delete_current_image') == 'on'

    image_url_to_save = current_image_url
    new_image_file = request.files.get('custom_image_file')

    if delete_image and not new_image_file:
        if current_image_url and current_image_url.startswith('uploads/'):
            try:
                os.remove(os.path.join(app.static_folder, current_image_url))
            except OSError as e:
                print(f"Error al eliminar imagen marcada {current_image_url}: {e}")
        image_url_to_save = None

    if new_image_file and new_image_file.filename != '' and allowed_file(new_image_file.filename):
        if current_image_url and current_image_url.startswith('uploads/'):
            try:
                os.remove(os.path.join(app.static_folder, current_image_url))
            except OSError as e:
                print(f"Error al eliminar imagen anterior {current_image_url}: {e}")
        
        filename_base = secure_filename(new_image_file.filename)
        unique_filename = str(uuid.uuid4().hex[:8]) + "_" + filename_base
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        try:
            new_image_file.save(filepath)
            image_url_to_save = os.path.join('uploads', unique_filename).replace("\\", "/")
        except Exception as e:
            print(f"Error al guardar nueva imagen: {e}")

    submitted_urls = []
    i = 0
    while f'urls[{i}][id]' in request.form:
        url_id = request.form.get(f'urls[{i}][id]')
        label = request.form.get(f'urls[{i}][label]', '').strip()
        link_type = request.form.get(f'urls[{i}][type]')
        value = request.form.get(f'urls[{i}][value]', '').strip()
        # Solo se requiere que el valor exista, no la etiqueta
        if value:
            submitted_urls.append({'id': url_id, 'label': label, 'link_type': link_type, 'value': value})
        i += 1

    try:
        cur.execute("UPDATE link_entries SET title = ?, description = ?, image_url = ?, section_id = ? WHERE id = ?",
                    (title, description, image_url_to_save, section_id, entry_id))

        cur.execute("SELECT id FROM entry_urls WHERE link_entry_id = ?", (entry_id,))
        existing_url_ids = {str(row['id']) for row in cur.fetchall()}
        submitted_url_ids = {u['id'] for u in submitted_urls if u['id'] != 'new'}
        
        urls_to_delete = existing_url_ids - submitted_url_ids
        for url_id in urls_to_delete:
            cur.execute("DELETE FROM entry_urls WHERE id = ?", (url_id,))

        for url in submitted_urls:
            if url['id'] == 'new':
                cur.execute("INSERT INTO entry_urls (link_entry_id, label, link_type, value) VALUES (?, ?, ?, ?)",
                            (entry_id, url['label'], url['link_type'], url['value']))
            else:
                cur.execute("UPDATE entry_urls SET label = ?, link_type = ?, value = ? WHERE id = ?",
                            (url['label'], url['link_type'], url['value'], url['id']))

        db.commit()
        flash("Entrada actualizada correctamente.", "success")
    except sqlite3.Error as e:
        db.rollback()
        flash(f"Error de base de datos al actualizar: {e}", "error")

    return redirect(url_for('index'))

@app.route('/delete_link_entry/<int:entry_id>', methods=['POST'])
def delete_link_entry(entry_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT image_url FROM link_entries WHERE id = ?", (entry_id,))
    row = cur.fetchone()
    if row and row['image_url'] and row['image_url'].startswith('uploads/'):
        image_path = os.path.join(app.static_folder, row['image_url'])
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except OSError as e:
                print(f"Error al eliminar imagen {image_path}: {e}")
    try:
        db.execute("DELETE FROM link_entries WHERE id = ?", (entry_id,))
        db.commit()
        flash("Entrada eliminada.", "success")
    except sqlite3.Error as e:
        flash(f"Error al eliminar entrada: {e}", "error")
    return redirect(url_for('index'))

@app.route('/get_entry_details/<int:entry_id>', methods=['GET'])
def get_entry_details(entry_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM link_entries WHERE id = ?", (entry_id,))
    entry = cur.fetchone()
    if not entry:
        return jsonify({'error': 'Entrada no encontrada'}), 404
    
    entry_dict = dict(entry)
    
    urls_cur = db.cursor()
    urls_cur.execute("SELECT * FROM entry_urls WHERE link_entry_id = ? ORDER BY id", (entry_id,))
    entry_dict['urls'] = [dict(url_row) for url_row in urls_cur.fetchall()]

    all_sections_cur = db.cursor()
    all_sections_cur.execute("SELECT id, name FROM sections ORDER BY order_index, name")
    entry_dict['all_sections'] = [dict(row) for row in all_sections_cur.fetchall()]

    return jsonify(entry_dict)

if __name__ == '__main__':
    # Descomenta la siguiente línea UNA SOLA VEZ para crear/reiniciar la base de datos
    # init_db()
    app.run(debug=True, host='0.0.0.0')