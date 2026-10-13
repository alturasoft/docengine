-- DocEngine — Migration 005: Add id_cliente to Policy Envelopes and Policies
-- Target Database: PostgreSQL 15+ with pgvector extension
-- Run AFTER 001, 002, 003, and 004 migrations.

-- 1. Agregar id_cliente a policy_envelopes (inicialmente NULLABLE para retrocompatibilidad)
ALTER TABLE policy_envelopes
    ADD COLUMN IF NOT EXISTS id_cliente VARCHAR(50);

-- 2. Índice para consultas rápidas por cliente en policy_envelopes
CREATE INDEX IF NOT EXISTS idx_envelopes_id_cliente ON policy_envelopes(id_cliente);

-- 3. Desnormalizar id_cliente en la tabla policies para consultas de documentos sin necesidad de JOIN
ALTER TABLE policies
    ADD COLUMN IF NOT EXISTS id_cliente VARCHAR(50);

-- 4. Índice para búsquedas directas de documentos por cliente
CREATE INDEX IF NOT EXISTS idx_policies_id_cliente ON policies(id_cliente);
