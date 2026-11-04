# LinkManager

Portal de enlaces de `urbenserver`. Publicado en <https://www.urbenserver.com>.

Consta de dos vistas:

| Vista | Ruta | Quién entra |
|---|---|---|
| Tablero de enlaces | `/` | Cualquiera (leer). Editar exige sesión. |
| Servicios del servidor | `/servidor` | Solo con sesión (expone puertos y rutas internas) |

## Acceso

La edición y `/servidor` piden usuario y contraseña.

- **Usuario:** `admin` (configurable con `LINKMANAGER_USER`)
- **Contraseña:** se genera sola la primera vez y queda en
  `~/docker/stacks/apps/linkmanager/ADMIN_PASSWORD.txt` (permisos 600).
  Dentro del contenedor está en `/app/database/ADMIN_PASSWORD.txt`.

Para cambiarla, crea un `.env` junto al `compose.yaml` con:

```
LINKMANAGER_PASSWORD=tu-contraseña
```

y ejecuta `docker compose up -d --force-recreate` desde
`~/docker/stacks/apps/linkmanager`.

## Variables de entorno

| Variable | Por defecto | Qué hace |
|---|---|---|
| `LINKMANAGER_USER` | `admin` | Usuario de administración |
| `LINKMANAGER_PASSWORD` | — | Contraseña en claro (se hashea al arrancar) |
| `LINKMANAGER_PASSWORD_HASH` | — | Alternativa: hash de werkzeug ya calculado |
| `LINKMANAGER_SECRET` | fichero `secret.key` | Clave de firma de sesiones |
| `LINKMANAGER_PRIVATE` | `0` | `1` = toda la aplicación pide sesión |
| `LINKMANAGER_METADATA` | `1` | `0` = no descargar metadatos de URLs externas |
| `LINKMANAGER_MAX_UPLOAD_MB` | `8` | Tamaño máximo de imagen |
| `CATALOGO_JSON` | `/app/servicios.json` | Catálogo de servicios para `/servidor` |
| `LINKMANAGER_DB` | `/app/database/database.db` | Base de datos SQLite |
| `AGENTE_ACTIVO` | `1` | `0` = sin asistente: ni botón ni rutas `/agente/*` |
| `AGENTE_API_KEY` | — | Clave del modelo. Vive en el `.env` del stack, no aquí |
| `AGENTE_MODELO` | `deepseek-chat` | Modelo a usar |
| `AGENTE_BASE_URL` | `https://api.deepseek.com/v1` | Cualquier API compatible con OpenAI (incluido un Ollama local) |
| `AGENTE_LEER_INTERNAS` | `1` | Deja al agente leer URLs de la LAN (puertos, subdominios propios) |
| `AGENTE_INTENTOS` | `3` | Veces que puede corregir la propuesta antes de rendirse (1-6) |
| `AGENTE_TIMEOUT` | `60` | Segundos máximos por llamada al modelo |
| `AGENTE_TIMEOUT_WEB` | `12` | Segundos máximos para leer una página ajena |

## Modelo de datos

```
sections (id, name, order_index)
  └── link_entries (id, section_id, title, description, image_url, logo_url,
                    parent_id, order_index)
        ├── entry_urls (id, link_entry_id, label, link_type, value)
        └── más link_entries (parent_id → la carpeta que las contiene)
```

`link_type` puede ser `internal_app` (un puerto), `subdomain` (un subdominio) o
`external_url` (una URL completa). El selector de entorno de la cabecera decide
con qué dominio base se construyen los enlaces dinámicos.

`logo_url` es el avatar pequeño de la tarjeta y `image_url` la portada grande:
son dos cosas distintas a propósito, porque un favicon sirve como logo pero no
como portada.

`parent_id` convierte una entrada en **carpeta**: las que cuelgan de ella se
despliegan al abrirla, y la tarjeta enseña un mosaico con lo que lleva dentro.
Solo hay dos niveles; borrar una carpeta no borra su contenido, lo deja suelto.

El asistente guarda lo suyo aparte, nunca dentro de las tablas del portal:

```
agente_conversaciones (id, creada, actualizada)
  ├── agente_mensajes (id, conversacion_id, rol, contenido, traza)
  └── agente_propuestas (id, conversacion_id, plan_json, estado, resultado_json)
```

## El asistente (agente de IA)

Con sesión iniciada, el botón **Asistente** de la cabecera abre un cajón donde se
le pegan enlaces y se le cuenta qué se quiere. Él los lee, mira qué hay ya en el
portal y **propone** secciones, tarjetas y carpetas. Nada se guarda hasta que el
usuario pulsa **Aplicar** en la tarjeta de la propuesta.

El flujo, en corto:

1. `agente.py` monta un agente de LangChain (`langchain-core` + `langchain-openai`)
   con cuatro herramientas: `leer_enlaces`, `consultar_portal`,
   `buscar_en_portal` y `proponer_plan`.
2. `proponer_plan` **no escribe en el portal**: valida el plan y lo guarda en
   `agente_propuestas` como pendiente. Es el único camino de escritura que tiene
   el modelo.
3. `POST /agente/aplicar/<id>` es el que escribe de verdad, en una transacción y
   una sola vez (la segunda devuelve «ya está aplicada»). Crea secciones, inserta
   entradas, resuelve los grupos y mueve entradas entre secciones.

Lo que **no** puede hacer: borrar. No hay herramienta para ello y el servidor
rechaza cualquier plan que no sea crear o mover.

### El JSON de la propuesta y su validación

