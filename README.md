# DocEngine — Motor de Extracción Documental

**Motor de extracción de alta fidelidad para PDFs de pólizas de seguros.**  
Construido sobre [Docling (IBM Research)](https://github.com/docling-project/docling).  
Produce Markdown estructurado y optimizado para pipelines RAG / LLM.

---

## Índice

1. [Características](#características)
2. [Arquitectura](#arquitectura)
3. [Requisitos](#requisitos)
4. [Instalación en Windows](#instalación-en-windows)
5. [Instalación en Rocky Linux 8.10](#instalación-en-rocky-linux-810)
6. [Configuración](#configuración)
7. [Uso — CLI](#uso--cli)
8. [Uso — API REST](#uso--api-rest)
9. [Despliegue con Docker](#despliegue-con-docker)
10. [Despliegue en Producción (Rocky Linux + Nginx)](#despliegue-en-producción-rocky-linux--nginx)
11. [Validación de Fidelidad](#validación-de-fidelidad)
12. [Tests](#tests)
13. [Estructura del Proyecto](#estructura-del-proyecto)
14. [OCR — Fase 2](#ocr--fase-2)

---

## Características

| Capacidad | Estado |
|-----------|--------|
| Extracción PDF con texto embebido | ✅ Activo |
| Análisis de Layout y Reading Order | ✅ Activo (Docling) |
| Detección de tablas (TableFormer ACCURATE) | ✅ Activo |
| Detección de tablas sin bordes / multipágina | ✅ Activo |
| Detección multi-columna | ✅ Activo |
| Eliminación de headers/footers repetitivos | ✅ Activo |
| Export Markdown de alta fidelidad | ✅ Activo |
| Export JSON estructurado | ✅ Activo |
| SHA-256, metadatos, reporte de extracción | ✅ Activo |
| API REST (FastAPI) | ✅ Activo |
| CLI (Click) | ✅ Activo |
| OCR (Tesseract / EasyOCR / RapidOCR) | 🔄 Fase 2 |

---

## Arquitectura

```
┌────────────────────────────────────────────┐
│  Presentation Layer                         │
│  ├── FastAPI (REST API)                     │
│  └── CLI (Click)                            │
├────────────────────────────────────────────┤
│  Application Layer                          │
│  ├── ExtractionService  (orquestador)       │
│  ├── MarkdownService    (post-procesado)    │
│  ├── MetadataService    (enriquecimiento)   │
│  └── ValidationService  (calidad)          │
├────────────────────────────────────────────┤
│  Domain Layer                               │
│  ├── Models: ExtractionResult, Metadata    │
│  └── Interfaces: IDocumentExtractor,       │
│       IStorageService, IOcrEngine           │
├────────────────────────────────────────────┤
│  Infrastructure Layer                       │
│  ├── DoclingAdapter  ← ÚNICO punto Docling │
│  ├── NullOcrAdapter  (Fase 2: OCR engines) │
│  ├── LocalStorageService                   │
│  └── structlog Logger                      │
└────────────────────────────────────────────┘
```

**Principio clave:** Docling es invocado **únicamente** desde `DoclingAdapter`.
FastAPI y CLI nunca acceden a Docling directamente.

---

## Requisitos

| Componente | Versión mínima |
|-----------|----------------|
| Python | 3.12 |
| Docling | 2.0+ |
| RAM disponible | 4 GB (8 GB recomendado) |
| Disco | 5 GB (modelos Docling) |

---

## Instalación en Windows

```powershell
# 1. Verificar Python 3.12
python --version

# 2. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Copiar configuración
copy .env.example .env

# 5. Verificar instalación
python -c "import docling; print(docling.__version__)"
```

> **Nota:** En la primera ejecución, Docling descargará automáticamente los modelos ML
> (~2-3 GB). Esto ocurre una sola vez y puede tomar varios minutos.

---

## Instalación en Rocky Linux 8.10

```bash
# 1. Instalar Python 3.12 (via EPEL o DNF)
sudo dnf install -y python3.12 python3.12-pip

# 2. Clonar repositorio
git clone <repo-url> docengine
cd docengine

# 3. Crear entorno virtual
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Instalar dependencias del sistema
sudo dnf install -y libgomp

# 5. Instalar dependencias Python
pip install -r requirements.txt

# 6. Copiar configuración
cp .env.example .env
# Editar .env según el entorno
nano .env
```

---

## Configuración

Toda la configuración se realiza via variables de entorno o el archivo `.env`.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `DOCENGINE_ENV` | `development` | Entorno: development / production / test |
| `DOCENGINE_EXTRACTION_DO_OCR` | `false` | OCR (Phase 2) |
| `DOCENGINE_EXTRACTION_TABLE_MODE` | `ACCURATE` | Calidad tablas: ACCURATE / FAST |
| `DOCENGINE_OUTPUT_OUTPUT_DIR` | `./outputs` | Directorio de salida |
| `DOCENGINE_LOG_LEVEL` | `INFO` | Nivel de log |
| `DOCENGINE_LOG_FORMAT` | `console` | Formato: console / json |
| `DOCENGINE_PIPELINE_ARTIFACTS_PATH` | `None` | Modelos pre-descargados (air-gapped) |

Ver [`.env.example`](.env.example) para la referencia completa.

---

## Uso — CLI

```bash
# Activar entorno virtual
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate      # Windows

# Extraer un archivo PDF
python main.py extract samples/poliza.pdf

# Extraer con formato específico
python main.py extract samples/poliza.pdf --format md

# Extraer todos los PDFs de una carpeta
python main.py extract ./documentos/

# Extraer desde URL
python main.py extract https://example.com/poliza.pdf

# Ver versión
python main.py version

# Iniciar servidor API
python main.py serve --host 0.0.0.0 --port 8000
```

**Salida típica:**
```
📄 Extracting file: samples/poliza.pdf

✅ Status          : SUCCESS
   Document ID    : f3a2b1c4-...
   Filename       : poliza.pdf
   Pages          : 24
   Tables found   : 7
   Markdown size  : 45,230 bytes
   Extract time   : 8.34s
   SHA-256        : 4a7f3bc1...
   Output files   :
     [md]       outputs/f3a2b1c4.../poliza.md
     [json]     outputs/f3a2b1c4.../poliza.json
     [metadata] outputs/f3a2b1c4.../metadata.json
     [report]   outputs/f3a2b1c4.../extraction_report.json
```

---

## Uso — API REST

### Iniciar el servidor

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Documentación interactiva

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Endpoints disponibles

```http
POST   /api/v1/extract              Extraer PDF (file upload)
POST   /api/v1/extract/url          Extraer desde URL
POST   /api/v1/extract/folder       Extraer carpeta
GET    /api/v1/health               Estado del servicio
GET    /api/v1/version              Versiones
GET    /api/v1/metrics              Métricas de uso
```

### Ejemplo con curl

```bash
# Extraer un archivo
curl -X POST "http://localhost:8000/api/v1/extract" \
  -H "accept: application/json" \
  -F "file=@samples/poliza.pdf"

# Verificar salud
curl http://localhost:8000/api/v1/health

# Métricas
curl http://localhost:8000/api/v1/metrics
```

### Ejemplo de respuesta

```json
{
  "document_id": "f3a2b1c4-...",
  "status": "success",
  "markdown_preview": "# PÓLIZA DE SEGURO\n\n## CONDICIONES PARTICULARES...",
  "metadata": {
    "filename": "poliza.pdf",
    "sha256": "4a7f3bc1...",
    "page_count": 24,
    "tables_detected": 7,
    "extraction_time_seconds": 8.34,
    "ocr_used": false
  },
  "output_paths": {
    "md": "/app/outputs/f3a2b1c4.../poliza.md"
  }
}
```

---

## Despliegue con Docker

```bash
# Construir imagen
docker build -t docengine:1.0 .

# Ejecutar con Docker Compose
docker compose up -d

# Ver logs
docker compose logs -f docengine

# Parar
docker compose down
```

La API estará disponible en `http://localhost:8000`.

---

## Despliegue en Producción (Rocky Linux + Nginx)

### 1. Configurar el servicio Systemd

```bash
# Crear archivo de servicio
sudo tee /etc/systemd/system/docengine.service << 'EOF'
[Unit]
Description=DocEngine — Motor de Extracción Documental
After=network.target

[Service]
Type=exec
User=docengine
WorkingDirectory=/opt/docengine
Environment="DOCENGINE_ENV=production"
Environment="DOCENGINE_LOG_FORMAT=json"
ExecStart=/opt/docengine/.venv/bin/uvicorn main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2 \
    --log-level info
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Habilitar y arrancar
sudo systemctl daemon-reload
sudo systemctl enable docengine
sudo systemctl start docengine
sudo systemctl status docengine
```

### 2. Configurar Nginx como reverse proxy

```nginx
# /etc/nginx/conf.d/docengine.conf
server {
    listen 80;
    server_name docengine.tudominio.com;

    client_max_body_size 250M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_connect_timeout 30s;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Validación de Fidelidad

```bash
# Validar un archivo Markdown extraído
python scripts/validate_fidelity.py outputs/<doc_id>/poliza.md

# Con metadatos (para check de densidad)
python scripts/validate_fidelity.py outputs/<doc_id>/poliza.md \
    --metadata outputs/<doc_id>/metadata.json

# Comparar contra referencia
python scripts/validate_fidelity.py outputs/<doc_id>/poliza.md \
    --reference samples/poliza_reference.md

# Salida JSON para integración con CI
python scripts/validate_fidelity.py outputs/<doc_id>/poliza.md --json-output
```

**Checks ejecutados:**

| Check | Descripción |
|-------|-------------|
| `content_not_empty` | Documento con contenido sustancial |
| `heading_structure` | Al menos un encabezado detectado |
| `no_column_mixing` | Sin mezcla de columnas (< 30% líneas cortas) |
| `table_integrity` | Tablas con columnas consistentes |
| `no_duplicate_content` | Sin repetición excesiva de líneas |
| `content_density` | Mínimo de caracteres por página |
| `reference_comparison` | F1 score vs. referencia (si se provee) |

---

## Tests

```bash
# Instalar dependencias de desarrollo
pip install -r requirements-dev.txt

# Tests unitarios (no requieren PDF)
pytest tests/unit/ -v

# Tests con cobertura
pytest tests/unit/ -v --cov=app --cov-report=term-missing

# Tests de integración (requiere samples/test_poliza.pdf)
pytest tests/integration/ -v -m integration

# Todos los tests
pytest -v
```

---

## Estructura del Proyecto

```
docengine/
├── app/
│   ├── config/settings.py          # Configuración Pydantic v2
│   ├── domain/
│   │   ├── models/                 # ExtractionResult, DocumentMetadata
│   │   └── interfaces/             # IDocumentExtractor, IStorageService, IOcrEngine
│   ├── application/                # ExtractionService, MarkdownService, ...
│   ├── infrastructure/
│   │   ├── adapters/               # DoclingAdapter (ÚNICO punto Docling)
│   │   ├── storage/                # LocalStorageService
│   │   └── logging/                # structlog configurado
│   ├── api/                        # FastAPI app + endpoints
│   └── cli/                        # Click commands
├── tests/
│   ├── unit/                       # Tests sin dependencias externas
│   └── integration/                # Tests con Docling real
├── scripts/validate_fidelity.py    # Validación de calidad Markdown
├── samples/                        # PDFs de prueba (no incluidos)
├── outputs/                        # Resultados extraídos (gitignored)
├── main.py                         # Entry point (API + CLI)
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## OCR — Fase 2

La infraestructura OCR está **completamente implementada** y lista para activación.

### Para activar OCR en Fase 2:

1. Instalar el motor elegido:
   ```bash
   pip install "docling[easyocr]"     # EasyOCR
   pip install "docling[tesseract]"   # Tesseract
   ```

2. Editar `.env`:
   ```env
   DOCENGINE_EXTRACTION_DO_OCR=true
   DOCENGINE_OCR_ENGINE=easyocr
   DOCENGINE_OCR_LANGUAGES=["es","en"]
   ```

3. **Sin cambios de código.** El adaptador OCR se activa automáticamente.

### Motores soportados (Fase 2)

| Motor | Extra | Recomendado para |
|-------|-------|-----------------|
| EasyOCR | `docling[easyocr]` | Facilidad de instalación |
| Tesseract | `docling[tesseract]` + binario | Control máximo |
| RapidOCR | `docling[rapidocr]` | Alto rendimiento |

---

## Licencia

MIT License — Ver LICENSE para detalles.
