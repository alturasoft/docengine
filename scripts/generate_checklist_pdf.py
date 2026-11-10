"""DocEngine — Generador de Documento PDF: Checklist de Despliegue a Producción.

Construye un documento técnico HTML optimizado para impresión y genera
el archivo PDF en docs/Checklist_Despliegue_Produccion_DocEngine.pdf usando xhtml2pdf.
"""

from __future__ import annotations

import sys
from pathlib import Path

from xhtml2pdf import pisa


def build_html_content() -> str:
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>DocEngine — Checklist de Despliegue a Producción</title>
<style>
    @page {
        size: letter;
        margin: 14mm 14mm 16mm 14mm;
        @bottom-right {
            content: "Página " counter(page);
            font-size: 8pt;
            color: #64748b;
            font-family: Helvetica, Arial, sans-serif;
        }
        @bottom-left {
            content: "DocEngine — Checklist Técnico de Despliegue a Producción";
            font-size: 8pt;
            color: #64748b;
            font-family: Helvetica, Arial, sans-serif;
        }
    }

    body {
        font-family: Helvetica, Arial, sans-serif;
        color: #1e293b;
        background-color: #ffffff;
        line-height: 1.38;
        font-size: 8.8pt;
        margin: 0;
        padding: 0;
    }

    /* Portada */
    .cover-page {
        page-break-after: always;
        min-height: 80vh;
        border-left: 7px solid #1e3a8a;
        padding-left: 28px;
        margin-top: 50px;
    }

    .cover-badge {
        display: inline-block;
        background-color: #eff6ff;
        color: #1e40af;
        border: 1px solid #bfdbfe;
        padding: 4px 10px;
        border-radius: 4px;
        font-size: 8.5pt;
        font-weight: bold;
        margin-bottom: 22px;
    }

    .cover-title {
        font-size: 24pt;
        font-weight: bold;
        color: #0f172a;
        margin: 0 0 10px 0;
        line-height: 1.15;
    }

    .cover-subtitle {
        font-size: 11.5pt;
        color: #475569;
        margin: 0 0 35px 0;
        line-height: 1.45;
    }

    .cover-meta {
        font-size: 9pt;
        color: #334155;
        border-top: 2px solid #e2e8f0;
        padding-top: 18px;
    }

    .cover-meta table {
        width: 100%;
        border-collapse: collapse;
    }

    .cover-meta td {
        padding: 4px 0;
        border: none;
        vertical-align: top;
    }

    .cover-meta td.label {
        font-weight: bold;
        color: #0f172a;
        width: 160px;
    }

    /* Encabezados y Tipografía */
    h1 {
        font-size: 13.5pt;
        font-weight: bold;
        color: #0f172a;
        border-bottom: 2px solid #2563eb;
        padding-bottom: 3px;
        margin-top: 16px;
        margin-bottom: 8px;
        page-break-after: avoid;
    }

    h2 {
        font-size: 11pt;
        font-weight: bold;
        color: #1e3a8a;
        margin-top: 13px;
        margin-bottom: 6px;
        border-left: 3px solid #3b82f6;
        padding-left: 7px;
        page-break-after: avoid;
    }

    h3 {
        font-size: 9.5pt;
        font-weight: bold;
        color: #334155;
        margin-top: 10px;
        margin-bottom: 4px;
        page-break-after: avoid;
    }

    p {
        margin: 0 0 6px 0;
    }

    ul, ol {
        margin: 0 0 7px 0;
        padding-left: 18px;
    }

    li {
        margin-bottom: 2px;
    }

    /* Tablas */
    table.data-table {
        width: 100%;
        border-collapse: collapse;
        margin: 6px 0 10px 0;
        font-size: 7.8pt;
        page-break-inside: avoid;
    }

    table.data-table th {
        background-color: #f1f5f9;
        color: #1e293b;
        font-weight: bold;
        text-align: left;
        padding: 4px 6px;
        border: 1px solid #cbd5e1;
    }

    table.data-table td {
        padding: 3.5px 6px;
        border: 1px solid #e2e8f0;
        vertical-align: top;
    }

    table.data-table tr.even td {
        background-color: #f8fafc;
    }

    /* Bloques de Código */
    pre.code-block {
        background-color: #f8fafc;
        color: #0f172a;
        border: 1px solid #cbd5e1;
        border-left: 4px solid #3b82f6;
        padding: 6px 8px;
        font-family: "Courier New", Courier, monospace;
        font-size: 7.2pt;
        line-height: 1.24;
        margin: 5px 0 8px 0;
        page-break-inside: avoid;
    }

    pre.env-block {
        background-color: #f8fafc;
        color: #0f172a;
        border: 1px solid #cbd5e1;
        border-left: 4px solid #10b981;
        padding: 5px 7px;
        font-family: "Courier New", Courier, monospace;
        font-size: 6.7pt;
        line-height: 1.16;
        margin: 4px 0 6px 0;
        page-break-inside: avoid;
    }

    code.inline-code {
        font-family: "Courier New", Courier, monospace;
        font-size: 8pt;
        background-color: #f1f5f9;
        color: #0f172a;
        padding: 1px 3px;
        border-radius: 3px;
        border: 1px solid #e2e8f0;
    }

    /* Cajas de Alerta */
    .alert-box {
        border-radius: 4px;
        padding: 6px 10px;
        margin: 6px 0 8px 0;
        page-break-inside: avoid;
    }

    .alert-critical {
        background-color: #fef2f2;
        border: 1px solid #fecaca;
        border-left: 5px solid #dc2626;
        color: #991b1b;
    }

    .alert-critical strong {
        color: #7f1d1d;
    }

    .alert-note {
        background-color: #f0fdf4;
        border: 1px solid #bbf7d0;
        border-left: 5px solid #16a34a;
        color: #166534;
    }

    .alert-warning {
        background-color: #fffbeb;
        border: 1px solid #fef3c7;
        border-left: 5px solid #d97706;
        color: #92400e;
    }

    .page-break {
        page-break-after: always;
    }
