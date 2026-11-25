# Guía de Implementación y Despliegue en Producción — DocEngine (Contenedor Docker / Podman)

**Versión de Imagen:** `docengine:1.0.2`  
**Archivo de Imagen:** `docengine-1.0.2.tar.gz`  
**Dirigido a:** Equipo de TI / Infraestructura y Sistemas  

---

## 1. Resumen de Arquitectura en Producción

DocEngine opera en producción bajo una arquitectura de dos contenedores principales orquestados con Docker Compose (o Podman Compose), protegidos detrás de un proxy inverso Nginx con TLS:

1. **`docengine_api` (`docengine:1.0.2`)**: Motor de extracción documental (Docling + pdfextract + OCR) y servicio API REST / WebUI en Python 3.12 + FastAPI + Uvicorn (puerto interno `8000`, enlazado únicamente a `127.0.0.1:8000`).
2. **`docengine_postgres` (`pgvector/pgvector:pg16`)**: Base de datos PostgreSQL 16 con extensión vectorial `pgvector`, encargada de almacenar pólizas, fragmentos RAG, catálogos maestros, estadísticas y bitácora de auditoría inmutable (WORM).
3. **Proxy Inverso (Nginx en el host)**: Terminación TLS/SSL (HTTPS 443), cabeceras de seguridad y límites de carga (`500M`) y timeout (`600s`) alineados con el procesamiento de pólizas extensas.

---

## 2. Requisitos Previos del Servidor de Producción

### 2.1 Hardware Mínimo Recomendado
* **CPU:** 4 a 8 vCPUs (arquitectura `x86_64` / `amd64`).
* **RAM:** Mínimo **12 GB** asignados al contenedor `docengine` (reserva recomendada de `4 GB`, límite `12 GB` configurado en `docker-compose.prod.yml`) + **2-4 GB** para PostgreSQL y Sistema Operativo (**16 GB RAM total recomendado**).
* **Disco:** Mínimo **50 GB libres** (la imagen descomprimida ocupa ~16.9 GB; adicionalmente se requieren ~5-8 GB para caché de modelos HuggingFace/Docling y espacio para `outputs/` y base de datos).

### 2.2 Software Base en el Servidor
* Linux (Rocky Linux 8/9, RHEL 8/9 o Ubuntu 22.04/24.04 LTS).
* **Docker Engine** ($\ge$ 24.x) con **Docker Compose v2** (`docker compose`), *o* **Podman** ($\ge$ 4.9) con `podman-compose`.
* **Nginx** (para publicación HTTPS externa).

### 2.3 Conectividad / Red Saliente Requerida
* **Hacia `api.openai.com` (TCP 443):** Obligatorio para consultas RAG y extracción estructurada con LLM.
* **Hacia `huggingface.co` y `cdn-lfs.huggingface.co` (TCP 443):** Requerido en el **primer arranque** para descargar los modelos de embeddings (`BAAI/bge-m3`), reranker (`BAAI/bge-reranker-v2-m3`) y modelos de layout/tablas de Docling al volumen persistente `hf_cache`. *(Si el servidor es 100% air-gapped sin salida a internet, ver sección 6.4 para pre-poblar el caché).*

---

## 3. Estructura de Archivos Requerida en Producción

El equipo de TI debe crear el directorio raíz de la aplicación (ejemplo: `/opt/docengine`) y desplegar exactamente la siguiente estructura de archivos (el código fuente de la aplicación ya viaja empaquetado dentro de `docengine-1.0.2.tar.gz`, por lo que **NO** es necesario copiar carpetas de código ni `.venv`):

```text
/opt/docengine/
├── docengine-1.0.2.tar.gz           # Imagen Docker exportada (entregable principal)
├── docengine-1.0.2.tar.gz.sha256    # Suma de verificación SHA-256
├── docker-compose.yml               # Definición base de servicios y red
├── docker-compose.prod.yml          # Override de endurecimiento y configuración de producción
├── docker-compose.offline.yml       # Override sugerido para usar la imagen cargada sin reconstruir (ver Paso 4.2)
├── .env                             # Variables de entorno y secretos de producción (NO versionar, permisos 600)
├── config.yaml                      # Configuración del motor pdfextract (montado :ro)
├── outputs/                         # Directorio persistente de documentos procesados (lectura/escritura)
├── skills/                          # Reglas de extracción por aseguradora (montado :ro)
│   ├── skill-general.md
│   └── skill-*.md
├── scripts/                         # Scripts SQL de inicialización de BD (001 al 013)
│   ├── 001_add_rag_tables.sql
│   ├── ...
│   └── 013_immutable_audit_and_stats.sql
└── deploy/                          # Plantillas de soporte de sistema operativo
    ├── nginx.conf                   # Configuración de Reverse Proxy Nginx + TLS
    ├── logrotate-docengine          # Rotación de logs
    └── cleanup-uploads.sh           # Limpieza periódica de archivos temporales (>24h)
```

