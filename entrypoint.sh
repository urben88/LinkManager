#!/bin/sh

# Si no existe la base de datos, la crea
if [ ! -f /app/database/database.db ]; then
  echo "Inicializando base de datos..."
  python3 -c "from app import init_db; init_db()"
fi

# Gunicorn con hilos: la consola usa websockets y cada terminal abierta ocupa
# un hilo mientras está conectada (el asistente también tiene peticiones largas).
exec gunicorn -w 4 -k gthread --threads 16 --timeout 120 -b 0.0.0.0:5000 app:app