</style>
</head>
<body>

<!-- PORTADA (PÁGINA 1) -->
<div class="cover-page">
    <div class="cover-badge">ARQUITECTURA DEVOPS & INFRAESTRUCTURA DE PRODUCCIÓN</div>
    <div class="cover-title">DocEngine — Checklist de Despliegue a Producción</div>
    <div class="cover-subtitle">
        Guía Técnica Integral de Pase a Producción (Windows a Linux), Hardening de Sistema,
        Vectorización RAG, Gestión de Memoria para Modelos IA y Operaciones.
    </div>

    <div class="cover-meta">
        <table>
            <tr>
                <td class="label">Sistema:</td>
                <td>DocEngine (Motor de Digitalización, Extracción OCR y Pipeline RAG)</td>
            </tr>
            <tr>
                <td class="label">Versión de Entrega:</td>
                <td>1.0.0 (Producción)</td>
            </tr>
            <tr>
                <td class="label">Fecha de Emisión:</td>
                <td>Octubre 2026</td>
            </tr>
            <tr>
                <td class="label">Rol Responsable:</td>
                <td>Arquitecto DevOps & Sistemas</td>
            </tr>
            <tr>
                <td class="label">Entorno Origen:</td>
                <td>Windows 11 (AMD Zen 4 / Workstation de Desarrollo)</td>
            </tr>
            <tr>
                <td class="label">Entorno Destino:</td>
                <td>Linux x86_64 (Ubuntu 22.04 / 24.04 LTS o Rocky Linux 8.10 / 9)</td>
            </tr>
            <tr>
                <td class="label">Stack Base:</td>
                <td>Python 3.12, FastAPI, Docling 2.0+, RapidOCR, PyTorch (bge-m3), PostgreSQL 16 + pgvector</td>
            </tr>
        </table>
    </div>
</div>

<!-- SECCIÓN 1 (PÁGINA 2) -->
<h1>1. Gestión de Rutas y Modelos Locales</h1>
<p>
    En la transición de Windows a Linux, el sistema de archivos pasa de ser insensible a mayúsculas/minúsculas
    (<em>case-insensitive</em>) y utilizar barras invertidas (<code>\\</code>), a ser <strong>estrictamente sensible (<em>case-sensitive</em>)</strong>
    y requerir rutas normalizadas POSIX (<code>/</code>). Se han auditado y resuelto los siguientes puntos críticos del código fuente:
</p>

<h2>1.1 Sensibilidad y Carga de Reglas Skills (<code>company_skill_loader.py</code>)</h2>
<p>
    La función <code class="inline-code">load_company_skill(sigla)</code> resuelve los archivos de reglas con el patrón
    <code class="inline-code">skills/skill-{canonical_sigla.lower()}.md</code> partiendo de
    <code class="inline-code">_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"</code>.