> **Nota sobre scripts SQL (`014` y `015`):** En el repositorio existen `014_cleanup_orphan_jobs_and_reconcile.sql` y `015_cleanup_synthetic_test_metrics.sql`. Estos son scripts de saneamiento histórico para entornos previos con datos de prueba; **en una base de datos nueva de producción** solo se montan del `001` al `013` (ya configurados en `docker-compose.prod.yml`).

---

## 4. Procedimiento de Despliegue Paso a Paso

### Paso 1: Transferencia y Verificación de Integridad
Copiar los archivos entregados al directorio `/opt/docengine` del servidor de producción y verificar el checksum de la imagen:

```bash
cd /opt/docengine
sha256sum -c docengine-1.0.2.tar.gz.sha256
# Salida esperada: /opt/docengine/dist/docengine-1.0.2.tar.gz: OK (o coincidencia exacta del hash)
```

### Paso 2: Cargar la Imagen Docker en el Motor Local
Cargar la imagen comprimida directamente en Docker (Docker descomprime `.tar.gz` nativamente):

```bash
docker load -i docengine-1.0.2.tar.gz
```
*(Si el servidor utiliza Podman: `podman load -i docengine-1.0.2.tar.gz`)*

Verificar que la imagen quedó registrada:
```bash
docker images | grep docengine
# Debe mostrar: docengine   1.0.2   <IMAGE_ID>   ...
```

> **Nota sobre PostgreSQL (`pgvector`):** `docker-compose.yml` utiliza la imagen oficial `pgvector/pgvector:pg16`. Si el servidor tiene acceso a Docker Hub, Compose la descargará automáticamente al iniciar. Si el servidor está aislado (*air-gapped*), TI deberá importar también la imagen `pgvector/pgvector:pg16` mediante `docker load`.

### Paso 3: Preparar el Archivo `.env` de Producción
Copiar la plantilla `.env.example` hacia `.env` y configurar **obligatoriamente** los parámetros de producción:

```bash
cp .env.example .env
chmod 600 .env
```

Editar `/opt/docengine/.env` validando los siguientes valores críticos:

```ini
# --- Entorno y Motor ---
DOCENGINE_ENV=production
DOCENGINE_EXTRACTOR_ENGINE=pdfextract
DOCENGINE_LOG_LEVEL=INFO
DOCENGINE_LOG_FORMAT=json

# --- Base de Datos (deben coincidir entre app y contenedor postgres_db) ---
DOCENGINE_DB_HOST=postgres_db
DOCENGINE_DB_PORT=5432
DOCENGINE_DB_NAME=docengine
DOCENGINE_DB_USER=docengine
DOCENGINE_DB_PASSWORD=<DEFINIR_CONTRASEÑA_FUERTE_SIN_CARACTERES_ESPECIALES_URL>

# --- Proveedor LLM (Obligatorio en producción) ---
OPENAI_API_KEY=<TU_OPENAI_API_KEY_REAL>

# --- Seguridad, RBAC y Hardening (CRÍTICO) ---
DOCENGINE_SECURITY_ENABLED=true
DOCENGINE_API_KEYS={"<KEY_READONLY>":"readonly","<KEY_WRITER>":"writer","<KEY_ADMIN>":"admin"}
DOCENGINE_CORS_ORIGINS=https://docengine.tu-empresa.com
DOCENGINE_ENABLE_DOCS=false

# --- Rendimiento y Embeddings ---
DOCENGINE_PIPELINE_ACCELERATOR_DEVICE=cpu
DOCENGINE_EMBED_DEVICE=cpu
TORCH_COMPILE_DISABLE=1
```

> **Recomendación para generar API Keys seguras:**
> ```bash
> openssl rand -hex 32
> ```

### Paso 4: Configurar Compose para Usar la Imagen Pre-cargada (Sin Reconstruir)
Como `docker-compose.yml` incluye la directiva `build:`, para evitar que Docker Compose intente compilar desde el `Dockerfile` en producción, crear el archivo `/opt/docengine/docker-compose.offline.yml` con el siguiente contenido:

