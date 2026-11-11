# LinkManager

Portal de enlaces de `urbenserver`. Publicado en <https://www.urbenserver.com>.

Consta de dos vistas:

| Vista | Ruta | Quién entra |
|---|---|---|
| Tablero de enlaces | `/` | Cualquiera (leer). Editar exige sesión. |
| Servicios del servidor | `/servidor` | Solo con sesión (expone puertos y rutas internas) |

## Acceso, roles y seguridad del login

| Rol | Qué puede hacer |
|---|---|
| `editor` | Editar enlaces, asistente de enlaces, monitor, `/servidor` |
| `admin` | Todo lo anterior + **consola del servidor** (exige 2FA) |

- **Usuarios en la base** (`usuarios`). El primero (`admin`) se crea solo con la
  contraseña de `ADMIN_PASSWORD.txt` (o `LINKMANAGER_PASSWORD` si está en el `.env`;
  en ese caso el `.env` manda en cada arranque).
- **Sesiones de 30 días** guardadas en el servidor (`sesiones`): caducan antes si
  pasan 7 días sin uso, y se pueden cerrar desde otro sitio (CLI o «Cerrar mis
  otras sesiones»). Salir invalida la sesión de verdad, no solo la cookie.
- **2FA (TOTP)**: con él activado, el login pide el código de la app. Un código no
  vale dos veces. Se activa **solo desde el servidor**, nunca desde la web.
- **Límites** en SQLite (compartidos por los workers): 10 fallos por IP cada
  15 min, y 5 códigos de 2FA malos por usuario cada 15 min (desde cualquier IP).
- **IP real**: solo se cree a `X-Real-IP` si la petición viene del contenedor de
  Nginx Proxy Manager. Cookie `Secure` cuando se entra por HTTPS, HSTS y una CSP
  sin JavaScript en línea.
- **Registro** de logins, fallos y uso de la consola en `accesos`.

Gestión, siempre desde el servidor:

```bash
U="docker exec -it linkmanager_web python3 /app/tools/usuarios.py"
$U listar
$U 2fa admin              # QR para la app de códigos (Aegis, Google Authenticator…)
$U crear maria --rol editor
$U clave admin            # cambia la contraseña y cierra sus sesiones
$U sesiones               # quién tiene sesión abierta, desde dónde
$U cerrar-sesiones admin  # echa a todo el mundo de esa cuenta
$U registro 50            # últimos accesos
```

## La consola del servidor

En el cajón del **Asistente**, los `admin` ven una segunda pestaña, **Servidor**:
terminales reales del servidor como el usuario `urben`, con botones para abrir
una **Terminal** (bash), **Claude** (Claude Code) u **OpenCode**. El cajón se
ensancha y puede ocupar toda la pantalla.

- Pide el código de 2FA para desbloquearse y lo vuelve a pedir cada
  `CONSOLA_DESBLOQUEO_HORAS` (8). Entrar con 2FA ya la deja desbloqueada.
- Las terminales **viven en el servidor**: cerrar la pestaña o perder la conexión
  no las mata; al volver se reengancha con lo último que salió por pantalla.
- `urben` tiene `sudo` y `docker`: **la consola equivale a root**. Por eso todas
  las capas: sesión en servidor → rol admin → 2FA reciente → CSRF → Origin del
  propio portal + ticket de un solo uso (30 s) para el websocket → firma HMAC
  hacia el puente.

Cómo está montado:

```
navegador ──wss──▶ NPM ──▶ linkmanager_web (flask-sock, relé)
                               │  socket UNIX montado + HMAC
                               ▼
                 consola-puente (host, systemd --user, como urben)
                               └─ pty: bash -l / claude / opencode
```

`consola-puente/` (fuera de la imagen) tiene el servicio. Instalar o actualizar:

```bash
~/Escritorio/apps/LinkManager/consola-puente/instalar.sh
```

Crea el socket en `~/.local/share/consola-puente/` y el secreto de firma en
`~/.config/consola-puente/secreto` (600); los dos se montan en el contenedor.
Para apagar la consola: `CONSOLA_ACTIVA: "0"` en el compose, o
`systemctl --user stop consola-puente`. Reiniciar el puente cierra las terminales.

## Registros de herramientas