</p>
<ul>
    <li><strong>Riesgo en Linux:</strong> Si en el directorio <code class="inline-code">/opt/docengine/skills/</code> existe algún archivo con mayúsculas (ej. <code>Skill-BISA.md</code> o <code>skill-BISA.md</code>), la resolución en Linux fallará silenciosamente, reportando <em>"Company skill file not found"</em> y omitiendo las reglas específicas de la aseguradora.</li>
    <li><strong>Validación Requerida:</strong> Verificar que todos los archivos en disco se mantengan estrictamente en minúsculas: <code>skill-bisa.md</code>, <code>skill-cre.md</code>, <code>skill-ali-seg.md</code>, <code>skill-general.md</code>, etc.</li>
</ul>

<h2>1.2 Caché Persistente de Modelos de IA (PyTorch, HuggingFace y RapidOCR)</h2>
<p>
    El código en <code class="inline-code">app/config/settings.py</code> (L44-56), <code class="inline-code">embedding_service.py</code> (L48-57)
    y <code class="inline-code">reranker_service.py</code> implementa un fallback a <code class="inline-code">tempfile.gettempdir() / "huggingface"</code>
    cuando el usuario del sistema tiene un <code class="inline-code">$HOME</code> no existente o no escribible (típico de usuarios de servicio o contenedores).
</p>
<div class="alert-box alert-critical">
    <strong>ALERTA DE PRODUCCIÓN:</strong> Si la aplicación se ejecuta bajo un usuario de servicio sin home persistente, los modelos
    (<code>BAAI/bge-m3</code> de 2.2 GB y <code>bge-reranker-v2-m3</code> de 2.2 GB) se guardarán en <code>/tmp</code>. Los mecanismos
    del sistema (<code>systemd-tmpfiles-clean</code> o reinicios) purgarán periódicamente <code>/tmp</code>, provocando descargas masivas
    repetitivas que degradarán el ancho de banda y congelarán el arranque del servicio.
</div>
<p><strong>Configuración Segura Obligatoria:</strong> Crear un directorio persistente dedicado y enlazarlo en el entorno:</p>
<pre class="code-block">sudo mkdir -p /var/cache/docengine/{huggingface,torch,rapidocr}
sudo chown -R docengine:docengine /var/cache/docengine
sudo chmod -R 750 /var/cache/docengine</pre>

<h2>1.3 Rutas de Subida y Salida de Archivos</h2>
<p>
    En <code class="inline-code">app/api/v1/extraction.py</code> (L144), los archivos cargados se guardan temporalmente en:
    <code class="inline-code">Path("outputs") / "_uploads" / f"{uuid.uuid4()}_{file.filename}"</code>.
</p>
<ul>
    <li>En producción, el valor de <code class="inline-code">DOCENGINE_OUTPUT_OUTPUT_DIR</code> debe ser obligatoriamente una ruta absoluta: <code>/opt/docengine/outputs</code>.</li>
    <li>El directorio <code>/opt/docengine/outputs/_uploads</code> debe tener permisos de escritura (<code>rwx</code>) para el usuario <code>docengine</code>.</li>
</ul>

<div class="page-break"></div>

<!-- SECCIÓN 2 (PÁGINA 3) -->
<h1>2. Dependencias del Sistema y Entorno Virtual en Linux</h1>
<p>
    DocEngine utiliza librerías de aceleración C++, bindings de OpenCV y modelos ONNX/PyTorch. Se deben instalar
    las dependencias de sistema a nivel del sistema operativo antes de configurar el entorno virtual.
</p>

<h2>2.1 Paquetes del Sistema Operativo</h2>
<h3>En Ubuntu 22.04 / 24.04 LTS:</h3>
<pre class="code-block">sudo apt-get update &amp;&amp; sudo apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev \
    build-essential gcc g++ make \
    libgomp1 libgl1 libglib2.0-0 \
    tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng poppler-utils</pre>

<h3>En Rocky Linux 8.10 / 9 (o RHEL):</h3>
<pre class="code-block">sudo dnf install -y epel-release
sudo dnf install -y python3.12 python3.12-devel \
    gcc gcc-c++ make libgomp mesa-libGL glib2 \
    tesseract tesseract-langpack-spa tesseract-langpack-eng poppler-utils</pre>

