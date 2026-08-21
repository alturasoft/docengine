-- DocEngine — Migration 002: Parent-Child Hybrid Search
-- Adds columns and indexes for Parent-Child Retrieval + Full-Text Search
-- Target: PostgreSQL 15+ with pgvector extension
-- Run AFTER 001_add_rag_tables.sql

-- 1. Columna chunk_id: UUID propio del chunk para referencia directa
--    Columna parent_id: links Child chunks to their Parent chunk
--    Parents have NULL; Children point to their Parent's chunk_id.
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS chunk_id UUID;
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS parent_id UUID;

-- 2. Columna chunk_type: discriminator for parent vs child chunks
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS chunk_type VARCHAR(10)
    DEFAULT 'parent' NOT NULL;

-- 3. Columna tsvector generada automáticamente para Full-Text Search (Spanish)
--    Populated automatically by PostgreSQL on INSERT/UPDATE.
ALTER TABLE policy_chunks ADD COLUMN IF NOT EXISTS content_tsvector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('spanish', coalesce(chunk_content, ''))
    ) STORED;

-- 4. Índice GIN para búsquedas Full-Text sobre content_tsvector
CREATE INDEX IF NOT EXISTS idx_policy_chunks_tsvector
    ON policy_chunks USING gin (content_tsvector);

-- 5. Índice B-tree sobre parent_id para lookups rápidos de Parent desde Child
CREATE INDEX IF NOT EXISTS idx_policy_chunks_parent_id
    ON policy_chunks (parent_id) WHERE parent_id IS NOT NULL;

-- 6. Índice sobre chunk_type para filtrado eficiente parent/child
CREATE INDEX IF NOT EXISTS idx_policy_chunks_type
    ON policy_chunks (chunk_type);

-- 7. Índice sobre chunk_id para resolución directa de Parents
CREATE INDEX IF NOT EXISTS idx_policy_chunks_chunk_id
    ON policy_chunks (chunk_id) WHERE chunk_id IS NOT NULL;