Los administradores tienen un visor en `/registros`. Cada herramienta recibe
un token propio (se crea desde esa página o con
`docker exec -it linkmanager_web python3 /app/tools/registros.py crear NOMBRE`);
el token solo se muestra una vez y en la base queda su SHA-256. El nombre del
token es la fuente que separa los registros.

La herramienta hace un `POST` autenticado con ese token:

```bash
curl -X POST https://www.urbenserver.com/api/ingesta \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"tipo":"log","texto":"hola","ruta":"/","usuario":"yo"}'
```

Campos recomendados: `tipo`, `fecha` (ISO 8601), `ruta`, `usuario`, `texto` y
`datos`. Cualquier JSON extra se guarda tal cual. Si `fecha` (o `idempotencia`) viene informada,
un reintento con el mismo contenido no duplica el registro. El visor permite
filtrar por fuente, buscar, copiar el JSON/texto, exportar a JSONL o CSV y
borrar registros o tokens.

## Variables de entorno

| Variable | Por defecto | Qué hace |
|---|---|---|
| `LINKMANAGER_USER` | `admin` | Usuario de administración |
| `LINKMANAGER_PASSWORD` | — | Contraseña en claro (se hashea al arrancar) |
| `LINKMANAGER_PASSWORD_HASH` | — | Alternativa: hash de werkzeug ya calculado |
| `LINKMANAGER_SESION_DIAS` | `30` | Duración máxima de una sesión |
| `LINKMANAGER_SESION_INACTIVA_DIAS` | `7` | Caduca antes si no se usa en estos días |
| `LINKMANAGER_PROXIES` | `nginx-proxy-manager` | Únicos orígenes cuyo `X-Real-IP` se cree |
| `AGENTE_CONSULTAS` | `1` | `0` = el asistente no puede consultar el servidor |
| `CONSOLA_ACTIVA` | `0` | `1` = acceso «Servidor» para los `admin` |
| `CONSOLA_DESBLOQUEO_HORAS` | `8` | Cada cuánto vuelve a pedir el 2FA la consola |
| `CONSOLA_SOCKET` | `/consola-puente/consola.sock` | Socket del puente |
| `CONSOLA_SECRETO_FICHERO` | `/run/secrets/consola-puente` | Secreto HMAC compartido con el puente |
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
| `AGENTE_LIMITE_SESION` | `30` | Consultas por sesión cada 15 minutos (freno de gasto) |
| `AGENTE_LIMITE_HORA` | `120` | Consultas por hora en todo el portal |
| `AGENTE_TIMEOUT` | `60` | Segundos máximos por llamada al modelo |
| `AGENTE_TIMEOUT_WEB` | `12` | Segundos máximos para leer una página ajena |
| `MONITOR_ACTIVO` | `1` | `0` = sin panel de estado: ni botón ni ruta `/monitor/datos` |
| `MONITOR_URL` | `http://glances:61208` | Dónde escucha Glances (misma red docker) |
| `MONITOR_EQUIPO` | `urbenserver` | Nombre que se muestra en el panel |
| `MONITOR_TIMEOUT` | `2.5` | Segundos máximos esperando a Glances |

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

### Seguridad y gasto

- **Solo con sesión.** Las cinco rutas `/agente/*` exigen login: sin sesión
  redirigen a `/login`, aunque se lleve un token CSRF válido. El botón no se
  pinta si no has entrado.
- **CSRF** en todos los POST (como el resto de la aplicación).
- **Frenos de gasto**: `AGENTE_LIMITE_SESION` consultas cada 15 minutos por
  sesión y `AGENTE_LIMITE_HORA` por hora en todo el portal (esta última se cuenta
  en la base, porque los 4 workers de gunicorn no comparten memoria). Al pasarse,
  respuesta 429 con un mensaje claro.
- **`Cache-Control: no-store`** y `X-Robots-Tag: noindex` en las respuestas del
  asistente: el hilo lleva notas privadas.
- **La clave nunca sale del proceso**: no se guarda en la base, no se registra en
  los logs y cualquier texto de error se limpia antes de devolverse
  (`_sin_secretos`).
- **Rotar la clave**: se edita `AGENTE_API_KEY` en el `.env` del stack
  (`chmod 600`) y se recrea el contenedor. No hay que reconstruir la imagen.

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

### Consultas de solo lectura al servidor