<h2>2.2 Creación del Entorno Virtual e Instalación Paso a Paso</h2>
<div class="alert-box alert-critical">
    <strong>DEPENDENCIA CRÍTICA PROPIETARIA:</strong> El proyecto incluye el archivo wheel
    <code>pdfextract-1.0.0-py3-none-any.whl</code> en la raíz. Como <code>DOCENGINE_EXTRACTOR_ENGINE=pdfextract</code>
    es el motor predeterminado (<code>app/api/main.py</code> L45), este wheel <strong>debe ser instalado explícitamente</strong>
    en el virtualenv. De lo contrario, la API fallará al arrancar con <code>ModuleNotFoundError: No module named 'pdfextract'</code>.
</div>

<p>Comandos exactos para recrear el entorno limpio:</p>
<pre class="code-block"># 1. Crear usuario de sistema dedicado
sudo useradd -r -s /bin/false -d /opt/docengine docengine
sudo mkdir -p /opt/docengine
sudo chown -R docengine:docengine /opt/docengine

# 2. Situarse en el directorio del código
cd /opt/docengine

# 3. Crear entorno virtual aislado con Python 3.12
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Actualizar instaladores base de Python
pip install --no-cache-dir --upgrade pip setuptools wheel

# 5. Instalar dependencias de producción
pip install --no-cache-dir -r requirements.txt

# 6. Instalar el paquete propietario local pdfextract
pip install --no-cache-dir ./pdfextract-1.0.0-py3-none-any.whl

# 7. Precalentar y cachear pesos de modelos ONNX y Embeddings en disco
python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"</pre>

<div class="page-break"></div>

<!-- SECCIÓN 3.1 (PÁGINA 4) -->
<h1>3. Variables de Entorno y Secrets (Archivo <code>.env</code>)</h1>
<p>
    El motor de configuración se gestiona mediante <code class="inline-code">AppSettings</code> en <code>app/config/settings.py</code>
    utilizando <code>pydantic-settings</code>, junto con validaciones de seguridad en <code>app/api/security.py</code>.
</p>

<h2>3.1 Tabla de Parámetros de Configuración</h2>
<table class="data-table">
    <thead>
        <tr>
            <th style="width: 32%;">Variable</th>
            <th style="width: 20%;">Valor Producción</th>
            <th style="width: 48%;">Propósito Técnico</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>DOCENGINE_ENV</code></td>
            <td><code>production</code></td>
            <td>Normaliza a modo producción (activa formateador de logs JSON).</td>
        </tr>
        <tr class="even">
            <td><code>DOCENGINE_EXTRACTOR_ENGINE</code></td>
            <td><code>pdfextract</code></td>
            <td>Motor de extracción activo (<code>pdfextract</code> o <code>docling</code>).</td>
        </tr>
        <tr>
            <td><code>DOCENGINE_SECURITY_ENABLED</code></td>
            <td><code>true</code></td>
            <td>Exige autenticación mediante cabecera <code>X-API-Key</code> en endpoints API.</td>
        </tr>
        <tr class="even">
            <td><code>DOCENGINE_API_KEYS</code></td>
            <td><code>{"key":"role",...}</code></td>
            <td>Mapeo JSON de API Keys a privilegios (<code>readonly</code>, <code>writer</code>, <code>admin</code>).</td>
        </tr>
        <tr>
            <td><code>DOCENGINE_DB_HOST</code></td>
            <td><code>127.0.0.1</code></td>
            <td>Host del servidor PostgreSQL 16 con extensión pgvector.</td>
        </tr>
        <tr class="even">
            <td><code>DOCENGINE_DB_POOL_MIN / MAX</code></td>
            <td><code>4 / 20</code></td>
            <td>Dimensionamiento del pool de conexiones multihilo (psycopg2).</td>
        </tr>
        <tr>
            <td><code>OPENAI_API_KEY</code></td>
            <td><code>sk-proj-...</code></td>
            <td>Credencial para generación RAG y extracción estructurada (gpt-4.1-mini / gpt-4o).</td>
        </tr>
        <tr class="even">
            <td><code>DOCENGINE_PIPELINE_NUM_THREADS</code></td>
            <td><code>8</code></td>
            <td>Hilos CPU dedicados a la descomposición de páginas en Docling.</td>
        </tr>
        <tr>
            <td><code>DOCENGINE_PIPELINE_IMAGES_SCALE</code></td>
            <td><code>1.0</code></td>
            <td>Escala estándar de renderizado (1.0 = 72 DPI), previene desbordamiento de RAM.</td>
        </tr>
        <tr class="even">
            <td><code>DOCENGINE_EMBED_BATCH_SIZE</code></td>
            <td><code>8</code></td>
            <td>Batch size óptimo para inferencia de bge-m3 en CPU Linux (evita padding cuadrático).</td>
        </tr>
        <tr>
            <td><code>DOCENGINE_LOG_FORMAT</code></td>
            <td><code>json</code></td>
            <td>Salida JSON estructurada estándar para ingesta por syslog/journald/ELK.</td>
        </tr>
        <tr class="even">
            <td><code>HF_HOME / TORCH_HOME</code></td>
            <td><code>/var/cache/docengine/...</code></td>
            <td>Directorios de almacenamiento persistente de pesos para evitar re-descargas.</td>
        </tr>
    </tbody>