```yaml
services:
  docengine:
    build: !reset null
    image: docengine:1.0.2
```
*(Alternativamente, si se usa una versión de Compose que no soporte `!reset`, agregar `image: docengine:1.0.2` bajo `services.docengine` en `docker-compose.prod.yml` y ejecutar `up -d --no-build`.)*

### Paso 5: Preparar Directorios y Permisos de Volúmenes
El proceso dentro del contenedor se ejecuta con el usuario no-root `docengine` (no como `root`). Preparar las carpetas locales antes de levantar el stack:

```bash
mkdir -p /opt/docengine/outputs
chmod 777 /opt/docengine/outputs   # O asignar el UID del usuario 'docengine' del contenedor
chmod -R a+rX /opt/docengine/skills /opt/docengine/scripts /opt/docengine/config.yaml
```

*(Si el servidor tiene **SELinux en modo Enforcing**, como en Rocky Linux/RHEL, etiquetar los directorios montados para evitar bloqueos de lectura/escritura):*
```bash
sudo chcon -Rt container_file_t /opt/docengine/outputs /opt/docengine/skills /opt/docengine/scripts /opt/docengine/config.yaml
```

### Paso 6: Levantar los Servicios en Producción
1. Iniciar primero la base de datos para asegurar su inicialización limpia (ejecución de `001` a `013`):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.offline.yml up -d postgres_db
   ```
2. Esperar a que PostgreSQL esté saludable (`healthy`) y verificar que las tablas se crearon:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.offline.yml ps
   docker exec -it docengine_postgres psql -U docengine -d docengine -c "\dt"
   ```
3. Levantar el servicio `docengine`:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.offline.yml up -d docengine
   ```
4. Monitorear el arranque inicial (el primer inicio descarga modelos en `hf_cache`, puede tardar 1 a 3 minutos):
   ```bash
   docker logs -f docengine_api
   ```
   Esperar los mensajes de confirmación:
   * `Docling models loaded. Service ready.`
   * `RAG Pipeline Service initialized and ready.`
   * `RAG Query Service initialized and ready.`
   * `Uvicorn running on http://0.0.0.0:8000`

---

## 5. Configuraciones Posteriores (Post-Despliegue)

### 5.1 Reverse Proxy con Nginx y TLS
`docker-compose.prod.yml` expone el puerto únicamente en `127.0.0.1:8000` por seguridad.
1. Copiar `deploy/nginx.conf` a `/etc/nginx/conf.d/docengine.conf` (Rocky/RHEL) o `/etc/nginx/sites-available/docengine.conf` (Ubuntu/Debian).
2. Ajustar `server_name`, `ssl_certificate` y `ssl_certificate_key` con los certificados corporativos.
3. Validar y recargar Nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
4. Verificar que el firewall (`firewalld` / `ufw`) permita únicamente los puertos `80` y `443`, manteniendo el `8000` y `5432` cerrados hacia el exterior.

### 5.2 Tareas Programadas de Mantenimiento (Cron & Logrotate)
1. **Rotación de Logs:**
   ```bash
   sudo cp /opt/docengine/deploy/logrotate-docengine /etc/logrotate.d/docengine
   ```
2. **Limpieza de cargas temporales (`_uploads` > 24 horas):**
   ```bash
   chmod +x /opt/docengine/deploy/cleanup-uploads.sh
   # Agregar al crontab de root o del usuario administrador:
   # 0 3 * * * /opt/docengine/deploy/cleanup-uploads.sh
   ```

### 5.3 Respaldo de Base de Datos (Backup)
Programar un `pg_dump` diario automatizado sobre el contenedor `docengine_postgres` (respaldando esquema vectorial, estadísticas y ledger inmutable):
```bash
docker exec docengine_postgres pg_dump -U docengine -Fc docengine > /backups/docengine_$(date +%F).dump
```

---

## 6. Matriz de Riesgos Probables y Mitigación

