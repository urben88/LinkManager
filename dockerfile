# Usar una imagen base oficial de Python
FROM python:3.10-slim

# Establecer el directorio de trabajo en el contenedor
WORKDIR /app

# Copiar el archivo de requerimientos primero para aprovechar el cache de Docker
COPY requirements.txt requirements.txt

# Instalar las dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código de la aplicación al directorio de trabajo
COPY . .

# Crear un directorio para la base de datos si no existe y asegurar permisos
# (La base de datos se montará desde el host, pero creamos el punto de montaje)
RUN mkdir -p /app/database && chown -R www-data:www-data /app/database
# RUN mkdir -p /app/database (alternativa más simple si no necesitas cambiar propietario)


# Exponer el puerto en el que la aplicación Flask se ejecuta dentro del contenedor
EXPOSE 5000

# Comando para ejecutar la aplicación cuando el contenedor inicie
# Usaremos Gunicorn como servidor WSGI de producción en lugar del servidor de desarrollo de Flask
# CMD ["flask", "run", "--host=0.0.0.0"] # Para desarrollo
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]