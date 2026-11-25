# Auditoría Técnica, Checklist de Seguridad y Guía Paso a Paso: Réplica de DocEngine a Producción (Rocky Linux)

> **Veredicto Ejecutivo de la Auditoría**
> Hacer una **réplica lógica y controlada** (reconstruyendo entorno virtual y clúster PostgreSQL de forma nativa en el destino) es **100% viable y segura**.
> **NO se debe realizar una copia directa bit-a-bit** (ni `rsync` completo de `/opt/docengine/.venv`, ni copia de `/var/lib/pgsql/16/data`, ni clonación de `.git` o `.env` tal cual están), porque el cambio de **Rocky Linux 8.10 (`glibc 2.28`)** a **Rocky Linux 9/10 (`glibc 2.34+`)** corrompería índices de PostgreSQL, rompería binarios compilados de Python y arrastraría credenciales y configuraciones de desarrollo hacia producción.

---

## 1. Inventario Real del Servidor Origen (Estado Auditado)

| Componente | Estado Actual en Servidor Origen | Observación para Producción |
| :--- | :--- | :--- |
| **Sistema Operativo** | Rocky Linux **8.10** (`x86_64`, `glibc 2.28`) | Destino será Rocky Linux **9.x o 10.x** (cambian repos `crb`/PGDG y `glibc`) |
| **SELinux** | `Enforcing` | Mantener `Enforcing`; requiere reglas explícitas para Nginx y contextos de archivos |
| **Hardware** | 12 vCPUs (Intel i5-11400), **15 GiB RAM**, 7.8 GiB Swap, sin GPU | `uvicorn` solo consume **9.4 GB RSS** en ejecución activa → **mínimo 16 GB RAM** (recomendado **24–32 GB**) |
| **Particionamiento** | `/` = 70 GB (48% usado, contiene `/opt` y `/var`), `/home` = 368 GB | En producción asignar **≥ 100 GB** en la partición que aloje `/opt/docengine/outputs`, `/var/lib/pgsql` y caché ML |
| **Runtime Python** | `Python 3.12.13` + `/opt/docengine/.venv` (**7.0 GB**) | Reconstruir `.venv` en destino con `python3.12` + `pip freeze` exacto + wheel local `pdfextract-1.0.2` |
| **Wheel Privado** | `pdfextract-1.0.2-py3-none-any.whl` (180 KB) | **No existe en PyPI**; imprescindible incluirlo en el paquete de transferencia |
| **Modelos ML en Caché** | `/home/ovis/.cache/huggingface/hub/` (**6.9 GB**): `BAAI/bge-m3` (4.3G), `BAAI/bge-reranker-v2-m3` (2.2G), `docling-models` (342M), `docling-layout-heron` (164M) | **Portables entre versiones de Rocky**; copiarlos a `/var/cache/docengine/huggingface` evita descargas y soporta redes restringidas |
| **Base de Datos** | PostgreSQL **16.14** + `pgvector` **0.8.6** (`docengine`, 86 MB, 14 tablas, 74 pólizas de prueba, 716 jobs, 197 eventos ledger) | Instalar `postgresql16-server` + `pgvector_16` para EL9/EL10; definir si producción parte **limpia** (`001`–`013`) o con migración lógica (`pg_dump`) |
| **Servicio Systemd** | `/etc/systemd/system/docengine.service` corre como usuario `ovis` en `0.0.0.0:8000` | Cambiar a usuario de sistema dedicado `docengine`, enlazar a `127.0.0.1:8000`, poner detrás de Nginx TLS |
| **Servicio Co-ubicado** | `tubroker-chat.service` (`/opt/tubroker-chat`, puerto `8100`, usuario `rolandol`) conectado a la **misma BD `docengine`** | **Definir alcance con negocio/TI**: si ese servicio también migra o es independiente |
| **Zona Horaria** | `America/New_York` (`EST -0500`) con `RTC in local TZ: yes` | Estandarizar en producción (ej. `America/La_Paz` UTC-4 o `UTC`) por consistencia del ledger WORM y dashboard |

---

## 2. Hallazgos Críticos y Trampas Detectadas (Riesgos Reales)

### Hallazgos de Seguridad Bloqueantes (NO copiar tal cual a producción)

1. **Token de GitHub (PAT) en texto plano dentro de `.git/config`**: El remoto `origin` almacena un token personal embebido en la URL. **Acción:** No copiar la carpeta `.git/` al servidor de producción; además, rotar/revocar ese token y reemplazar el remoto por SSH o credenciales seguras.
2. **Seguridad RBAC desactivada en el `.env` actual**: El `.env` actual tiene `DOCENGINE_ENV=development` y omite `DOCENGINE_SECURITY_ENABLED=true` y `DOCENGINE_API_KEYS`. Según [app/api/security.py](../app/api/security.py), cuando ambas están desactivadas **toda petición anónima recibe privilegios `admin`** (incluyendo borrado de pólizas).
3. **PostgreSQL expuesto en `0.0.0.0:5432` con usuario superuser `postgres` y `ssl=off`**: En producción debe escuchar solo en `localhost` (salvo consumidores externos justificados), usar un rol dedicado **sin privilegios de superusuario** (`docengine`) y contraseña robusta (`scram-sha-256`).
4. **Uvicorn expuesto directamente en `0.0.0.0:8000` sin HTTPS**: En producción debe escuchar únicamente en `127.0.0.1:8000` detrás de Nginx con TLS 1.2/1.3.