Acepta tanto enlaces sueltos como **texto sin ordenar** (notas, una lista
pegada de un chat, nombres con enlaces a mitad). De ahí saca las tarjetas y las
agrupa. Lo que propone siempre tiene esta forma, y es lo que se guarda:

```json
{
  "version": 1,
  "resumen": "una o dos frases",
  "secciones_nuevas": ["Nombre"],
  "entradas": [
    {
      "titulo": "Plex",
      "seccion": "Peliculas/Videos 📼",
      "descripcion": "Servidor multimedia",
      "dentro_de": "",
      "urls": [
        {"valor": "https://www.plex.tv/", "etiqueta": "Web oficial", "tipo": "external_url"},
        {"valor": "32400", "etiqueta": "Mi servidor", "tipo": "internal_app"}
      ]
    }
  ],
  "movimientos": [{"entrada": "Immich", "seccion_destino": "IA"}]
}
```

La validación corre **en el servidor** y distingue dos cosas:

| | Qué es | Qué pasa |
|---|---|---|
| **Errores** | falta el resumen, un título, la sección o un enlace; puerto que no es un número; subdominio sin punto; URL que no es un dominio; dos tarjetas con el mismo título en la misma sección; más de 40 entradas | la propuesta **no se guarda**: se le devuelven los errores al modelo y la corrige |
| **Avisos** | la sección ya existe, la tarjeta ya está en el portal, el grupo no aparece | se aplica igual y se avisa en la tarjeta |

Hay un número **limitado de intentos** (`AGENTE_INTENTOS`, por defecto 3). Si
los agota, no se crea ninguna propuesta y el chat dice «no he podido generar
una propuesta válida» con los motivos. Nunca se queda dando vueltas.

Una entrada que solo hace de **carpeta** (otra cuelga de ella con `dentro_de`)
puede ir sin `urls`: la tarjeta se dibuja con el mosaico de sus hijas y no repite
sus enlaces.

En la tarjeta de propuesta, **Ver JSON** enseña exactamente ese objeto y permite
copiarlo.

Detalles que importan:

- La conversación vive en SQLite, no en memoria: gunicorn corre 4 workers y cada
  petición puede caer en uno distinto.
- El bucle de herramientas es explícito (`bind_tools` + `tool_calls`) con tope de
  pasos, tiempo y tamaño de texto leído. Si el modelo falla, el portal sigue en
  pie y el error se pinta en el hilo.
- La portada de una tarjeta nueva se saca del `og:image` de su enlace, igual que
  cuando se añade a mano; si no hay, la tarjeta usa el monograma.
- Sin `AGENTE_API_KEY` (o con `AGENTE_ACTIVO=0`) el botón no aparece y las rutas
  `/agente/*` responden 503. El portal funciona exactamente igual que antes.

## Imágenes

`tools/imagenes.py` rellena logos y portadas. Se ejecuta dentro del contenedor:

```bash
docker exec linkmanager_web python3 /app/tools/imagenes.py --seco --detalle  # ver el plan
docker exec linkmanager_web python3 /app/tools/imagenes.py                   # hacerlo
```

Regla: **nunca una imagen pixelada**. Un logo puede ser un SVG; una portada no,
salvo que sea grande. Si no aparece ninguna portada de calidad se hace una
**captura** del servicio con el Chromium que viene en la imagen, y si tampoco es
posible se retira la portada en lugar de dejar una mala.

## Subdivisiones

Una entrada se puede colocar «dentro de» otra al crearla o editarla. La de arriba
se dibuja como una carpeta del iPhone: mosaico con las imágenes de hasta cuatro
hijas, y al abrirla el panel entra con un zoom suave y las tarjetas aparecen
escalonadas.

## Dónde viven los datos

- **Base de datos:** volumen Docker `link-manager_db_data` → `/app/database`.
- **Imágenes subidas:** `/app/database/uploads`. **Dentro del volumen**, para que
  sobrevivan a recrear el contenedor. Se sirven por `/uploads/<fichero>`.

## Endurecimiento aplicado

- Sesión obligatoria para editar, para `/servidor` y para toda la API de detalle.
- Token CSRF en todos los formularios y en las llamadas JSON.
- Clave de firma de sesiones **estable** (antes era aleatoria por worker).
- Escapado de HTML en el cliente: el modal de edición ya no inyecta datos sin filtrar.
- Guarda anti-SSRF al leer metadatos de URLs externas (bloquea direcciones internas).
- Las subidas se validan por **contenido real** (firma del fichero), no por extensión,
  y con límite de tamaño.
- Cabeceras `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`.
- Los borrados piden **doble confirmación**: el primer clic pregunta, el segundo borra.

## La página /servidor

`/servidor` lista los servicios reales del servidor cruzando tres fuentes, y la
regenera un cron cada 10 minutos mediante `~/docker/tools/generar-catalogo.py`:

| Fuente | Qué aporta |
|---|---|
| `docker ps` / `inspect` | contenedores, puertos publicados y proyecto compose |
| Nginx Proxy Manager | el subdominio público de cada contenedor |
| Coolify | el dominio de las aplicaciones desplegadas ahí |

El resultado se monta en el contenedor como `/app/servicios.json` (solo lectura).

## Interfaz

Sin Bootstrap ni jQuery: solo CSS y JavaScript propios, más SortableJS servido
desde `static/vendor/`. Se puede buscar (atajo `/`), plegar secciones, alternar
entre vista compacta y con portada, cambiar el entorno de los enlaces y, con
sesión iniciada, arrastrar tarjetas y secciones para reordenarlas.

## Desarrollo

```bash
cd ~/docker/stacks/apps/linkmanager
docker compose build && docker compose up -d --force-recreate
docker compose logs -f web
```