</table>

<p style="margin-top: 10px; font-size: 8.5pt; color: #475569;">
    El archivo completo listo para despliegue se presenta a continuación con todos los parámetros pre-sintonizados para entornos Linux de alta concurrencia.
</p>

<div class="page-break"></div>

<!-- SECCIÓN 3.2 (PÁGINA 5) -->
<h2>3.2 Archivo de Producción Completo: <code>/opt/docengine/.env</code></h2>
<pre class="env-block"># ==============================================================================
# DOCENGINE — CONFIGURACIÓN DE PRODUCCIÓN (LINUX)
# Ubicación: /opt/docengine/.env | Permisos: 600 (docengine:docengine)
# ==============================================================================

DOCENGINE_ENV=production
DOCENGINE_APP_NAME=DocEngine
DOCENGINE_APP_VERSION=1.0.0
DOCENGINE_EXTRACTOR_ENGINE=pdfextract
DOCENGINE_SKIP_SKILLS=false

# --- Seguridad y Control de Acceso (RBAC) ---
DOCENGINE_SECURITY_ENABLED=true
DOCENGINE_API_KEYS={"prod-read-789a6c2f":"readonly","prod-write-91b4d3e1":"writer","prod-admin-82c4f1a0":"admin"}

# --- Base de Datos PostgreSQL + pgvector ---
DOCENGINE_DB_HOST=127.0.0.1
DOCENGINE_DB_PORT=5432
DOCENGINE_DB_NAME=docengine
DOCENGINE_DB_USER=docengine_app
DOCENGINE_DB_PASSWORD=CAMBIAR_POR_PASSWORD_SEGURO_PROD
DOCENGINE_DB_POOL_MIN=4
DOCENGINE_DB_POOL_MAX=20

# --- OpenAI API (LLM) ---
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DOCENGINE_RAG_LLM_MODEL=gpt-4.1-mini
DOCENGINE_RAG_MAX_TOKENS=16384
DOCENGINE_RAG_TEMPERATURE=0.0
DOCENGINE_RAG_TOP_K=10
DOCENGINE_RAG_SIMILARITY_THRESHOLD=0.20

# --- Pipeline de Extracción y OCR ---
DOCENGINE_EXTRACTION_DO_OCR=true
DOCENGINE_EXTRACTION_FORCE_OCR_ALL_PAGES=false
DOCENGINE_EXTRACTION_AUTO_DETECT_PDF_TYPE=true
DOCENGINE_EXTRACTION_TABLE_MODE=ACCURATE
DOCENGINE_EXTRACTION_DO_TABLE_STRUCTURE=true
DOCENGINE_EXTRACTION_DO_CELL_MATCHING=true
DOCENGINE_EXTRACTION_FIX_SPACED_TEXT=true
DOCENGINE_EXTRACTION_SPLIT_MERGED_TABLES=true
DOCENGINE_OCR_ENGINE=rapidocr
DOCENGINE_OCR_LANGUAGES=["es","en"]

