-- DocEngine — Migration 004: Policy Envelopes and Document Classification
-- Target Database: PostgreSQL 15+ with pgvector extension
-- Run AFTER 001_add_rag_tables.sql, 002_parent_child_hybrid_search.sql, and 003_add_processing_stats_table.sql

-- 1. Tabla contenedor lógico de pólizas (agrupa múltiples documentos)
CREATE TABLE IF NOT EXISTS policy_envelopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero_poliza VARCHAR(100) NOT NULL,
    company_sigla VARCHAR(20),
    ramo VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_envelope_poliza_company UNIQUE (numero_poliza, company_sigla)
);

-- 2. Columnas aditivas opcionales en la tabla policies
ALTER TABLE policies
    ADD COLUMN IF NOT EXISTS envelope_id UUID REFERENCES policy_envelopes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS tipo_documento VARCHAR(50);

-- 3. Índices para búsqueda eficiente
CREATE INDEX IF NOT EXISTS idx_policies_envelope_id ON policies(envelope_id);
CREATE INDEX IF NOT EXISTS idx_envelopes_numero_poliza ON policy_envelopes(numero_poliza);
CREATE INDEX IF NOT EXISTS idx_envelopes_company_sigla ON policy_envelopes(company_sigla);
