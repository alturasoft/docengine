-- DocEngine — RAG Schema Definition with pgvector (1024 dimensions)
-- Target Database: PostgreSQL 15+ with pgvector extension

-- 1. Habilitar la extensión de Vectores
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Tabla principal de Pólizas (Metadatos)
CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name VARCHAR(255) NOT NULL,
    file_hash VARCHAR(64) UNIQUE NOT NULL, -- SHA256 para evitar duplicados
    company_sigla VARCHAR(3) CHECK (
        company_sigla IN (
            'ALI', 'ALV', 'BIS', 'FOV', 'CRI', 'CRG', 'CRP', 
            'FOR', 'LBC', 'LBP', 'VIT', 'MSC', 'NPF', 'NVS', 'UNI', 'UBI'
        )
    ),
    total_pages INT,
    file_size_bytes BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Tabla para el texto completo en Markdown (.md extraído por Docling)
CREATE TABLE IF NOT EXISTS policy_raw_md (
    policy_id UUID PRIMARY KEY REFERENCES policies(id) ON DELETE CASCADE,
    markdown_content TEXT NOT NULL,
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Tabla para los Datos Estructurados (JSONB Atomizado)
CREATE TABLE IF NOT EXISTS policy_structured_data (
    policy_id UUID PRIMARY KEY REFERENCES policies(id) ON DELETE CASCADE,
    data JSONB NOT NULL, -- Coberturas, sumas aseguradas, condicionados
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Tabla para Chunks y Embeddings (Motor RAG)
CREATE TABLE IF NOT EXISTS policy_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id UUID REFERENCES policies(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_content TEXT NOT NULL,
    metadata_json JSONB, -- Número de página, tipo de cláusula/anexo, encabados
    embedding vector(1024), -- 1024 dimensiones para BAAI/bge-m3
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Tabla para Control de Trabajos Asíncronos (Jobs)
CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, COMPLETED, FAILED, SKIPPED
    error_message TEXT,
    policy_id UUID REFERENCES policies(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Creación de Índices para alto rendimiento
CREATE INDEX IF NOT EXISTS idx_policies_file_hash ON policies(file_hash);
CREATE INDEX IF NOT EXISTS idx_policies_company_sigla ON policies(company_sigla);

-- Índice vectorial HNSW para búsquedas semánticas (1024 dims)
CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding 
ON policy_chunks 
USING hnsw (embedding vector_cosine_ops);

-- Índice GIN para realizar búsquedas rápidas dentro del JSONB
CREATE INDEX IF NOT EXISTS idx_structured_data_gin 
ON policy_structured_data 
USING gin (data);