### Trampas Técnicas Detectadas en el Código y Plantillas de Despliegue

1. **Precedencia silenciosa de `.env.linux` ([app/config/settings.py](../app/config/settings.py))**: En Linux, DocEngine carga automáticamente `.env` y luego `.env.linux`. El archivo `.env.linux` tiene **`DOCENGINE_RERANKER_ENABLED=false`**, `DOCENGINE_OCR_ENGINE=rapidocr` y `DOCENGINE_PIPELINE_IMAGES_SCALE=1.0`. Si se ejecuta cualquier comando CLI o `uvicorn` sin `DOCENGINE_ENV=production` en el entorno del SO, `.env.linux` **sobrescribe `.env`** y apaga el reranker silenciosamente. **Solución:** En producción **NO copiar `.env.linux` ni `.env.windows`**; centralizar el 100% de variables en un único `/opt/docengine/.env` (`chmod 600`).
2. **Incompatibilidad WebUI vs RBAC (`X-API-Key`)**: Al auditar `webui/*.html`, solo [webui/dashboard.html](../webui/dashboard.html) solicita y envía la cabecera `X-API-Key`. Las otras 4 vistas (`index.html`, `chat.html`, `ingesta.html`, `eliminar.html`) **no envían `X-API-Key`**. Si activan `DOCENGINE_SECURITY_ENABLED=true` y usuarios finales acceden a esas pantallas directamente, recibirán `401 Unauthorized` (a menos que Nginx inyecte la API Key tras autenticación corporativa/SSO/VPN, o que producción solo exponga API REST + Dashboard).
3. **Dependencias CDN externas en WebUI**: Las vistas `webui/*.html` cargan Google Fonts, FontAwesome (`cdnjs.cloudflare.com`), `marked.js` y `Chart.js` (`cdn.jsdelivr.net`). Si el navegador del cliente corporativo no tiene salida a internet, los gráficos e íconos no cargarán.
4. **Errores en la plantilla [deploy/docengine.service](../deploy/docengine.service) para Rocky Linux**:
   - Declara `After=postgresql.service` y `Wants=postgresql.service`, pero en Rocky Linux con repositorio PGDG el servicio se llama **`postgresql-16.service`**.
   - Activa `ProtectHome=true` y `ProtectSystem=strict` **sin declarar `HF_HOME`** ni añadir la ruta de caché a `ReadWritePaths=`. Si se usa tal cual, DocEngine falla al intentar leer/escribir modelos HuggingFace en `/home/docengine/.cache`.
   - Omite `Environment="TORCHDYNAMO_DISABLE=1"` (sí presente en el servicio activo actual y necesario para estabilidad de PyTorch en CPU).
   - Usa `StandardOutput=append:/var/log/docengine/docengine.log`: si el directorio `/var/log/docengine` no se crea previamente con dueño `docengine:docengine`, systemd falla al arrancar.
   - [config.yaml](../config.yaml) tiene `save_log_file: true`: con `ProtectSystem=strict`, el directorio `/opt/docengine` queda en solo lectura; verificar que `pdfextract` no intente escribir logs en el directorio raíz de trabajo (o cambiar `save_log_file: false` en producción).
5. **Script [scripts/init_db.py](../scripts/init_db.py) ejecuta TODOS los `*.sql` incluyendo `014` y `015`**: Los scripts `014` y `015` son saneamientos históricos del entorno de pruebas. Para una BD limpia en producción se deben ejecutar **únicamente del `001` al `013`**. Además, `001_add_rag_tables.sql` ejecuta `CREATE EXTENSION IF NOT EXISTS vector;`, lo cual exige superusuario PostgreSQL antes de ceder permisos al rol de aplicación `docengine`.
6. **Cambios sin commitear en Git**: `Dockerfile` tiene modificaciones locales (`pdfextract-1.0.0` → `1.0.2`) y `docs/GUIA_DESPLIEGUE_PRODUCCION_TI.md` está sin trackear. Congelar un commit/tag antes de replicar.
7. **Consumo real de RAM y tuning de PostgreSQL**: `uvicorn` activo en este servidor ocupa **9.4 GB RAM**. Además, PostgreSQL opera con valores por defecto mínimos (`shared_buffers=128MB`, `work_mem=4MB`, `maintenance_work_mem=64MB`), subóptimos para índices HNSW de `pgvector`.

---

## 3. Qué Copiar vs. Qué Reconstruir vs. Qué Excluir

