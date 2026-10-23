-- DocEngine — Migration 011: Add nombre_cliente to Policy Envelopes and Policies
-- Target Database: PostgreSQL 15+ with pgvector extension
-- Run AFTER 001 through 010 migrations.

-- 1. Agregar nombre_cliente a policy_envelopes (NULLABLE para retrocompatibilidad)
ALTER TABLE policy_envelopes
    ADD COLUMN IF NOT EXISTS nombre_cliente VARCHAR(255);

-- 2. Índice para consultas rápidas por nombre en policy_envelopes
CREATE INDEX IF NOT EXISTS idx_envelopes_nombre_cliente ON policy_envelopes(nombre_cliente);

-- 3. Desnormalizar nombre_cliente en la tabla policies para consultas de documentos sin necesidad de JOIN
ALTER TABLE policies
    ADD COLUMN IF NOT EXISTS nombre_cliente VARCHAR(255);

-- 4. Índice para búsquedas directas de documentos por nombre de cliente
CREATE INDEX IF NOT EXISTS idx_policies_nombre_cliente ON policies(nombre_cliente);
