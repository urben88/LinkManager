#!/bin/sh

# Si no existe la base de datos, la crea
if [ ! -f /app/database/database.db ]; then
  echo "Inicializando base de datos..."
  python3 -c "from app import init_db; init_db()"
fi

# Ejecutar Gunicorn como servidor WSGI
exec gunicorn -w 4 -b 0.0.0.0:5000 app:app