# --- Pipeline Técnico Docling y Embeddings ---
DOCENGINE_PIPELINE_NUM_THREADS=8
DOCENGINE_PIPELINE_ACCELERATOR_DEVICE=cpu
DOCENGINE_PIPELINE_PDF_BACKEND=docling_parse_v2
DOCENGINE_PIPELINE_IMAGES_SCALE=1.0
DOCENGINE_EMBED_MODEL_NAME=BAAI/bge-m3
DOCENGINE_EMBED_BATCH_SIZE=8
DOCENGINE_EMBED_NUM_THREADS=6
DOCENGINE_EMBED_DEVICE=cpu
DOCENGINE_EMBED_CHUNK_SIZE_CHARS=2500
DOCENGINE_EMBED_CHUNK_OVERLAP_CHARS=200
DOCENGINE_RERANKER_ENABLED=false

# --- Almacenamiento, Rendimiento y Logging ---
DOCENGINE_OUTPUT_OUTPUT_DIR=/opt/docengine/outputs
DOCENGINE_OUTPUT_INCLUDE_METADATA=true
DOCENGINE_OUTPUT_INCLUDE_REPORT=true
DOCENGINE_PERF_BATCH_SIZE=8
DOCENGINE_PERF_MAX_UPLOAD_SIZE_MB=500
DOCENGINE_PERF_REQUEST_TIMEOUT_SECONDS=300
DOCENGINE_LOG_LEVEL=INFO
DOCENGINE_LOG_FORMAT=json
DOCENGINE_LOG_LOG_FILE=/var/log/docengine/docengine.log

# --- Caché Persistente y Entorno Matemático ---
HF_HOME=/var/cache/docengine/huggingface
SENTENCE_TRANSFORMERS_HOME=/var/cache/docengine/huggingface
TRANSFORMERS_CACHE=/var/cache/docengine/huggingface
TORCH_HOME=/var/cache/docengine/torch
TORCHDYNAMO_DISABLE=1
TORCH_COMPILE_DISABLE=1
OMP_NUM_THREADS=6
MKL_NUM_THREADS=6</pre>

<div class="page-break"></div>

<!-- SECCIÓN 4 (PÁGINA 6) -->
<h1>4. Base de Datos y Vectorización (PostgreSQL 16 + pgvector)</h1>
<p>
    DocEngine utiliza PostgreSQL 16 con la extensión vectorial <code class="inline-code">vector</code> (dimensión 1024 para BAAI/bge-m3)
    y un esquema relacional/híbrido compuesto por 12 migraciones correlativas ubicadas en el directorio <code>scripts/</code>.
</p>

<h2>4.1 Preparación de la Base de Datos y Extensión</h2>
<pre class="code-block"># 1. Instalar PostgreSQL 16 y extensión pgvector (Ubuntu)
sudo apt-get install -y postgresql-16 postgresql-16-pgvector

# 2. Crear base de datos, usuario y habilitar pgvector
sudo -u postgres psql &lt;&lt; 'EOF'
CREATE DATABASE docengine;
CREATE USER docengine_app WITH ENCRYPTED PASSWORD 'CAMBIAR_POR_PASSWORD_SEGURO_PROD';
GRANT ALL PRIVILEGES ON DATABASE docengine TO docengine_app;
\c docengine
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO docengine_app;
EOF</pre>

<h2>4.2 Ejecución Automatizada de Migraciones</h2>
<p>
    El script <code class="inline-code">scripts/init_db.py</code> lee la configuración desde <code>settings.database</code>,
    detecta todos los archivos SQL ordenados alfabéticamente (desde <code>001_add_rag_tables.sql</code> hasta
    <code>012_add_client_name_search_indexes.sql</code>) y los ejecuta en modo autocommit.
</p>
<pre class="code-block">cd /opt/docengine &amp;&amp; source .venv/bin/activate
python scripts/init_db.py</pre>