| Elemento | Acción | Motivo Técnico |
| :--- | :--- | :--- |
| `app/`, `skills/`, `webui/`, `scripts/` (`001`–`013`), `deploy/`, `main.py`, `config.yaml`, `requirements.txt`, `pyproject.toml`, `.agents/` | **COPIAR** | Código fuente y reglas de extracción por aseguradora (respetando inmutabilidad) |
| `pdfextract-1.0.2-py3-none-any.whl` | **COPIAR** | Dependencia privada local; no está en PyPI |
| `requirements-lock.txt` (generado con `pip freeze` desde el origen) | **GENERAR Y COPIAR** | Congela versiones exactas validadas (`docling==2.151.1`, `torch==2.13.0`, etc.) evitando regresiones por `>=` |
| `/home/ovis/.cache/huggingface/hub/` (6.9 GB) | **COPIAR** a `/var/cache/docengine/huggingface/hub/` | Pesos ML independientes de versión de SO; ahorra descarga de ~7 GB y permite arranque offline |
| `/opt/docengine/.venv` (7.0 GB) | **NO COPIAR — RECONSTRUIR** | Enlaces simbólicos y librerías nativas `.so` atadas a `glibc 2.28` / Python de Rocky 8.10 |
| `/var/lib/pgsql/16/data` | **NO COPIAR — RECONSTRUIR** | Cambio de `glibc` (EL8 → EL9/10) altera colaciones `en_US.UTF-8` y corrompe índices B-tree |
| `.git/`, `.env`, `.env.linux`, `.env.windows` | **NO COPIAR** | `.git` contiene PAT en texto plano; `.env` tiene configuración dev; `.env.linux` desactiva el reranker |
| `outputs/` (3.5G), `dist/` (7.3G), `carga_inicial/`, `empresas/`, `samples/`, `*.log`, `skills.zip`, `.pytest_cache/` | **NO COPIAR** | Datos y residuos de pruebas/staging (salvo decisión explícita de migrar las 74 pólizas actuales) |

---

## 4. Checklist 100% Seguro de Réplica a Producción

### Fase A — Decisiones Previas y Congelamiento (Antes de tocar Producción)
- [ ] **Definir estrategia de datos inicial**: ¿Producción arranca con **0 pólizas** (solo esquemas y catálogos `001`–`013`) o requiere migrar las 74 pólizas actuales (vía `pg_dump -Fc` + `outputs/`)?
- [ ] **Definir alcance de `tubroker-chat` (puerto 8100)**: Confirmar si se replica aparte o no aplica en producción.
- [ ] **Definir modelo de acceso WebUI + RBAC**: Confirmar si los usuarios usarán solo API REST + `/dashboard` (soporta `X-API-Key`), o si usarán `/chat`, `/ingesta`, `/eliminar` (requiere inyección de cabecera en Nginx tras auth corporativa o red interna aislada).
- [ ] **Congelar versión en Git**: Commitear cambios pendientes, etiquetar release (ej. `v1.0.2-prod`) y **rotar/revocar el GitHub PAT** expuesto en `.git/config`.
- [ ] **Generar llave OpenAI exclusiva de producción**: Separada del entorno dev/pruebas, verificando límites TPM/RPM (recomendado Tier ≥ 2 si procesan pólizas muy extensas).
- [ ] **Preparar certificados TLS y DNS**: Dominio corporativo (ej. `docengine.empresa.com`), certificado válido `.crt`/`.key` y política de firewall.

### Fase B — Infraestructura y Requisitos del Servidor Destino (Rocky Linux 9/10)
- [ ] **Hardware validado**: ≥ 8 vCPUs `x86_64`, **≥ 16 GB RAM** (recomendado **24–32 GB**) + **8 GB Swap**, **≥ 100 GB libres** en la partición de datos (`/opt`, `/var`).
- [ ] **SO actualizado y reloj sincronizado**: `chronyd` activo, zona horaria corporativa definida (`America/La_Paz` o `UTC`), `RTC in local TZ: no`.
- [ ] **SELinux en modo `Enforcing`** confirmado y herramientas `policycoreutils-python-utils` instaladas.
- [ ] **Conectividad saliente verificada**: TCP `443` hacia `api.openai.com` (obligatorio). Hacia `huggingface.co` solo si no se copian los modelos pre-descargados.
- [ ] **Firewall (`firewalld`) endurecido**: Solo `443/tcp` (y `80/tcp` para redirect a HTTPS) y `22/tcp` (administración restringida). Puertos **`8000` y `5432` cerrados al exterior**.
- [ ] **Python 3.12 instalado**: Verificar `python3.12 --version` (evitar Python 3.13+ que puede romper wheels de PyTorch/Docling).
- [ ] **Librerías de sistema para Docling/OpenCV instaladas**: `gcc`, `gcc-c++`, `python3.12-devel`, `mesa-libGL`, `libglvnd-glx`, `glib2`, `libgomp`, `nginx`.
- [ ] **PostgreSQL 16 + `pgvector_16` instalados** desde repositorio PGDG oficial correspondiente a la versión exacta de Rocky (EL9 o EL10).