| Riesgo Probable | Síntoma | Causa Raíz | Mitigación / Solución |
| :--- | :--- | :--- | :--- |
| **Error de permisos en `/var/log/docengine` o `/app/outputs`** | El contenedor reinicia o falla al escribir logs (`PermissionError`) | El contenedor corre como usuario no-root `docengine`, mientras el volumen Docker `docengine_logs` o `./outputs` nace propiedad de `root`. | Dar permisos al volumen o host: verificar UID (`docker run --rm --entrypoint id docengine:1.0.2`) y ejecutar `chown -R <UID>:<GID> ./outputs` y en el volumen `docengine_logs` (o ajustar `DOCENGINE_LOG_LOG_FILE=` vacío para usar solo `stdout` recolectado por Docker). |
| **Bloqueo SELinux en Rocky Linux / RHEL** | `Permission denied` al leer `/app/skills`, `/app/config.yaml` o scripts SQL | SELinux en modo `Enforcing` bloquea volúmenes sin etiqueta de contenedor. | Aplicar `chcon -Rt container_file_t` a los directorios montados o agregar `:Z` al final de cada volumen en `docker-compose.prod.yml`. |
| **Fallo al iniciar `postgres_db` con variables por defecto** | Error de autenticación (`password authentication failed for user "docengine"`) | `postgres_data` ya fue inicializado previamente con otro usuario/contraseña (`postgres`), o faltó `DOCENGINE_DB_PASSWORD` en `.env`. | Asegurar `.env` antes del primer `up`. Si hubo un arranque fallido previo, limpiar el volumen vacío (`docker volume rm ..._postgres_data`) antes de reintentar. |
| **Servidor sin salida a internet (Air-Gapped) en primer arranque** | Timeout o error descargando `BAAI/bge-m3` o modelos Docling | Los modelos de embeddings (`hf_cache`) se descargan en el primer inicio desde HuggingFace. | Pre-descargar los modelos en una máquina con internet dentro de un directorio y copiarlos al volumen `hf_cache`, o definir `DOCENGINE_PIPELINE_ARTIFACTS_PATH` apuntando a los modelos locales montados. |
| **Timeouts HTTP 504 en PDFs grandes** | Error 504 Gateway Timeout desde clientes o WebUI | Proxy inverso o balanceador con timeout estándar de 60s frente a PDFs de cientos de páginas con OCR. | Confirmar en Nginx `proxy_read_timeout 600s`, `proxy_send_timeout 600s` y `client_max_body_size 500M` (tal como viene en `deploy/nginx.conf`). |
| **Agotamiento de RAM (OOMKilled)** | El contenedor muere con código `137` durante cargas masivas o PDFs pesados | Concurrencia alta de OCR + `bge-m3` + `bge-reranker-v2-m3` simultáneos supera la RAM del host. | Mantener `--workers 1` (ya definido), límite de `12G` en compose, y asegurar swap de respaldo en el host (4-8 GB). |

---

## 7. Pool de Pruebas y Validaciones Requeridas (Aceptación de Pase a Producción)

Una vez levantados los servicios, el equipo de TI debe ejecutar **todas** las validaciones siguientes y registrar los resultados como evidencia de pase exitoso.

> Reemplazar `https://docengine.tu-empresa.com` (o `http://127.0.0.1:8000` en pruebas locales desde el servidor) y las claves de API configuradas en `.env`.