<h2>4.3 Catálogo de Migraciones Ejecutadas</h2>
<table class="data-table">
    <thead>
        <tr>
            <th style="width: 40%;">Archivo de Migración</th>
            <th style="width: 60%;">Objetivo en el Esquema</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>001_add_rag_tables.sql</code></td>
            <td>Crea extensión <code>vector</code>, tablas <code>policies</code>, <code>policy_chunks</code> (vector 1024), <code>policy_raw_md</code>, <code>policy_structured_data</code> y trabajos.</td>
        </tr>
        <tr class="even">
            <td><code>002_parent_child_hybrid_search.sql</code></td>
            <td>Añade columnas <code>chunk_id</code>, <code>parent_id</code>, y columna generada <code>content_tsvector</code> con índice GIN para búsqueda en español.</td>
        </tr>
        <tr>
            <td><code>003_add_processing_stats_table.sql</code></td>
            <td>Crea tabla <code>processing_stats</code> para auditoría de tiempos, páginas y consumo de CPU.</td>
        </tr>
        <tr class="even">
            <td><code>004_add_policy_envelope.sql</code></td>
            <td>Agrupación de documentos por Sobre de Póliza (<code>policy_envelopes</code>).</td>
        </tr>
        <tr>
            <td><code>005_add_id_cliente.sql</code></td>
            <td>Columna indexada <code>id_cliente</code> (Carnet de Identidad o NIT) en sobres y pólizas.</td>
        </tr>
        <tr class="even">
            <td><code>006_add_master_catalogs.sql</code></td>
            <td>Catálogos maestros APS: <code>cat_aseguradoras</code>, <code>cat_tipos_documento</code>, <code>cat_ramos</code>.</td>
        </tr>
        <tr>
            <td><code>007_align_stats_company_sigla.sql</code></td>
            <td>Alineación de siglas de aseguradoras en estadísticas.</td>
        </tr>
        <tr class="even">
            <td><code>008_add_policy_section_summaries.sql</code></td>
            <td>Tabla de resúmenes de secciones para navegación contextual rápida de pólizas grandes.</td>
        </tr>
        <tr>
            <td><code>009_add_policy_fleet_vehicles.sql</code></td>
            <td>Tabla estructurada para flotillas de vehículos (placas, chasis, sumas aseguradas).</td>
        </tr>
        <tr class="even">
            <td><code>010_add_policy_insured_persons.sql</code></td>
            <td>Tabla de personas aseguradas para colectivos de vida, salud y accidentes.</td>
        </tr>
        <tr>
            <td><code>011_add_nombre_cliente.sql</code></td>
            <td>Columna de nombre o razón social del cliente / tomador.</td>
        </tr>
        <tr class="even">
            <td><code>012_add_client_name_search_indexes.sql</code></td>
            <td>Índices funcionales B-tree <code>LOWER(nombre_cliente)</code> para búsquedas ágiles ILIKE.</td>
        </tr>
    </tbody>
</table>

<div class="page-break"></div>

<!-- SECCIÓN 5 (PÁGINA 7) -->
<h1>5. Demonización y Servicios (Systemd)</h1>
<p>
    En producción, la API se gestiona mediante <code class="inline-code">systemd</code>. Es mandatorio utilizar
    <strong>1 solo worker de Uvicorn</strong>. Como cada proceso carga en memoria los modelos de visión, OCR y embeddings
    (consumiendo entre 2 y 4 GB de RAM), múltiples workers duplicarían innecesariamente los pesos estáticos en memoria.
    La concurrencia se resuelve mediante I/O asíncrono y los hilos internos de inferencia (OpenMP / PyTorch).
</p>

<h2>5.1 Archivo de Servicio: <code>/etc/systemd/system/docengine.service</code></h2>
<pre class="code-block">[Unit]
Description=DocEngine — API de Extracción Documental y RAG
Documentation=https://github.com/alturasoft/docengine
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=exec
User=docengine
Group=docengine
WorkingDirectory=/opt/docengine

# Archivo de variables de entorno de producción
EnvironmentFile=/opt/docengine/.env

# Ejecución a través del entorno virtual con 1 worker
ExecStart=/opt/docengine/.venv/bin/uvicorn main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --log-level info \
    --no-access-log

# Ciclo de vida y reinicios
Restart=always
RestartSec=10s
TimeoutStartSec=120s
TimeoutStopSec=30s

# --- LÍMITES DE SISTEMA PARA MODELOS IA ---
# Bloqueo de memoria en RAM: previene que los pesos de los modelos sean enviados a SWAP
LimitMEMLOCK=infinity
# Descriptores de archivos para subida masiva de PDFs y sockets de red
LimitNOFILE=65536
# Permite suficientes hilos para OpenMP, PyTorch y Tokenizers concurrentes
LimitNPROC=4096
# Evita que systemd limite la creación de hilos a bajo nivel en C++
TasksMax=infinity

# --- SEGURIDAD Y SANDBOXING ---
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=true
ReadWritePaths=/opt/docengine/outputs /var/log/docengine /var/cache/docengine

[Install]
WantedBy=multi-user.target</pre>