### Fase C — Base de Datos, Aplicación y Hardening
- [ ] **Usuario de sistema dedicado `docengine`** creado sin shell interactivo (`--system --shell /sbin/nologin`).
- [ ] **Rol PostgreSQL `docengine` (NO superusuario)** creado con contraseña robusta (`scram-sha-256`) y `listen_addresses = 'localhost'`.
- [ ] **Extensión `vector` habilitada** (como superusuario `postgres`) y scripts **`001` a `013`** ejecutados sin errores (sin `014`/`015` en BD nueva), con permisos `GRANT` otorgados al rol `docengine`.
- [ ] **Tuning básico de PostgreSQL aplicado** (`shared_buffers`, `work_mem`, `maintenance_work_mem`, `effective_cache_size`).
- [ ] **Entorno virtual `.venv` recreado nativamente** con versiones congeladas (`requirements-lock.txt`) + `pdfextract-1.0.2-py3-none-any.whl`.
- [ ] **Caché de modelos ML copiado** en `/var/cache/docengine/huggingface` (dueño `docengine:docengine`) y modelos RapidOCR inicializados.
- [ ] **Archivo `/opt/docengine/.env` de producción creado** (`chmod 600`, dueño `docengine:docengine`) y **ausencia confirmada de `.env.linux` y `.env.windows`**.
- [ ] **Parámetros críticos de seguridad verificados en `.env`**:
  - `DOCENGINE_ENV=production`
  - `DOCENGINE_SECURITY_ENABLED=true`
  - `DOCENGINE_API_KEYS={...}` (claves generadas con `openssl rand -hex 32` para roles `readonly`, `writer`, `admin`)
  - `DOCENGINE_CORS_ORIGINS=https://docengine.tu-empresa.com`
  - `DOCENGINE_ENABLE_DOCS=false`
  - `DOCENGINE_ALLOWED_FOLDER_BASE=/opt/docengine/inputs` (restringe `POST /api/v1/extract/folder`)
  - `DOCENGINE_RERANKER_ENABLED=true` (o valor explícito acordado)
  - `DOCENGINE_LOG_FORMAT=json`
- [ ] **Unit systemd corregido** en `/etc/systemd/system/docengine.service` (`After=postgresql-16.service`, `HF_HOME=/var/cache/docengine/huggingface`, `TORCHDYNAMO_DISABLE=1`, `TORCH_COMPILE_DISABLE=1`, `--host 127.0.0.1`, `ReadWritePaths` completo).
- [ ] **SELinux habilitado para Nginx**: `setsebool -P httpd_can_network_connect 1` y `restorecon -Rv` en `/opt/docengine`, `/var/log/docengine`, `/var/cache/docengine`.
- [ ] **Nginx TLS configurado** (`client_max_body_size 500M`, `proxy_read_timeout 600s`, `proxy_send_timeout 600s`).
- [ ] **Mantenimiento programado**: `logrotate` en `/etc/logrotate.d/docengine`, cron de limpieza `cleanup-uploads.sh`, y respaldo automático diario de PostgreSQL (`pg_dump -Fc`) + `outputs/`.

### Fase D — Validación de Aceptación (Smoke & Security Tests)
- [ ] `systemctl status postgresql-16 docengine nginx` → los 3 en estado `active (running)` y `enabled`.
- [ ] **Prueba de reinicio del servidor** (`reboot`) → PostgreSQL 16 levanta primero, luego DocEngine, luego Nginx sin intervención manual.
- [ ] `GET /api/v1/health` (vía HTTPS) → `200 OK` con `"environment": "production"`.
- [ ] `GET /docs` y `GET /openapi.json` → `404 Not Found`.
- [ ] `GET /api/v1/metrics` sin `X-API-Key` → `401 Unauthorized`.
- [ ] `GET /api/v1/metrics` con clave `readonly` → `200 OK`.
- [ ] `POST /api/v1/extract` con clave `readonly` → `403 Forbidden`.
- [ ] **Prueba E2E completa**: ingesta de 1 PDF real con clave `writer` → archivos creados en `/opt/docengine/outputs/` + chunks en `policy_chunks` → consulta RAG exitosa (`POST /api/v1/query` con OpenAI + reranker) → limpieza con clave `admin` (`DELETE /api/v1/policies/<id>`).
- [ ] **Prueba de escaneo de puertos externos**: confirmar desde otro equipo que `8000` y `5432` NO responden.

---

## 5. Guía Paso a Paso para la Réplica Segura (Rocky 8.10 → Rocky 9/10)

### Paso 1 — En el Servidor Origen (Rocky 8.10): Congelar Dependencias y Empaquetar Artefactos Limpios

Ejecutar en el servidor actual para generar un paquete **100% limpio** (sin `.venv`, sin `.git`, sin `.env`, sin `outputs/` ni residuos de prueba):