El asistente tiene la herramienta `consultar_servidor`: cuando le preguntas por el
hardware o el software («¿qué CPU tiene?», «¿hay servicios caídos?») ejecuta la
consulta y contesta con el dato, en vez de decirte qué comando usar.

No recibe comandos, recibe el **nombre** de una consulta de un catálogo cerrado
que vive en el puente (`CONSULTAS` en `consola-puente/puente.py`):

| Consulta | Qué ejecuta (ruta absoluta, argumentos fijos, sin shell ni sudo) |
|---|---|
| `resumen` | `hostnamectl`, `/etc/os-release`, `uname -srvmo`, `uptime` |
| `cpu` | `lscpu` (sin la lista de flags), `/proc/loadavg` |
| `memoria` | `free -h --si`, `swapon --show` |
| `placa` | `/sys/class/dmi/id/*` legibles sin root (sin números de serie) |
| `gpu` | `lspci -nn` |
| `usb` | `lsusb` |
| `temperaturas` | `sensors` |
| `discos` | `lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,ROTA,TRAN`, `df -hT` |
| `montajes` | `findmnt -D` (solo sistemas de ficheros reales) |
| `red` | `ip -br addr` (sin veth), `ip route`, `ss -tulnH` |
| `procesos` | `ps -eo pid,user,pcpu,pmem,etime,comm` (solo nombre, nunca argumentos) |
| `servicios` | `systemctl --failed`, servicios en marcha (sistema y usuario), `list-timers` |
| `docker` | `docker ps -a` (nombre, imagen, estado) |
| `docker_puertos` | `docker ps` (nombre y puertos) |
| `docker_consumo` | `docker stats --no-stream`, `docker system df` |
| `errores` | `journalctl -p 3 -b -n 60` |
| `kernel` | `journalctl -k -p 4 -b -n 60` |
| `arranques` | `journalctl --list-boots` |
| `hora` | `timedatectl` |
| `sesiones` | `who` |
| `actualizaciones` | `apt list --upgradable` |
| `ia` | `ollama list`, `ollama ps` |

Garantías: solo programas que leen; 15 s máximo por paso; salida recortada a
12 000 caracteres; se tapan patrones de contraseñas, tokens y claves; nada
que muestre argumentos de procesos, variables de entorno ni `docker inspect`.
Queda fuera a propósito lo que necesita root (`smartctl`, `dmidecode`, `dmesg`).
Funciona aunque `CONSOLA_ACTIVA=0` (solo necesita el puente);
`AGENTE_CONSULTAS=0` la apaga. Para añadir una consulta, se edita `CONSULTAS`
y se reinstala el puente.

## El monitor del servidor

Con sesión iniciada, el botón **Monitor** de la cabecera abre un cajón con el
estado del ordenador: CPU total y por núcleo, carga media, temperatura, memoria
y swap, GPU (uso y temperatura), disco y tiempo encendido. Arriba, un semáforo
con el peor indicador; abajo, la gráfica de CPU y memoria de los dos últimos
minutos.

De dónde sale cada cifra:

| Dato | Quién lo mide |
|---|---|
| CPU, memoria, swap, carga, temperaturas, GPU (nombre y °C), uptime | **Glances** (stack `infra/glances`, API v4) |
| % de uso de la GPU | `/sys/class/drm/card0/device/gpu_busy_percent` (en las Radeon integradas Glances no lo da) |
| Disco | `statvfs` del volumen `/app/database`, que es el disco real del servidor |

El navegador **nunca habla con Glances**: pide `/monitor/datos` al portal, que es
quien consulta la API por dentro de la red docker y cachea 2 segundos. Glances no
publica ningún puerto, así que no hay una segunda puerta al servidor.

- **Solo con sesión**: `/monitor/datos` redirige a `/login` sin sesión, y las
  respuestas van con `Cache-Control: no-store`.
- **Solo lectura**: no hay órdenes, ni consola, ni socket de Docker. El monitor
  mira; no toca.
- **Si Glances se cae**, el panel dice «No se pudo hablar con Glances» y el resto
  del portal sigue igual. Los umbrales del semáforo están en `monitor.py`
  (`UMBRALES`).
- La gráfica se alimenta de las muestras de la pestaña abierta (60 × 2,5 s); al
  cerrar el cajón o pasar la pestaña a segundo plano, deja de pedir.

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
