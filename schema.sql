-- Elimina las tablas si ya existen para permitir una reinicialización limpia.
DROP TABLE IF EXISTS entry_urls;
DROP TABLE IF EXISTS link_entries;
DROP TABLE IF EXISTS sections;
DROP TABLE IF EXISTS settings;

-- Tabla para almacenar la configuración de la aplicación, como los dominios.
CREATE TABLE settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL
);

-- Tabla para las secciones que agrupan las entradas de enlaces.
CREATE TABLE sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tabla para las entradas individuales (las tarjetas con imagen, título, etc.).
CREATE TABLE link_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    image_url TEXT,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (section_id) REFERENCES sections (id) ON DELETE CASCADE
);

-- Tabla para los enlaces específicos dentro de cada entrada.
CREATE TABLE entry_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_entry_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    link_type TEXT NOT NULL, -- 'internal_app' o 'external_url'
    value TEXT NOT NULL,
    FOREIGN KEY (link_entry_id) REFERENCES link_entries (id) ON DELETE CASCADE
);

-- Inserta valores de configuración por defecto si se desea.
INSERT INTO settings (setting_key, setting_value) VALUES 
('domain_public', 'http://example.com'),
('domain_lan', 'http://192.168.1.100'),
('domain_local', 'http://localhost');