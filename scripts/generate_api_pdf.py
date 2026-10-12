"""DocEngine — Generador de Especificación Técnica de APIs en Formato PDF.

Construye un documento HTML profesional con estilos de impresión CSS optimizados
y utiliza Microsoft Edge Headless para compilar el archivo PDF final.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def build_html_content() -> str:
    """Construye el contenido HTML completo del documento técnico."""
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>DocEngine — Especificación Técnica de Endpoints y APIs (v1)</title>
<style>
    @page {
        size: letter;
        margin: 15mm 15mm 18mm 15mm;
        @bottom-right {
            content: "Página " counter(page);
            font-size: 8pt;
            color: #64748b;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        @bottom-left {
            content: "DocEngine v1.0 — Especificación Técnica de APIs";
            font-size: 8pt;
            color: #64748b;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        color: #1e293b;
        background-color: #ffffff;
        line-height: 1.45;
        font-size: 9.5pt;
        margin: 0;
        padding: 0;
    }

    /* Portada */
    .cover-page {
        page-break-after: always;
        min-height: 85vh;
        display: flex;
        flex-direction: column;
        justify-content: center;
        border-left: 8px solid #2563eb;
        padding-left: 32px;
        margin-top: 40px;
    }

    .cover-badge {
        display: inline-block;
        background: #eff6ff;
        color: #1d4ed8;
        border: 1px solid #bfdbfe;
        padding: 5px 12px;
        border-radius: 4px;
        font-size: 9pt;
        font-weight: 700;
        letter-spacing: 0.5px;
        margin-bottom: 25px;
        width: fit-content;
    }

    .cover-title {
        font-size: 26pt;
        font-weight: 800;
        color: #0f172a;
        margin: 0 0 12px 0;
        line-height: 1.2;
    }

    .cover-subtitle {
        font-size: 13pt;
        color: #475569;
        font-weight: 400;
        margin: 0 0 35px 0;
        line-height: 1.45;
        max-width: 90%;
    }

    .cover-meta {
        font-size: 9.5pt;
        color: #475569;
        border-top: 2px solid #e2e8f0;
        padding-top: 20px;
        max-width: 85%;
    }

    .cover-meta table {
        width: 100%;
        border-collapse: collapse;
        margin: 0;
    }

    .cover-meta td {
        border: none;
        padding: 4px 8px 4px 0;
        background: transparent !important;
    }

    .cover-meta td.label {
        font-weight: 700;
        color: #1e293b;
        width: 170px;
    }

    /* Encabezados y Secciones */
    h1 {
        font-size: 16pt;
        font-weight: 700;
        color: #0f172a;
        border-bottom: 2px solid #2563eb;
        padding-bottom: 5px;
        margin-top: 24px;
        margin-bottom: 12px;
        page-break-after: avoid;
    }

    h2 {
        font-size: 12.5pt;
        font-weight: 700;
        color: #1e3a8a;
        margin-top: 20px;
        margin-bottom: 10px;
        border-left: 3px solid #3b82f6;
        padding-left: 8px;
        page-break-after: avoid;
    }

    h3 {
        font-size: 10.5pt;
        font-weight: 600;
        color: #334155;
        margin-top: 14px;
        margin-bottom: 6px;
        page-break-after: avoid;
    }

    p {
        margin: 0 0 8px 0;
    }

    ul, ol {
        margin: 0 0 10px 0;
        padding-left: 20px;
    }

    li {
        margin-bottom: 4px;
    }

    /* Insignias de Verbos HTTP */
    .badge-get {
        display: inline-block;
        background: #0284c7;
        color: #ffffff;
        font-weight: 700;
        font-size: 8.5pt;
        padding: 3px 8px;
        border-radius: 4px;
        font-family: Consolas, monospace;
        letter-spacing: 0.5px;
    }

    .badge-post {
        display: inline-block;
        background: #059669;
        color: #ffffff;
        font-weight: 700;
        font-size: 8.5pt;
        padding: 3px 8px;
        border-radius: 4px;
        font-family: Consolas, monospace;
        letter-spacing: 0.5px;
    }

    .badge-delete {
        display: inline-block;
        background: #dc2626;
        color: #ffffff;
        font-weight: 700;
        font-size: 8.5pt;
        padding: 3px 8px;
        border-radius: 4px;
        font-family: Consolas, monospace;
        letter-spacing: 0.5px;
    }

    /* Tarjetas de Endpoints */
    .endpoint-card {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        margin: 14px 0 18px 0;
        padding: 12px 14px;
        page-break-inside: avoid;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }

    .endpoint-header {
        display: flex;
        align-items: center;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        padding: 6px 10px;
        border-radius: 4px;
        margin-bottom: 10px;
    }

    .endpoint-path {
        font-family: Consolas, "Courier New", monospace;
        font-weight: 700;
        color: #0f172a;
        margin-left: 10px;
        font-size: 10pt;
    }

    /* Tablas */
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 8px 0 12px 0;
        font-size: 8.5pt;
        page-break-inside: avoid;
    }

    th {
        background: #f1f5f9;
        color: #334155;
        font-weight: 600;
        text-align: left;
        padding: 5px 8px;
        border: 1px solid #cbd5e1;
    }

    td {
        padding: 5px 8px;
        border: 1px solid #e2e8f0;
        vertical-align: top;
    }

    tr:nth-child(even) td {
        background: #f8fafc;
    }

    /* Bloques de Código */
    pre {
        background: #f1f5f9;
        color: #0f172a;
        border: 1px solid #cbd5e1;
        padding: 8px 10px;
        border-radius: 4px;
        font-family: Consolas, "Courier New", monospace;
        font-size: 7.8pt;
        overflow-x: auto;
        margin: 6px 0 10px 0;
        line-height: 1.35;
        page-break-inside: avoid;
    }

    code {
        font-family: Consolas, "Courier New", monospace;
        font-size: 8.5pt;
        background: #f1f5f9;
        color: #0f172a;
        padding: 1px 4px;
        border-radius: 3px;
    }

    pre code {
        background: none;
        color: inherit;
        padding: 0;
    }

    /* Cajas Informativas */
    .callout {
        background: #f0fdf4;
        border: 1px solid #bbf7d0;
        border-left: 4px solid #16a34a;
        padding: 8px 12px;
        border-radius: 4px;
        margin: 10px 0;
        font-size: 8.8pt;
        page-break-inside: avoid;
    }

    .callout-title {
        font-weight: 700;
        color: #15803d;
        margin-bottom: 3px;
    }

    .callout-warning {
        background: #fffbeb;
        border: 1px solid #fef3c7;
        border-left: 4px solid #d97706;
    }

    .callout-warning .callout-title {
        color: #b45309;
    }

    .callout-info {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        border-left: 4px solid #2563eb;
    }

    .callout-info .callout-title {
        color: #1d4ed8;
    }

    .toc {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        padding: 14px 18px;
        border-radius: 6px;
        margin: 20px 0;
        page-break-inside: avoid;
    }

    .toc-title {
        font-weight: 700;
        font-size: 11pt;
        color: #0f172a;
        margin-bottom: 8px;
    }

    .toc ul {
        list-style-type: none;
        padding-left: 0;
        margin: 0;
    }

    .toc li {
        padding: 3px 0;
        font-size: 9pt;
    }

    .toc a {
        color: #2563eb;
        text-decoration: none;
        font-weight: 500;
    }
</style>
</head>
<body>

<!-- ==================================================================== -->
<!-- PORTADA -->
<!-- ==================================================================== -->
<div class="cover-page">
    <div class="cover-badge">DOCENGINE REST API &bull; ESPECIFICACIÓN TÉCNICA v1.0</div>
    <div class="cover-title">DocEngine — Especificación Técnica de Endpoints y APIs</div>
    <div class="cover-subtitle">
        Manual integral de integración y arquitectura para analistas y desarrolladores.<br>
        Ingesta documental, motor de sobres, persistencia vectorial y consultas semánticas RAG.
    </div>
    <div class="cover-meta">
        <table>
            <tr>
                <td class="label">Plataforma:</td>
                <td>DocEngine (FastAPI + IBM Docling + PostgreSQL pgvector)</td>
            </tr>
            <tr>
                <td class="label">Versión de la API:</td>
                <td>v1.0.0 (Prefijo global: <code>/api/v1</code>)</td>
            </tr>
            <tr>
                <td class="label">Formatos de Datos:</td>
                <td>JSON (UTF-8) / multipart/form-data</td>
            </tr>
            <tr>
                <td class="label">Fecha de Emisión:</td>
                <td>Octubre 2026</td>
            </tr>
            <tr>
                <td class="label">Estado del Documento:</td>
                <td>Especificación Técnica Oficial y Operativa</td>
            </tr>
        </table>
    </div>
</div>

<!-- ==================================================================== -->
<!-- TABLA DE CONTENIDOS -->
<!-- ==================================================================== -->
<div class="toc">
    <div class="toc-title">Índice del Contenido</div>
    <ul>
        <li><strong>1. Visión General:</strong> Propósito, formatos de intercambio y arquitectura de sobres.</li>
        <li><strong>2. Entornos y URLs Base:</strong> Direcciones por ciclo de vida (Desarrollo, Staging, Producción).</li>
        <li><strong>3. Autenticación y Autorización:</strong> Mecanismos de seguridad y cabeceras.</li>
        <li><strong>4. Convención Global de Errores y Respuestas:</strong> Estructura estándar JSON y códigos HTTP.</li>
        <li><strong>5. Paginación, Filtros y Orden:</strong> Reglas de consulta masiva y navegación.</li>
        <li><strong>6. Catálogo Detallado de Endpoints:</strong>
            <ul>
                <li>&bull; <em>6.1 Módulo Extraction:</em> Ingesta y extracción de PDFs (archivo, URL, carpeta y catálogo de aseguradoras).</li>
                <li>&bull; <em>6.2 Módulo Policies & Envelopes:</em> Búsqueda, consulta y <strong>eliminación limpia de sobres</strong>.</li>
                <li>&bull; <em>6.3 Módulo RAG Query:</em> Consultas en lenguaje natural con citas textuales y diagnóstico.</li>
                <li>&bull; <em>6.4 Módulo System & Health:</em> Monitoreo de latido, métricas y buffer de logs.</li>
            </ul>
        </li>
        <li><strong>7. Límites de Tasa (Rate Limiting) y Rendimiento:</strong> Capacidad de procesamiento y memoria.</li>
        <li><strong>8. Procesamiento Asíncrono e Idempotencia:</strong> Hashing SHA-256 y ciclo de vida de jobs.</li>
    </ul>
</div>

<!-- ==================================================================== -->
<!-- 1. VISIÓN GENERAL -->
<!-- ==================================================================== -->
<h1>1. Visión General</h1>
<p>
    <strong>DocEngine</strong> es una plataforma de servicios de alto rendimiento diseñada para la digitalización, extracción estructurada, 
    clasificación y consulta conversacional (RAG) de pólizas de seguro en Bolivia. 
</p>
<p>
    El sistema procesa documentos PDF complejos (nativos o escaneados con OCR), normaliza la estructura visual a Markdown estructurado y JSON, 
    fragmenta el contenido en jerarquías <em>Parent-Child</em>, genera representaciones vectoriales densas de 1024 dimensiones utilizando el modelo 
    local <strong>BAAI/bge-m3</strong>, y almacena la información tanto relacional como vectorialmente en <strong>PostgreSQL con la extensión pgvector</strong>.
</p>

<h3>Principios Clave de la API</h3>
<ul>
    <li><strong>Versionado Estricto:</strong> Todos los endpoints de negocio están bajo la ruta base <code>/api/v1/</code>, garantizando evolución controlada y compatibilidad hacia atrás.</li>
    <li><strong>Formato Estándar:</strong> Todas las peticiones y respuestas estructuradas utilizan <strong>JSON</strong> codificado en <strong>UTF-8</strong> (salvo la carga de archivos binarios vía <code>multipart/form-data</code>).</li>
    <li><strong>Idempotencia Nativa:</strong> Toda ingesta documental verifica el hash criptográfico SHA-256 del archivo; si el documento ya fue procesado, no se reprocesa innecesariamente, evitando costos de cómputo y duplicación de vectores.</li>
    <li><strong>Arquitectura de Sobres (Policy Envelopes):</strong> Los documentos no existen aislados; se agrupan lógicamente en "sobres" que representan la póliza completa (agrupando carátula, condicionados generales, condicionados particulares, liquidaciones y anexos).</li>
</ul>

<!-- ==================================================================== -->
<!-- 2. ENTORNOS Y URLS BASE -->
<!-- ==================================================================== -->
<h1>2. Entornos y URLs Base</h1>
<p>
    La API se despliega de forma desacoplada y puede consumirse a través de los siguientes endpoints base según el ciclo de vida del software:
</p>

<table>
    <thead>
        <tr>
            <th>Entorno</th>
            <th>URL Base de Endpoints</th>
            <th>Documentación Swagger UI</th>
            <th>Propósito</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Desarrollo Local</strong></td>
            <td><code>http://localhost:8000/api/v1</code></td>
            <td><code>http://localhost:8000/docs</code></td>
            <td>Pruebas locales, ejecución directa con Uvicorn.</td>
        </tr>
        <tr>
            <td><strong>Staging / Pruebas</strong></td>
            <td><code>http://192.168.1.50:8000/api/v1</code></td>
            <td><code>http://192.168.1.50:8000/docs</code></td>
            <td>Validación de integración y QA con clientes internos.</td>
        </tr>
        <tr>
            <td><strong>Producción</strong></td>
            <td><code>https://docengine.altura.bo/api/v1</code></td>
            <td><code>https://docengine.altura.bo/docs</code></td>
            <td>Servidor productivo de alta concurrencia.</td>
        </tr>
    </tbody>
</table>

<div class="callout callout-info">
    <div class="callout-title">Documentación Interactiva OpenAPI</div>
    DocEngine expone la especificación OpenAPI estándar en <code>/openapi.json</code> y provee interfaces interactivas para pruebas en <code>/docs</code> (Swagger UI) y <code>/redoc</code> (ReDoc).
</div>

<!-- ==================================================================== -->
<!-- 3. AUTENTICACIÓN Y AUTORIZACIÓN -->
<!-- ==================================================================== -->
<h1>3. Autenticación y Autorización</h1>
<p>
    En la fase actual de despliegue para redes internas protegidas (VPC corporativa), los endpoints operan sin restricción de tokens públicos. 
    Para despliegues expuestos a internet o consumo por aplicaciones de terceros, la convención estándar adoptada por la arquitectura es:
</p>
<ul>
    <li><strong>Encabezado HTTP:</strong> <code>Authorization: Bearer &lt;TOKEN_JWT&gt;</code> o <code>X-API-Key: &lt;SECRET_KEY&gt;</code>.</li>
    <li><strong>Manejo de Errores de Acceso:</strong>
        <ul>
            <li><code>401 Unauthorized</code>: Ausencia de token o token caducado/inválido.</li>
            <li><code>403 Forbidden</code>: Credencial válida pero sin privilegios suficientes para la operación (ej. permisos de solo lectura intentando ejecutar <code>DELETE</code>).</li>
        </ul>
    </li>
</ul>

<!-- ==================================================================== -->
<!-- 4. CONVENCIÓN GLOBAL DE ERRORES Y RESPUESTAS -->
<!-- ==================================================================== -->
<h1>4. Convención Global de Errores y Respuestas</h1>
<p>
    DocEngine se adhiere a las mejores prácticas de diseño RESTful y convenciones estándar de FastAPI/Starlette.
</p>

<h3>Estructura Estándar de Error JSON</h3>
<pre><code>{
  "detail": "Descripción precisa y legible del motivo del error o validación"
}</code></pre>

<h3>Códigos de Estado HTTP Admitidos</h3>
<table>
    <thead>
        <tr>
            <th>Código HTTP</th>
            <th>Significado</th>
            <th>Contexto en DocEngine</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>200 OK</strong></td>
            <td>Éxito</td>
            <td>La petición se procesó exitosamente y se retorna la información solicitada.</td>
        </tr>
        <tr>
            <td><strong>400 Bad Request</strong></td>
            <td>Petición inválida</td>
            <td>Parámetros incorrectos, archivo con formato no admitido (solo se admite PDF) o payload malformado.</td>
        </tr>
        <tr>
            <td><strong>404 Not Found</strong></td>
            <td>No encontrado</td>
            <td>El sobre (<code>envelope_id</code>), documento (<code>policy_id</code>) o recurso solicitado no existe en la base de datos.</td>
        </tr>
        <tr>
            <td><strong>422 Unprocessable Entity</strong></td>
            <td>Error de validación</td>
            <td>Error de validación de tipos o restricciones Pydantic en los datos enviados.</td>
        </tr>
        <tr>
            <td><strong>500 Internal Server Error</strong></td>
            <td>Error interno</td>
            <td>Excepción no controlada en el motor de extracción Docling o en PostgreSQL.</td>
        </tr>
        <tr>
            <td><strong>503 Service Unavailable</strong></td>
            <td>Servicio no disponible</td>
            <td>El servicio de consultas RAG o la base de datos se encuentran en proceso de inicialización o fuera de línea.</td>
        </tr>
    </tbody>
</table>

<!-- ==================================================================== -->
<!-- 5. PAGINACIÓN, FILTROS Y ORDEN -->
<!-- ==================================================================== -->
<h1>5. Paginación, Filtros y Orden</h1>
<p>
    Para evitar sobrecargar la memoria y el ancho de banda al listar colecciones de datos, los endpoints de consulta masiva implementan parámetros de paginación por desplazamiento:
</p>
<table>
    <thead>
        <tr>
            <th>Parámetro</th>
            <th>Tipo</th>
            <th>Por Defecto</th>
            <th>Descripción</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>limit</code></td>
            <td>integer</td>
            <td>20 / 50</td>
            <td>Cantidad máxima de registros a retornar por página (máximo permitido: 100).</td>
        </tr>
        <tr>
            <td><code>offset</code></td>
            <td>integer</td>
            <td>0</td>
            <td>Cantidad de registros a omitir desde el inicio del conjunto de resultados.</td>
        </tr>
        <tr>
            <td><code>company_sigla</code></td>
            <td>string</td>
            <td>null</td>
            <td>Filtro opcional por sigla oficial de la aseguradora (ej. <code>CRI</code>, <code>ALI</code>, <code>LBC</code>).</td>
        </tr>
    </tbody>
</table>
<p>
    <strong>Ordenamiento:</strong> Los resultados se devuelven por defecto ordenados descendentemente por fecha de actualización/creación (<code>updated_at DESC, created_at DESC</code>).
</p>

<!-- ==================================================================== -->
<!-- 6. CATÁLOGO DETALLADO DE ENDPOINTS -->
<!-- ==================================================================== -->
<h1>6. Catálogo Detallado de Endpoints</h1>

<!-- 6.1 EXTRACTION -->
<h2>6.1 Módulo de Ingesta y Extracción Documental (Extraction)</h2>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-post">POST</span>
        <span class="endpoint-path">/api/v1/extract</span>
    </div>
    <p><strong>Propósito:</strong> Carga un archivo PDF binario para su extracción documental, generación de Markdown, atomización de coberturas, generación de embeddings (BGE-M3) y persistencia en PostgreSQL.</p>
    <p><strong>Content-Type:</strong> <code>multipart/form-data</code></p>
    <table>
        <thead>
            <tr>
                <th>Campo Form</th>
                <th>Tipo</th>
                <th>Requerido</th>
                <th>Descripción</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><code>file</code></td>
                <td>Binary</td>
                <td><strong>Sí</strong></td>
                <td>Archivo PDF de la póliza de seguro.</td>
            </tr>
            <tr>
                <td><code>company_sigla</code></td>
                <td>string</td>
                <td>No</td>
                <td>Sigla de la aseguradora (ej. <code>CRI</code>, <code>ALI</code>, <code>LBC</code>) para aplicar reglas especializadas.</td>
            </tr>
            <tr>
                <td><code>numero_poliza</code></td>
                <td>string</td>
                <td>No</td>
                <td>Número de póliza para vincular el documento a un sobre lógico existente o crear uno nuevo.</td>
            </tr>
            <tr>
                <td><code>ramo</code></td>
                <td>string</td>
                <td>No</td>
                <td>Ramo de seguro (ej. <code>AUTOMOTOR</code>, <code>INCENDIO</code>, <code>SALUD</code>).</td>
            </tr>
            <tr>
                <td><code>tipo_documento</code></td>
                <td>string</td>
                <td>No</td>
                <td>Clasificación documental (<code>POLIZA_PRINCIPAL</code>, <code>CONDICIONADO_GENERAL</code>, <code>CONDICIONADO_PARTICULAR</code>, <code>LIQUIDACION_PAGOS</code>, <code>ANEXO</code>).</td>
            </tr>
        </tbody>
    </table>
    <p><strong>Ejemplo de Respuesta (200 OK):</strong></p>
<pre><code>{
  "document_id": "4b684531-10df-4f40-84cf-8d9633e6c0c2",
  "status": "success",
  "markdown_preview": "# PÓLIZA DE SEGURO AUTOMOTOR\\n\\n## CONDICIONES PARTICULARES...",
  "metadata": {
    "filename": "poliza_automotor.pdf",
    "sha256": "c5d1b7a956d43e882a1738be78...",
    "page_count": 12,
    "extraction_time_seconds": 3.84,
    "company_sigla": "CRI",
    "envelope_id": "b3e0c091-6fa7-4f68-9bf9-a9a7a9354060",
    "tipo_documento": "CONDICIONADO_PARTICULAR"
  },
  "rag_report": {
    "policy_id": "4b684531-10df-4f40-84cf-8d9633e6c0c2",
    "chunks_created": 24,
    "skipped_duplicate": false,
    "envelope_id": "b3e0c091-6fa7-4f68-9bf9-a9a7a9354060",
    "tipo_documento": "CONDICIONADO_PARTICULAR"
  }
}</code></pre>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-post">POST</span>
        <span class="endpoint-path">/api/v1/extract/url</span>
    </div>
    <p><strong>Propósito:</strong> Descarga y procesa un documento PDF accesible a través de una URL pública.</p>
    <p><strong>Content-Type:</strong> <code>application/json</code></p>
<pre><code>// Body de Petición:
{
  "url": "https://storage.ejemplo.com/polizas/2026/poliza_9988.pdf",
  "company_sigla": "ALI"
}</code></pre>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-post">POST</span>
        <span class="endpoint-path">/api/v1/extract/folder</span>
    </div>
    <p><strong>Propósito:</strong> Procesa de forma recursiva por lotes todos los archivos PDF presentes en una carpeta del servidor local.</p>
    <p><strong>Content-Type:</strong> <code>application/json</code></p>
<pre><code>// Body de Petición:
{
  "folder_path": "C:/datos/polizas_ingesta/lote_enero",
  "company_sigla": "LBC",
  "recursive": true
}</code></pre>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/extract/companies</span>
    </div>
    <p><strong>Propósito:</strong> Retorna el catálogo oficial de siglas y nombres completos de las 16 compañías aseguradoras bolivianas soportadas por el motor.</p>
    <p><strong>Ejemplo de Respuesta (200 OK):</strong></p>
<pre><code>{
  "ALI": "ALIANZA COMPAÑIA DE SEGUROS Y REASEGUROS S.A.",
  "BIS": "BISA SEGUROS Y REASEGUROS S.A.",
  "CRI": "CREDINFORM INTERNATIONAL S.A. DE SEGUROS",
  "FOR": "FORTALEZA SEGUROS Y REASEGUROS S.A.",
  "LBC": "LA BOLIVIANA CIACRUZ DE SEGUROS Y REASEGUROS S.A.",
  "MSC": "NACIONAL SEGUROS PATRIMONIALES Y FIANZAS S.A."
}</code></pre>
</div>

<!-- 6.2 POLICIES & ENVELOPES -->
<h2>6.2 Módulo de Pólizas y Gestión de Sobres (Policies & Envelopes)</h2>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/policies/envelopes</span>
    </div>
    <p><strong>Propósito:</strong> Lista los sobres de pólizas indexados, paginados y con el resumen de documentos vinculados.</p>
    <table>
        <thead>
            <tr>
                <th>Parámetro Query</th>
                <th>Tipo</th>
                <th>Por Defecto</th>
                <th>Descripción</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><code>limit</code></td>
                <td>integer</td>
                <td>50</td>
                <td>Máximo de sobres a devolver (1 - 100).</td>
            </tr>
            <tr>
                <td><code>offset</code></td>
                <td>integer</td>
                <td>0</td>
                <td>Desplazamiento para paginación.</td>
            </tr>
            <tr>
                <td><code>company_sigla</code></td>
                <td>string</td>
                <td>null</td>
                <td>Filtro opcional por sigla de aseguradora (ej. <code>CRI</code>).</td>
            </tr>
        </tbody>
    </table>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/policies/envelopes/by-number/{numero_poliza}</span>
    </div>
    <p><strong>Propósito:</strong> Busca y devuelve los sobres y documentos que coincidan con el número de póliza especificado.</p>
    <p><strong>Parámetros:</strong> <code>numero_poliza</code> (Path, string), <code>company_sigla</code> (Query, opcional).</p>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/policies/envelopes/{envelope_id}</span>
    </div>
    <p><strong>Propósito:</strong> Retorna el detalle completo de un sobre y todos sus documentos asociados a partir de su UUID único.</p>
    <p><strong>Ejemplo de Respuesta (200 OK):</strong></p>
<pre><code>{
  "id": "b3e0c091-6fa7-4f68-9bf9-a9a7a9354060",
  "numero_poliza": "POL-AUTO-998877",
  "company_sigla": "CRI",
  "ramo": "AUTOMOTOR",
  "created_at": "2026-10-01T14:20:00Z",
  "updated_at": "2026-10-01T14:22:15Z",
  "documents_count": 2,
  "documents": [
    {
      "policy_id": "4b684531-10df-4f40-84cf-8d9633e6c0c2",
      "file_name": "caratula_y_condiciones.pdf",
      "file_hash": "c5d1b7a956d43e882a1738be78...",
      "company_sigla": "CRI",
      "tipo_documento": "CONDICIONADO_PARTICULAR",
      "total_pages": 8,
      "file_size_bytes": 1045230,
      "created_at": "2026-10-01T14:20:10Z"
    },
    {
      "policy_id": "9d182741-22aa-4c55-b8dd-1a2b3c4d5e6f",
      "file_name": "plan_pagos.pdf",
      "file_hash": "a1b2c3d4e5f6...",
      "company_sigla": "CRI",
      "tipo_documento": "LIQUIDACION_PAGOS",
      "total_pages": 2,
      "file_size_bytes": 312450,
      "created_at": "2026-10-01T14:22:15Z"
    }
  ]
}</code></pre>
</div>

<!-- DELETE ENVELOPE -->
<div class="endpoint-card" style="border-left: 4px solid #dc2626;">
    <div class="endpoint-header">
        <span class="badge-delete">DELETE</span>
        <span class="endpoint-path">/api/v1/policies/envelopes/{envelope_id}</span>
    </div>
    <p><strong>Propósito:</strong> Elimina de forma atómica y completa una póliza entera (sobre) y todos los documentos que contiene en la base de datos y opcionalmente en el disco local.</p>
    
    <div class="callout callout-warning">
        <div class="callout-title">Comportamiento en Cascada y Limpieza Transaccional</div>
        Al invocar este endpoint, la base de datos elimina en cascada todas las tablas hijas asociadas a cada documento:
        <code>policy_chunks</code> (vectores), <code>policy_raw_md</code> (markdown), <code>policy_structured_data</code> (JSON de coberturas) 
        y <code>policy_processing_stats</code> (telemetría). Al eliminarse los registros en <code>policies</code>, 
        los hashes criptográficos quedan liberados, permitiendo volver a subir los documentos corregidos inmediatamente sin conflicto de idempotencia.
    </div>

    <table>
        <thead>
            <tr>
                <th>Parámetro</th>
                <th>Ubicación</th>
                <th>Tipo</th>
                <th>Por Defecto</th>
                <th>Descripción</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><code>envelope_id</code></td>
                <td>Path</td>
                <td>string (UUID)</td>
                <td><strong>Requerido</strong></td>
                <td>Identificador único del sobre a eliminar.</td>
            </tr>
            <tr>
                <td><code>delete_files</code></td>
                <td>Query</td>
                <td>boolean</td>
                <td><code>true</code></td>
                <td>Si es <code>true</code>, busca y elimina también del disco los subdirectorios en <code>outputs/{SIGLA}/{filename_stem}</code>.</td>
            </tr>
        </tbody>
    </table>

    <p><strong>Ejemplo de Respuesta (200 OK):</strong></p>
<pre><code>{
  "envelope_id": "b3e0c091-6fa7-4f68-9bf9-a9a7a9354060",
  "numero_poliza": "POL-AUTO-998877",
  "company_sigla": "CRI",
  "ramo": "AUTOMOTOR",
  "deleted_documents_count": 2,
  "deleted_documents": [
    {
      "policy_id": "4b684531-10df-4f40-84cf-8d9633e6c0c2",
      "file_name": "caratula_y_condiciones.pdf",
      "file_hash": "c5d1b7a956d43e882a1738be78...",
      "company_sigla": "CRI"
    },
    {
      "policy_id": "9d182741-22aa-4c55-b8dd-1a2b3c4d5e6f",
      "file_name": "plan_pagos.pdf",
      "file_hash": "a1b2c3d4e5f6...",
      "company_sigla": "CRI"
    }
  ],
  "deleted_disk_dirs": [
    "outputs\\CRI\\caratula_y_condiciones",
    "outputs\\CRI\\plan_pagos"
  ],
  "message": "Sobre de póliza y todos sus documentos asociados fueron eliminados exitosamente."
}</code></pre>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/policies/recent</span>
    </div>
    <p><strong>Propósito:</strong> Retorna las pólizas más recientes con sus 6 campos canónicos normalizados (número de póliza, asegurado, ramo, documento, vigencia, prima total). Parámetro: <code>limit</code> (Query, defecto 20).</p>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/policies/search</span>
    </div>
    <p><strong>Propósito:</strong> Búsqueda rápida por número de póliza, UUID o palabra clave. Parámetro: <code>q</code> (Query, string requerido).</p>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/policies/{policy_id}</span>
    </div>
    <p><strong>Propósito:</strong> Obtiene la información básica de un documento específico de póliza a través de su UUID.</p>
</div>

<!-- 6.3 RAG QUERY -->
<h2>6.3 Módulo de Consultas Semánticas RAG (RAG Query)</h2>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-post">POST</span>
        <span class="endpoint-path">/api/v1/query</span>
    </div>
    <p><strong>Propósito:</strong> Responde preguntas formuladas en lenguaje natural sobre las pólizas digitalizadas, sintetizando una respuesta fundamentada con citas textuales a partir de fragmentos semánticos recuperados en pgvector.</p>
    <p><strong>Content-Type:</strong> <code>application/json</code></p>
    <table>
        <thead>
            <tr>
                <th>Campo JSON</th>
                <th>Tipo</th>
                <th>Por Defecto</th>
                <th>Descripción</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><code>question</code></td>
                <td>string</td>
                <td><strong>Requerido</strong></td>
                <td>Pregunta en lenguaje natural formulada por el usuario.</td>
            </tr>
            <tr>
                <td><code>top_k</code></td>
                <td>integer</td>
                <td>5</td>
                <td>Cantidad de fragmentos contextuales a recuperar (1 - 20).</td>
            </tr>
            <tr>
                <td><code>similarity_threshold</code></td>
                <td>float</td>
                <td>0.40</td>
                <td>Umbral mínimo de similitud coseno para descartar fragmentos irrelevantes.</td>
            </tr>
            <tr>
                <td><code>filters</code></td>
                <td>object</td>
                <td>null</td>
                <td>Filtros de metadatos opcionales (ej. <code>{"company_sigla": "CRI"}</code>).</td>
            </tr>
        </tbody>
    </table>

    <p><strong>Ejemplo de Respuesta (200 OK):</strong></p>
<pre><code>{
  "answer": "La cobertura de Responsabilidad Civil Extracontractual cubre hasta un límite máximo de USD 20,000.00 por evento, con un deducible aplicable del 10% del monto indemnizable.",
  "question": "¿Cuál es el límite de responsabilidad civil y su deducible?",
  "chunks_retrieved": 3,
  "sources": [
    {
      "chunk_id": "f8a92b3c-...",
      "policy_id": "4b684531-...",
      "file_name": "condicionado_particular.pdf",
      "company_sigla": "CRI",
      "page_number": 4,
      "similarity_score": 0.884,
      "content": "CLÁUSULA 4. RESPONSABILIDAD CIVIL: Límite USD 20,000.00..."
    }
  ],
  "latency_seconds": 1.42
}</code></pre>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/query/health</span>
    </div>
    <p><strong>Propósito:</strong> Verifica que el modelo de embeddings BGE-M3 y el motor vectorial se encuentren cargados en memoria y listos para inferencia.</p>
</div>

<!-- 6.4 SYSTEM & HEALTH -->
<h2>6.4 Módulo de Sistema y Monitoreo (System & Health)</h2>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/health</span>
    </div>
    <p><strong>Propósito:</strong> Verificación básica de latido del servicio (<em>liveness check</em>). Retorna <code>{"status": "ok"}</code>.</p>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/health/system</span>
    </div>
    <p><strong>Propósito:</strong> Reporte técnico completo: versión de DocEngine, motor de extracción (Docling/PDFExtract), modelos OCR y conectividad a PostgreSQL.</p>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/health/metrics</span>
    </div>
    <p><strong>Propósito:</strong> Estadísticas acumuladas: documentos procesados, páginas totales, tablas detectadas, tiempo promedio y tasa de éxito.</p>
</div>

<div class="endpoint-card">
    <div class="endpoint-header">
        <span class="badge-get">GET</span>
        <span class="endpoint-path">/api/v1/health/logs</span>
    </div>
    <p><strong>Propósito:</strong> Consulta el búfer circular en memoria de los últimos eventos del servidor (filtrable por nivel: <code>level=INFO|WARNING|ERROR</code>, <code>limit=100</code>).</p>
</div>

<!-- ==================================================================== -->
<!-- 7. LÍMITES DE TASA Y RENDIMIENTO -->
<!-- ==================================================================== -->
<h1>7. Límites de Tasa (Rate Limiting) y Rendimiento</h1>
<p>
    Debido a que DocEngine ejecuta modelos locales de inteligencia artificial (modelos de visión OCR y modelo BGE-M3 de 1024 dimensiones), 
    el rendimiento y la concurrencia deben gestionarse cuidadosamente:
</p>
<ul>
    <li><strong>Extracción e Ingesta:</strong> Operación intensiva en CPU/GPU. Se recomienda mantener una tasa máxima de <strong>10 a 15 documentos concurrentes</strong> por instancia para evitar saturación de memoria RAM.</li>
    <li><strong>Consultas RAG:</strong> Operación liviana; el modelo BGE-M3 procesa la pregunta en menos de 50ms y pgvector responde en menos de 15ms. Capacidad recomendada: <strong>100 solicitudes por minuto por nodo</strong>.</li>
    <li><strong>Memoria RAM Requerida:</strong> Mínimo 8 GB (16 GB recomendado para soporte simultáneo de OCR multihilo y BGE-M3).</li>
</ul>

<!-- ==================================================================== -->
<!-- 8. PROCESAMIENTO ASÍNCRONO E IDEMPOTENCIA -->
<!-- ==================================================================== -->
<h1>8. Procesamiento Asíncrono e Idempotencia</h1>

<h3>Garantía de Idempotencia Criptográfica</h3>
<p>
    Cada archivo recibido se somete al cálculo inmediato de su firma SHA-256 (columna <code>file_hash</code> con restricción <code>UNIQUE</code> en la tabla <code>policies</code>). 
    Si un archivo con el mismo hash ya existe en el sistema:
</p>
<ol>
    <li>Se omite la costosa fase de extracción Docling y vectorización.</li>
    <li>El trabajo se marca como <code>status: SKIPPED</code> en la tabla <code>processing_jobs</code>.</li>
    <li>Se retorna inmediatamente el identificador existente y se asocia al sobre indicado.</li>
</ol>

<h3>Ciclo de Vida de los Trabajos (Jobs)</h3>
<table>
    <thead>
        <tr>
            <th>Estado</th>
            <th>Significado</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>PENDING</code></td>
            <td>Archivo en cola de recepción.</td>
        </tr>
        <tr>
            <td><code>PROCESSING</code></td>
            <td>Extracción Docling, chunking o vectorización en curso.</td>
        </tr>
        <tr>
            <td><code>COMPLETED</code></td>
            <td>Documento procesado e indexado exitosamente en PostgreSQL.</td>
        </tr>
        <tr>
            <td><code>SKIPPED</code></td>
            <td>Documento omitido por detección de duplicado idéntico (SHA-256).</td>
        </tr>
        <tr>
            <td><code>FAILED</code></td>
            <td>Fallo en el pipeline; incluye mensaje de error en la columna <code>error_message</code>.</td>
        </tr>
    </tbody>
</table>

<div class="callout callout-info" style="margin-top: 15px;">
    <div class="callout-title">Resumen de Integración para Desarrolladores</div>
    Flujo recomendado para sistemas externos (ERP / Portales Web):
    <ol style="margin: 4px 0 0 16px; padding: 0;">
        <li>Cargar documentos con <code>POST /api/v1/extract</code> pasando el <code>numero_poliza</code> para auto-agruparlos en un sobre.</li>
        <li>Consultar el estado del sobre y sus partes mediante <code>GET /api/v1/policies/envelopes/by-number/{numero_poliza}</code>.</li>
        <li>Si ocurre un error de carga o se requiere reiniciar la póliza, ejecutar <code>DELETE /api/v1/policies/envelopes/{envelope_id}?delete_files=true</code>.</li>
        <li>Consultar coberturas mediante <code>POST /api/v1/query</code> en lenguaje natural.</li>
    </ol>
</div>

</body>
</html>
"""


def generate_pdf() -> Path:
    """Genera el archivo HTML y compila el PDF mediante Microsoft Edge."""
    base_dir = Path(__file__).resolve().parents[1]
    docs_dir = base_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    html_path = docs_dir / "DocEngine_Especificacion_Tecnica_APIs.html"
    pdf_path = docs_dir / "DocEngine_Especificacion_Tecnica_APIs.pdf"

    html_content = build_html_content()
    html_path.write_text(html_content, encoding="utf-8")
    print(f"HTML generado en: {html_path}")

    edge_paths = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    edge_exe = next((p for p in edge_paths if p.exists()), None)
    if not edge_exe:
        raise FileNotFoundError("No se encontró el ejecutable de Microsoft Edge.")

    cmd = [
        str(edge_exe),
        "--headless",
        "--disable-gpu",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={pdf_path.resolve()}",
        str(html_path.resolve()),
    ]

    print("Compilando PDF con Edge Headless...")
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    print(f"PDF generado exitosamente en: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    generate_pdf()