```bash
cd /opt/docengine

# 1. Congelar versiones exactas de Python actualmente validadas en este servidor
#    (excluyendo pdfextract porque se instala desde el .whl local)
/opt/docengine/.venv/bin/pip freeze | grep -v '^pdfextract==' > /tmp/requirements-lock.txt

# 2. Empaquetar SOLO los archivos necesarios de la aplicación
tar --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.env' \
    --exclude='.env.linux' \
    --exclude='.env.windows' \
    --exclude='outputs' \
    --exclude='dist' \
    --exclude='carga_inicial' \
    --exclude='empresas' \
    --exclude='samples' \
    --exclude='skills.zip' \
    --exclude='*.log' \
    -czf /tmp/docengine-app-replica.tar.gz -C /opt docengine

# 3. Empaquetar caché de modelos HuggingFace/Docling (6.9 GB — portable entre Rocky 8/9/10)
tar -czf /tmp/docengine-hf-cache.tar.gz -C /home/ovis/.cache huggingface

# 4. (SOLO SI EL NEGOCIO DECIDE MIGRAR LAS 74 PÓLIZAS ACTUALES)
# pg_dump -h localhost -U postgres -Fc docengine > /tmp/docengine_db_backup.dump
# tar -czf /tmp/docengine-outputs.tar.gz -C /opt/docengine outputs

# 5. Generar checksums de integridad
sha256sum /tmp/docengine-app-replica.tar.gz /tmp/docengine-hf-cache.tar.gz /tmp/requirements-lock.txt > /tmp/replica.sha256
```

Transferir `/tmp/docengine-app-replica.tar.gz`, `/tmp/docengine-hf-cache.tar.gz`, `/tmp/requirements-lock.txt` y `/tmp/replica.sha256` al servidor de producción por `scp`/`sftp`, y verificar integridad en el destino:
```bash
sha256sum -c /tmp/replica.sha256
```

---

### Paso 2 — En el Servidor Destino (Rocky Linux 9/10): Preparación del SO y Paquetes Base

```bash
# 1. Verificar versión exacta de Rocky, CPU, RAM y discos
cat /etc/os-release
lscpu | grep -E 'Model name|CPU\(s\)|Architecture'
free -h && df -h

# 2. Configurar zona horaria corporativa y NTP (ajustar si usan UTC)
sudo timedatectl set-timezone America/La_Paz
sudo timedatectl set-local-rtc 0
sudo systemctl enable --now chronyd

# 3. Habilitar EPEL y CRB (en Rocky 9/10 reemplaza a PowerTools de Rocky 8)
sudo dnf install -y dnf-plugins-core epel-release
sudo dnf config-manager --set-enabled crb

# 4. Instalar Python 3.12, compiladores, librerías gráficas (OpenCV/Docling), Nginx y utilidades SELinux
#    (En Rocky 10 python3 ya es 3.12; en Rocky 9 instalar python3.12 explícitamente)
sudo dnf install -y \
    python3.12 python3.12-devel python3.12-pip \
    gcc gcc-c++ make \
    mesa-libGL libglvnd-glx glib2 libgomp \
    nginx jq policycoreutils-python-utils

python3.12 --version   # Confirmar 3.12.x
```

---

### Paso 3 — En el Servidor Destino: Instalar y Configurar PostgreSQL 16 + `pgvector`

```bash
# 1. Instalar repositorio oficial PGDG según versión de Rocky Linux:
#    Para Rocky Linux 9:
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf -qy module disable postgresql

#    (Si el destino es Rocky Linux 10, usar EL-10-x86_64 en lugar de EL-9-x86_64)

# 2. Instalar PostgreSQL 16 y extensión pgvector_16
sudo dnf install -y postgresql16-server postgresql16-contrib pgvector_16

# 3. Inicializar clúster con UTF-8 y habilitar servicio
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16
```

Configurar seguridad y tuning básico en `/var/lib/pgsql/16/data/postgresql.conf` (ajustar según RAM total; ejemplo para servidor de 16–24 GB RAM):
```ini
listen_addresses = 'localhost'
max_connections = 100
shared_buffers = 2GB
effective_cache_size = 6GB
work_mem = 16MB
maintenance_work_mem = 512MB
password_encryption = scram-sha-256
```

Verificar en `/var/lib/pgsql/16/data/pg_hba.conf` que las conexiones locales `127.0.0.1/32` y `::1/128` usen `scram-sha-256` (no `trust`), y reiniciar PostgreSQL:
```bash
sudo systemctl restart postgresql-16
```

Crear rol dedicado **no-superuser**, base de datos y extensión `vector`:
```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE docengine WITH LOGIN PASSWORD '<CONTRASEÑA_FUERTE_PRODUCCION>';
CREATE DATABASE docengine OWNER docengine ENCODING 'UTF8';
\c docengine
CREATE EXTENSION IF NOT EXISTS vector;
SQL
```

---

### Paso 4 — Desplegar Código, Modelos ML y Recrear `.venv` Nativamente