<h2>5.2 Comandos de Activación del Servicio</h2>
<pre class="code-block">sudo systemctl daemon-reload &amp;&amp; sudo systemctl enable docengine
sudo systemctl start docengine &amp;&amp; sudo systemctl status docengine</pre>

<div class="page-break"></div>

<!-- SECCIÓN 6 & 7 (PÁGINA 8) -->
<h1>6. Almacenamiento, Logs y Permisos</h1>

<h2>6.1 Matriz de Permisos de Directorios</h2>
<table class="data-table">
    <thead>
        <tr>
            <th style="width: 32%;">Directorio</th>
            <th style="width: 20%;">Usuario / Grupo</th>
            <th style="width: 15%;">Permiso</th>
            <th style="width: 33%;">Contenido</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>/opt/docengine/outputs</code></td>
            <td><code>docengine:docengine</code></td>
            <td><code>750 (rwxr-x---)</code></td>
            <td>Markdown extraído, JSONs, carpetas <code>_uploads</code> temporales.</td>
        </tr>
        <tr class="even">
            <td><code>/opt/docengine/skills</code></td>
            <td><code>docengine:docengine</code></td>
            <td><code>755 (rwxr-xr-x)</code></td>
            <td>Archivos de reglas de negocio por aseguradora (Solo Lectura).</td>
        </tr>
        <tr>
            <td><code>/var/log/docengine</code></td>
            <td><code>docengine:docengine</code></td>
            <td><code>750 (rwxr-x---)</code></td>
            <td>Logs estructurados JSON (<code>docengine.log</code>).</td>
        </tr>
        <tr class="even">
            <td><code>/var/cache/docengine</code></td>
            <td><code>docengine:docengine</code></td>
            <td><code>750 (rwxr-x---)</code></td>
            <td>Pesos cacheados de Hugging Face, Torch y RapidOCR.</td>
        </tr>
    </tbody>
</table>

<h2>6.2 Rotación de Logs (<code>/etc/logrotate.d/docengine</code>)</h2>
<pre class="code-block">/var/log/docengine/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 docengine docengine
    sharedscripts
    postrotate
        systemctl kill -s HUP docengine.service >/dev/null 2>&1 || true
    endscript
}</pre>

<h2>6.3 Proxy Inverso Nginx (<code>/etc/nginx/sites-available/docengine</code>)</h2>
<pre class="code-block">server {
    listen 80;
    server_name docengine.tudominio.com;

    client_max_body_size 500M;
    client_body_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
    }
}</pre>

<h1>7. Protocolo de Pruebas Post-Despliegue (Smoke Tests)</h1>
<pre class="code-block"># 1. Healthcheck general del servicio y base de datos
curl -s http://127.0.0.1:8000/api/v1/health | jq .

# 2. Verificación de versiones y motor activo (debe reportar pdfextract)
curl -s http://127.0.0.1:8000/api/v1/version | jq .

# 3. Test de subida y extracción con autenticación RBAC
curl -X POST "http://127.0.0.1:8000/api/v1/extract" \
  -H "X-API-Key: prod-write-91b4d3e1" \
  -F "file=@samples/test_policy.pdf" \
  -F "id_cliente=1234567" \
  -F "company_sigla=BISA" \
  -F "async_mode=false"

# 4. Monitoreo de logs estructurados en vivo
sudo journalctl -u docengine.service -f -o cat</pre>

</body>
</html>
"""


def generate_pdf() -> Path:
    base_dir = Path(__file__).resolve().parent.parent
    docs_dir = base_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    html_path = docs_dir / "Checklist_Despliegue_Produccion_DocEngine.html"
    pdf_path = docs_dir / "Checklist_Despliegue_Produccion_DocEngine.pdf"

    print("Construyendo documento HTML...")
    html_content = build_html_content()
    html_path.write_text(html_content, encoding="utf-8")
    print(f"HTML generado en: {html_path}")

    print("Compilando PDF con xhtml2pdf / ReportLab...")
    with open(pdf_path, "wb") as f:
        pisa_status = pisa.CreatePDF(html_content, dest=f)
        if pisa_status.err:
            print(f"[ERROR] Hubo errores durante la generación: {pisa_status.err}")
            sys.exit(1)

    print(f"[OK] Archivo PDF generado exitosamente en: {pdf_path}")
    print(f"Tamaño: {pdf_path.stat().st_size:,} bytes")
    return pdf_path


if __name__ == "__main__":
    generate_pdf()
