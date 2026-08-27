-- DocEngine — Migration 003: Processing Stats & Telemetry Table
-- Target Database: PostgreSQL 15+ with pgvector extension
-- Run AFTER 001_add_rag_tables.sql and 002_parent_child_hybrid_search.sql

CREATE TABLE IF NOT EXISTS policy_processing_stats (
    policy_id UUID PRIMARY KEY REFERENCES policies(id) ON DELETE CASCADE,
    job_id UUID REFERENCES processing_jobs(job_id) ON DELETE SET NULL,
    
    -- Identificadores del Negocio
    policy_number VARCHAR(100),
    company_sigla VARCHAR(3) CHECK (
        company_sigla IN (
            'ALI', 'ALV', 'BIS', 'FOV', 'CRI', 'CRG', 'CRP', 
            'FOR', 'LBC', 'LBP', 'VIT', 'MSC', 'NPF', 'NVS', 'UNI', 'UBI'
        )
    ),
    
    -- Tipología de Documento y Extracción
    file_type VARCHAR(20) NOT NULL CHECK (file_type IN ('DIGITAL', 'SCANNED', 'HYBRID', 'UNKNOWN')),
    ocr_applied BOOLEAN DEFAULT FALSE,
    scanned_page_ratio NUMERIC(5,2),        -- % de páginas escaneadas (ej. 0.85 = 85%)
    total_pages INT NOT NULL DEFAULT 0,
    
    -- Tiempos de Ejecución (en segundos con resolución de milisegundos)
    extraction_time_seconds NUMERIC(8,3) NOT NULL,
    time_per_page_seconds NUMERIC(8,3) NOT NULL,
    chunking_time_seconds NUMERIC(8,3) NOT NULL,
    embedding_time_seconds NUMERIC(8,3) NOT NULL,
    openai_time_seconds NUMERIC(8,3) NOT NULL,
    total_pipeline_time_seconds NUMERIC(8,3) NOT NULL,
    
    -- Métricas de Chunking y Jerarquía RAG
    total_chunks INT NOT NULL DEFAULT 0,
    parent_chunks INT DEFAULT 0,
    child_chunks INT DEFAULT 0,
    
    -- Consumo y Costo de Tokens OpenAI (gpt-4o)
    openai_prompt_tokens INT DEFAULT 0,
    openai_completion_tokens INT DEFAULT 0,
    openai_total_tokens INT DEFAULT 0,
    openai_estimated_cost_usd NUMERIC(8,5) DEFAULT 0.00000,
    
    -- Métricas de Contenido y Calidad
    coberturas_extracted_count INT DEFAULT 0,
    tables_detected INT DEFAULT 0,
    memory_peak_mb NUMERIC(8,2),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices para reportes y dashboards
CREATE INDEX IF NOT EXISTS idx_stats_company_sigla ON policy_processing_stats(company_sigla);
CREATE INDEX IF NOT EXISTS idx_stats_file_type ON policy_processing_stats(file_type);
CREATE INDEX IF NOT EXISTS idx_stats_created_at ON policy_processing_stats(created_at);