```bash
# 1. Crear usuario de sistema dedicado sin login interactivo
sudo useradd --system --home-dir /opt/docengine --shell /sbin/nologin docengine

# 2. Extraer código limpio y crear directorios operativos
sudo tar -xzf /tmp/docengine-app-replica.tar.gz -C /opt
sudo mkdir -p /opt/docengine/outputs /opt/docengine/inputs /var/log/docengine /var/cache/docengine

# 3. Extraer caché de modelos ML (6.9 GB)
sudo tar -xzf /tmp/docengine-hf-cache.tar.gz -C /var/cache/docengine

# 4. Asignar propiedad al usuario docengine
sudo chown -R docengine:docengine /opt/docengine /var/log/docengine /var/cache/docengine

# 5. Recrear entorno virtual nativo con Python 3.12 e instalar versiones exactas
sudo -u docengine python3.12 -m venv /opt/docengine/.venv
sudo -u docengine /opt/docengine/.venv/bin/pip install --upgrade pip wheel
sudo -u docengine /opt/docengine/.venv/bin/pip install --no-cache-dir -r /tmp/requirements-lock.txt
sudo -u docengine /opt/docengine/.venv/bin/pip install --no-cache-dir --no-deps /opt/docengine/pdfextract-1.0.2-py3-none-any.whl

# 6. Verificar carga de paquetes críticos y modelos RapidOCR
sudo -u docengine /opt/docengine/.venv/bin/python -c "
import docling, pdfextract, torch, pgvector, psycopg2, sentence_transformers
from rapidocr_onnxruntime import RapidOCR
RapidOCR()
print('OK:', docling.__version__, pdfextract.__version__, torch.__version__)
"
```

---

### Paso 5 — Inicializar Esquema de Base de Datos (Scripts `001` a `013`)

**Opción A — Inicio Limpio (Recomendado para Producción Nueva):**
Ejecutar **solo del `001` al `013`** (excluyendo `014` y `015`) como dueño `docengine`:
```bash
for f in /opt/docengine/scripts/00[1-9]_*.sql /opt/docengine/scripts/01[0-3]_*.sql; do
  echo ">>> Aplicando $(basename "$f")..."
  PGPASSWORD='<CONTRASEÑA_FUERTE_PRODUCCION>' psql -h localhost -U docengine -d docengine -v ON_ERROR_STOP=1 -f "$f"
done

# Verificar tablas y catálogos cargados
PGPASSWORD='<CONTRASEÑA_FUERTE_PRODUCCION>' psql -h localhost -U docengine -d docengine -c "\dt" -c "SELECT count(*) AS aseguradoras FROM cat_aseguradoras;"
```

*(Opción B — Solo si el negocio solicita migrar las 74 pólizas actuales: restaurar con `pg_restore --no-owner --role=docengine -h localhost -U postgres -d docengine /tmp/docengine_db_backup.dump`, reasignar ownership de tablas/secuencias a `docengine`, y extraer `docengine-outputs.tar.gz` en `/opt/docengine/`).*

---

### Paso 6 — Configurar `/opt/docengine/.env` Único de Producción

Confirmar que **NO existan** `.env.linux` ni `.env.windows` en `/opt/docengine/`, generar API Keys con `openssl rand -hex 32` y crear `/opt/docengine/.env`:

```bash
sudo rm -f /opt/docengine/.env.linux /opt/docengine/.env.windows
```

Contenido base recomendado de `/opt/docengine/.env` (ajustar valores entre `<...>`):

```ini
# --- Aplicación ---
DOCENGINE_ENV=production
DOCENGINE_APP_NAME=DocEngine
DOCENGINE_APP_VERSION=1.0.2
DOCENGINE_EXTRACTOR_ENGINE=pdfextract
DOCENGINE_SKIP_SKILLS=true

# --- Seguridad, RBAC y Hardening (OBLIGATORIO) ---
DOCENGINE_SECURITY_ENABLED=true
DOCENGINE_API_KEYS={"<KEY_READONLY>":"readonly","<KEY_WRITER>":"writer","<KEY_ADMIN>":"admin"}
DOCENGINE_CORS_ORIGINS=https://docengine.tu-empresa.com
DOCENGINE_ENABLE_DOCS=false
DOCENGINE_ALLOWED_FOLDER_BASE=/opt/docengine/inputs

# --- Extracción y Pipeline ---
DOCENGINE_EXTRACTION_DO_OCR=false
DOCENGINE_EXTRACTION_AUTO_DETECT_PDF_TYPE=true
DOCENGINE_EXTRACTION_TABLE_MODE=ACCURATE
DOCENGINE_EXTRACTION_DO_TABLE_STRUCTURE=true
DOCENGINE_EXTRACTION_DO_CELL_MATCHING=true
DOCENGINE_EXTRACTION_GENERATE_PICTURE_IMAGES=false
DOCENGINE_EXTRACTION_FIX_SPACED_TEXT=true
DOCENGINE_EXTRACTION_SPACED_TEXT_MIN_RATIO=0.4
DOCENGINE_EXTRACTION_SPLIT_MERGED_TABLES=true
DOCENGINE_PIPELINE_NUM_THREADS=8
DOCENGINE_PIPELINE_ACCELERATOR_DEVICE=cpu
DOCENGINE_PIPELINE_PDF_BACKEND=docling_parse_v2
DOCENGINE_PIPELINE_IMAGES_SCALE=2.0
DOCENGINE_OCR_ENGINE=rapidocr
DOCENGINE_OCR_LANGUAGES=["es","en"]
DOCENGINE_OCR_FORCE_FULL_PAGE_OCR=false
TORCHDYNAMO_DISABLE=1
TORCH_COMPILE_DISABLE=1
OMP_NUM_THREADS=6
MKL_NUM_THREADS=6

# --- Almacenamiento, Modelos y Logs ---
DOCENGINE_OUTPUT_OUTPUT_DIR=/opt/docengine/outputs
DOCENGINE_LOG_LEVEL=INFO
DOCENGINE_LOG_FORMAT=json
DOCENGINE_LOG_LOG_FILE=/var/log/docengine/docengine.log
HF_HOME=/var/cache/docengine/huggingface
SENTENCE_TRANSFORMERS_HOME=/var/cache/docengine/huggingface
TORCH_HOME=/var/cache/docengine/torch

# --- Rendimiento ---
DOCENGINE_PERF_BATCH_SIZE=4
DOCENGINE_PERF_MAX_UPLOAD_SIZE_MB=500
DOCENGINE_PERF_REQUEST_TIMEOUT_SECONDS=600
DOCENGINE_PERF_MEMORY_WARNING_THRESHOLD_MB=8192

# --- Base de Datos (PostgreSQL 16 local) ---
DOCENGINE_DB_HOST=localhost
DOCENGINE_DB_PORT=5432
DOCENGINE_DB_NAME=docengine
DOCENGINE_DB_USER=docengine
DOCENGINE_DB_PASSWORD=<CONTRASEÑA_FUERTE_PRODUCCION>
DOCENGINE_DB_POOL_MIN=2
DOCENGINE_DB_POOL_MAX=10

# --- Embeddings, Reranker y OpenAI ---
DOCENGINE_EMBED_MODEL_NAME=BAAI/bge-m3
DOCENGINE_EMBED_BATCH_SIZE=8
DOCENGINE_EMBED_NUM_THREADS=6
DOCENGINE_EMBED_DEVICE=cpu
DOCENGINE_EMBED_CHUNK_SIZE_CHARS=2500
DOCENGINE_EMBED_CHUNK_OVERLAP_CHARS=200
DOCENGINE_RERANKER_ENABLED=true
DOCENGINE_RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-m3
DOCENGINE_RERANKER_TOP_N=8
DOCENGINE_RERANKER_DEVICE=cpu
OPENAI_API_KEY=<TU_OPENAI_API_KEY_PRODUCCION>
DOCENGINE_RAG_TOP_K=20
DOCENGINE_RAG_SIMILARITY_THRESHOLD=0.20
DOCENGINE_RAG_LLM_MODEL=gpt-4.1-mini
DOCENGINE_RAG_MAX_TOKENS=16384
DOCENGINE_RAG_TEMPERATURE=0.0
```