### Prueba 1: Salud del Servicio y Estado de Contenedores
* **Objetivo:** Confirmar que ambos contenedores están `Up (healthy)` y el endpoint responde.
* **Comando:**
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.offline.yml ps
  curl -s -f http://127.0.0.1:8000/api/v1/health | jq .
  ```
* **Resultado Esperado:** HTTP `200 OK` con `"status": "ok"` y `"environment": "production"`.

### Prueba 2: Validación de Versiones de Motor
* **Objetivo:** Verificar versión de la aplicación, Python 3.12 y Docling activo.
* **Comando:**
  ```bash
  curl -s -f http://127.0.0.1:8000/api/v1/version | jq .
  ```
* **Resultado Esperado:** HTTP `200 OK` con versión de `docling`, `python_version` (`3.12.x`) y `app_version`.

### Prueba 3: Seguridad, Hardening y RBAC (Crítica)
* **Objetivo:** Confirmar que la documentación OpenAPI está oculta y que el acceso sin API Key o con rol insuficiente es rechazado.
* **Comandos:**
  ```bash
  # 3a. Docs deshabilitados en producción (debe devolver 404)
  curl -i -s http://127.0.0.1:8000/docs | head -n 1

  # 3b. Acceso sin X-API-Key a endpoint protegido (debe devolver 401 Unauthorized)
  curl -i -s http://127.0.0.1:8000/api/v1/metrics | head -n 1

  # 3c. Acceso con X-API-Key válida de lectura (debe devolver 200 OK)
  curl -s -f -H "X-API-Key: <KEY_READONLY>" http://127.0.0.1:8000/api/v1/metrics | jq .

  # 3d. Intento de escritura usando rol readonly (debe devolver 403 Forbidden)
  curl -i -s -X POST -H "X-API-Key: <KEY_READONLY>" http://127.0.0.1:8000/api/v1/extract | head -n 1
  ```
* **Resultado Esperado:** `404`, `401`, `200`, y `403` respectivamente.

### Prueba 4: Conectividad PostgreSQL + Extensión `pgvector` + Catálogos
* **Objetivo:** Confirmar que los scripts `001`–`013` se ejecutaron y la base de datos responde a la API.
* **Comandos:**
  ```bash
  # Verificar extensión vector y tablas principales en PostgreSQL
  docker exec docengine_postgres psql -U docengine -d docengine -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
  docker exec docengine_postgres psql -U docengine -d docengine -c "SELECT COUNT(*) AS empresas FROM cat_aseguradoras;"

  # Verificar consulta de catálogos vía API
  curl -s -f -H "X-API-Key: <KEY_READONLY>" http://127.0.0.1:8000/api/v1/catalogs/companies | jq .
  ```
* **Resultado Esperado:** Extensión `vector` instalada y listado JSON de aseguradoras retornado sin errores.

### Prueba 5: Prueba Funcional End-to-End de Extracción e Indexación RAG
* **Objetivo:** Verificar el ciclo completo: recepción de PDF $\rightarrow$ extracción `pdfextract`/Docling $\rightarrow$ persistencia en `./outputs` $\rightarrow$ generación de embeddings (`bge-m3`) $\rightarrow$ guardado en PostgreSQL.
* **Comando (usando un PDF de prueba válido):**
  ```bash
  curl -s -f -X POST "http://127.0.0.1:8000/api/v1/extract" \
    -H "X-API-Key: <KEY_WRITER>" \
    -F "file=@/ruta/a/poliza_prueba.pdf" \
    -F "id_cliente=00000001-TEST" \
    -F "nombre_cliente=PRUEBA PRODUCCION TI" \
    -F "company_sigla=CRI" | jq .
  ```
* **Resultado Esperado:** HTTP `200 OK`, `status: "success"`, `document_id` y `rag_report.policy_id` generados, `rag_report.chunks_created > 0`, archivos creados en `/opt/docengine/outputs/` y registro visible en `GET /api/v1/policies/recent`.

### Prueba 6: Prueba de Consulta RAG + OpenAI + Reranker
* **Objetivo:** Validar conectividad con OpenAI, búsqueda híbrida en `pgvector` y funcionamiento del reranker.
* **Comandos:**
  ```bash
  # Verificar salud del servicio RAG
  curl -s -f -H "X-API-Key: <KEY_READONLY>" http://127.0.0.1:8000/api/v1/query/health | jq .

  # Realizar una pregunta sobre la póliza de prueba indexada en la Prueba 5
  curl -s -f -X POST "http://127.0.0.1:8000/api/v1/query" \
    -H "X-API-Key: <KEY_READONLY>" \
    -H "Content-Type: application/json" \
    -d '{"question": "¿Cuál es la vigencia o cobertura principal de esta póliza?", "filters": {"id_cliente": "00000001-TEST"}}' | jq .
  ```
* **Resultado Esperado:** Respuesta coherente generada por el LLM acompañada de `sources` con fragmentos recuperados.

### Prueba 7: Prueba de Acceso HTTPS Público (Vía Nginx) y Limpieza
* **Objetivo:** Confirmar TLS válido, acceso a WebUI (`/`, `/dashboard`) y posterior limpieza del registro sintético de prueba.
* **Comandos:**
  ```bash
  # Validar certificado TLS y respuesta vía dominio público
  curl -I -f https://docengine.tu-empresa.com/api/v1/health

  # Eliminar el documento de prueba usando rol ADMIN (usar el rag_report.policy_id de la Prueba 5)
  curl -s -f -X DELETE "http://127.0.0.1:8000/api/v1/policies/<POLICY_ID_PRUEBA>" \
    -H "X-API-Key: <KEY_ADMIN>" | jq .
  ```
* **Resultado Esperado:** HTTP `200 OK` sobre HTTPS sin errores de certificado y eliminación confirmada del documento de prueba.

---

## 8. Procedimiento de Rollback (Reversión)
En caso de requerir reversión a una versión previa:
1. Detener la versión actual (sin borrar los volúmenes `postgres_data`, `outputs` ni `hf_cache`):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.offline.yml down
   ```
2. Cargar la imagen `.tar.gz` de la versión anterior y actualizar el tag en `docker-compose.offline.yml`.
3. Levantar nuevamente el servicio con `up -d`.
