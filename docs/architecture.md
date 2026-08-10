# DocEngine — Architecture

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                            │
│                                                                  │
│  ┌─────────────────────────┐  ┌──────────────────────────────┐  │
│  │   FastAPI (REST API)    │  │      CLI (Click)             │  │
│  │  app/api/               │  │  app/cli/commands.py         │  │
│  │  - POST /extract        │  │  - extract <source>          │  │
│  │  - POST /extract/url    │  │  - extract --format md       │  │
│  │  - POST /extract/folder │  │  - version                   │  │
│  │  - GET /health          │  │                              │  │
│  │  - GET /version         │  │                              │  │
│  │  - GET /metrics         │  │                              │  │
│  └────────────┬────────────┘  └──────────────┬───────────────┘  │
└───────────────┼──────────────────────────────┼──────────────────┘
                │  ExtractionService            │
                ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ExtractionService  (orchestrator)                      │    │
│  │  app/application/extraction_service.py                  │    │
│  │                                                          │    │
│  │   ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │    │
│  │   │MarkdownSvc   │  │MetadataSvc   │  │Validation   │  │    │
│  │   │Post-process  │  │Enrich meta   │  │Svc Quality  │  │    │
│  │   └──────────────┘  └──────────────┘  └─────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                │  IDocumentExtractor
                ▼  IStorageService
┌─────────────────────────────────────────────────────────────────┐
│                      DOMAIN LAYER                                │
│                                                                  │
│  Models:              Interfaces:                                │
│  - ExtractionResult   - IDocumentExtractor (ABC)                │
│  - DocumentMetadata   - IStorageService (ABC)                   │
│  - ExtractionRequest  - IOcrEngine (ABC)                        │
│  - ExtractionStatus                                              │
└─────────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   INFRASTRUCTURE LAYER                           │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  DoclingAdapter  │  │LocalStorage  │  │  structlog      │   │
│  │  ← ONLY place    │  │Service       │  │  Logger         │   │
│  │  Docling is used │  │outputs/      │  │                 │   │
│  │                  │  │{doc_id}/     │  │                 │   │
│  │  NullOcrAdapter  │  │  .md         │  │                 │   │
│  │  (Phase 2: OCR)  │  │  .json       │  │                 │   │
│  └──────────────────┘  │  metadata    │  └─────────────────┘   │
│                         │  report      │                        │
│                         └──────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

## Docling Pipeline Configuration

```
DocumentConverter
    └── PdfFormatOption
            └── PdfPipelineOptions
                    ├── do_ocr = False          # Phase 1
                    ├── do_table_structure = True
                    ├── table_structure_options
                    │       ├── mode = TableFormerMode.ACCURATE
                    │       └── do_cell_matching = True
                    └── generate_picture_images = False
```

## Extraction Pipeline Flow

```
ExtractionRequest
        │
        ▼
DoclingAdapter.extract()
        │  DocumentConverter.convert()
        │  → ConversionResult
        │
        ▼
ExtractionResult (raw)
        │
        ▼
MarkdownService.post_process()
        │  - Detect repeated headers/footers
        │  - Remove page numbers
        │  - Normalize whitespace
        │
        ▼
MetadataService.enrich_metadata()
        │  - Update headers_removed, footers_removed
        │  - Update markdown_size_bytes
        │
        ▼
ValidationService.validate_result()
        │  - Check content density
        │  - Check heading presence
        │  - Check table integrity
        │  → Append warnings to metadata
        │
        ▼
LocalStorageService.save_result()
        │  - Write {stem}.md
        │  - Write {stem}.json
        │  - Write metadata.json
        │  - Write extraction_report.json
        │
        ▼
ExtractionResult (complete, with output_paths)
```

## Output Directory Structure

```
outputs/
└── {document_id}/
    ├── {filename}.md            ← Primary output for RAG
    ├── {filename}.json          ← Full Docling document structure
    ├── metadata.json            ← Extraction metadata
    └── extraction_report.json  ← Quality report
```

## Configuration Class Hierarchy

```
AppSettings
    ├── ExtractionConfig    (DOCENGINE_EXTRACTION_*)
    ├── PipelineConfig      (DOCENGINE_PIPELINE_*)
    ├── OutputConfig        (DOCENGINE_OUTPUT_*)
    ├── LoggingConfig       (DOCENGINE_LOG_*)
    ├── OCRConfig           (DOCENGINE_OCR_*)
    ├── PerformanceConfig   (DOCENGINE_PERF_*)
    └── MarkdownConfig      (DOCENGINE_MD_*)
```