Proteger permisos del `.env`:
```bash
sudo chown docengine:docengine /opt/docengine/.env
sudo chmod 600 /opt/docengine/.env
```

---

### Paso 7 — Configurar Systemd (Corregido para Rocky Linux), SELinux, Nginx y Firewall

Crear `/etc/systemd/system/docengine.service` (versión corregida de la plantilla original para Rocky Linux con PostgreSQL 16 y `HF_HOME` compatible con `ProtectHome=true`):

```ini
[Unit]
Description=DocEngine — Motor de Extracción Documental y Pipeline RAG
After=network.target postgresql-16.service
Requires=postgresql-16.service

[Service]
Type=simple
User=docengine
Group=docengine
WorkingDirectory=/opt/docengine
EnvironmentFile=/opt/docengine/.env
Environment="DOCENGINE_ENV=production"
Environment="DOCENGINE_LOG_FORMAT=json"
Environment="TORCHDYNAMO_DISABLE=1"
Environment="TORCH_COMPILE_DISABLE=1"
Environment="HF_HOME=/var/cache/docengine/huggingface"
Environment="SENTENCE_TRANSFORMERS_HOME=/var/cache/docengine/huggingface"
Environment="TORCH_HOME=/var/cache/docengine/torch"

ExecStart=/opt/docengine/.venv/bin/uvicorn main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --timeout-keep-alive 60 \
    --log-level info

Restart=always
RestartSec=5
TimeoutStartSec=180
TimeoutStopSec=30

# --- Límites de Recursos ---
MemoryMax=12G
LimitNOFILE=65536

# --- Hardening Systemd ---
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/docengine/outputs /var/log/docengine /var/cache/docengine /tmp

StandardOutput=append:/var/log/docengine/docengine.log
StandardError=append:/var/log/docengine/docengine-error.log

[Install]
WantedBy=multi-user.target
```

*(Nota: Si `pdfextract` intenta escribir un archivo de log local en `/opt/docengine` debido a `logging.save_log_file: true` en [config.yaml](../config.yaml), cambiar `save_log_file: false` en el `config.yaml` de producción para no romper `ProtectSystem=strict`.)*

Restaurar contextos SELinux, levantar DocEngine, configurar Nginx TLS y Firewall:
```bash
# 1. Contextos SELinux + habilitar conexión de Nginx hacia 127.0.0.1:8000
sudo restorecon -Rv /opt/docengine /var/log/docengine /var/cache/docengine
sudo setsebool -P httpd_can_network_connect 1

# 2. Habilitar e iniciar DocEngine
sudo systemctl daemon-reload
sudo systemctl enable --now docengine
sudo journalctl -u docengine -f   # Esperar "Uvicorn running on http://127.0.0.1:8000"

# 3. Configurar Nginx Reverse Proxy TLS (editar server_name y rutas de certificados)
sudo cp /opt/docengine/deploy/nginx.conf /etc/nginx/conf.d/docengine.conf
sudo vi /etc/nginx/conf.d/docengine.conf
sudo nginx -t && sudo systemctl enable --now nginx

# 4. Endurecer firewalld (solo HTTP/HTTPS y SSH)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --remove-port=8000/tcp 2>/dev/null || true
sudo firewall-cmd --permanent --remove-port=5432/tcp 2>/dev/null || true
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

---

### Paso 8 — Mantenimiento Programado (Logrotate, Limpieza y Backups)

```bash
# 1. Rotación de logs
sudo cp /opt/docengine/deploy/logrotate-docengine /etc/logrotate.d/docengine
sudo logrotate -d /etc/logrotate.d/docengine

# 2. Cron de limpieza de cargas temporales (>24h) y backup diario de PostgreSQL
sudo chmod +x /opt/docengine/deploy/cleanup-uploads.sh
sudo mkdir -p /var/backups/docengine && sudo chmod 700 /var/backups/docengine

# Agregar en /etc/cron.d/docengine:
sudo tee /etc/cron.d/docengine >/dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
# Limpieza diaria de archivos temporales huérfanos (03:00)
0 3 * * * docengine /opt/docengine/deploy/cleanup-uploads.sh
# Respaldo diario de PostgreSQL 16 (02:00) con retención de 14 días
0 2 * * * postgres pg_dump -Fc docengine > /var/backups/docengine/docengine_$(date +\%F).dump && find /var/backups/docengine -name "*.dump" -mtime +14 -delete
CRON
```

---

### Paso 9 — Batería de Pruebas de Aceptación (Verificación Post-Réplica)

```bash
# 1. Salud del servicio y entorno production
curl -s -f https://docengine.tu-empresa.com/api/v1/health | jq .

# 2. Verificar que Swagger/OpenAPI estén bloqueados (debe devolver 404)
curl -s -o /dev/null -w "%{http_code}\n" https://docengine.tu-empresa.com/docs

# 3. Verificar RBAC: sin API Key -> 401 | readonly -> 200 | readonly en POST -> 403
curl -s -o /dev/null -w "%{http_code}\n" https://docengine.tu-empresa.com/api/v1/metrics
curl -s -f -H "X-API-Key: <KEY_READONLY>" https://docengine.tu-empresa.com/api/v1/catalogs/companies | jq 'length'
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "X-API-Key: <KEY_READONLY>" https://docengine.tu-empresa.com/api/v1/extract

# 4. Prueba E2E de extracción + RAG + OpenAI + limpieza (usar PDF de prueba)
curl -s -f -X POST "https://docengine.tu-empresa.com/api/v1/extract" \
  -H "X-API-Key: <KEY_WRITER>" \
  -F "file=@/ruta/poliza_prueba.pdf" \
  -F "id_cliente=00000001-TEST" \
  -F "nombre_cliente=PRUEBA PRODUCCION" \
  -F "company_sigla=CRI" | jq '{status, document_id, rag_report}'

curl -s -f -X POST "https://docengine.tu-empresa.com/api/v1/query" \
  -H "X-API-Key: <KEY_READONLY>" \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Cuál es la vigencia o cobertura principal?", "filters": {"id_cliente": "00000001-TEST"}}' | jq '{answer, sources_count: (.sources | length)}'

# Eliminar registro sintético de prueba con rol ADMIN
curl -s -f -X DELETE "https://docengine.tu-empresa.com/api/v1/policies/<POLICY_ID>" \
  -H "X-API-Key: <KEY_ADMIN>" | jq .
```

---

## 6. Nota Comparativa: Réplica Nativa vs. Contenedor (Ya Disponible en el Proyecto)

El proyecto ya cuenta con una alternativa empaquetada en [GUIA_DESPLIEGUE_PRODUCCION_TI.md](./GUIA_DESPLIEGUE_PRODUCCION_TI.md) (`docengine-1.0.2.tar.gz` + `docker-compose.prod.yml`):

| Criterio | Réplica Nativa en Rocky 9/10 (Esta Guía) | Despliegue con Contenedor (`docengine-1.0.2.tar.gz`) |
| :--- | :--- | :--- |
| **Aislamiento frente a versión de Rocky Linux** | Requiere recrear `.venv`, instalar libs EL9/10 y configurar PGDG 16 | **Total**: Python 3.12, librerías y `pgvector/pgvector:pg16` aislados del SO host |
| **Operación estándar para equipos Linux/DBA tradicionales** | **Familiar**: `systemd`, `postgresql-16`, `pg_dump`, `nginx` nativos | Requiere operación con Docker/Podman Compose y manejo de volúmenes |
| **Actualización de `skills/`** | Edición/copia directa en `/opt/docengine/skills/` | Volumen montado `:ro` (`./skills:/app/skills:ro`), igual de rápido |
| **Riesgo de regresión por cambio de SO** | Bajo **si y solo si** se usa `requirements-lock.txt` y reconstrucción limpia | Mínimo (imagen inmutable ya probada) |
