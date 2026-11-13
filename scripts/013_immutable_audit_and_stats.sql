-- DocEngine — Migration 013: Auditoría Inmutable y Telemetría Permanente (WORM / Append-Only)
-- Target Database: PostgreSQL 15+ with pgvector extension
-- Garantiza que las métricas de páginas procesadas, documentos, sobres, tablas y costos
-- nunca se pierdan por borrado en cascada ni puedan ser eliminadas o truncadas en producción.

-- =============================================================================
-- 1. EXTENSIÓN Y DESACOPLAMIENTO DE policy_processing_stats (SIN ON DELETE CASCADE)
-- =============================================================================

-- 1.1 Añadir columnas aditivas para conservar identidad completa del documento y sobre
ALTER TABLE policy_processing_stats
    ADD COLUMN IF NOT EXISTS stat_id UUID DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS envelope_id UUID,
    ADD COLUMN IF NOT EXISTS file_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS tipo_documento VARCHAR(150),
    ADD COLUMN IF NOT EXISTS id_cliente VARCHAR(50);

-- Asegurar que todos los registros existentes tengan un stat_id único
UPDATE policy_processing_stats
SET stat_id = gen_random_uuid()
WHERE stat_id IS NULL;

-- Retro-poblar metadatos desde policies para registros históricos existentes
UPDATE policy_processing_stats pps
SET
    envelope_id = COALESCE(pps.envelope_id, p.envelope_id),
    file_name = COALESCE(pps.file_name, p.file_name),
    file_hash = COALESCE(pps.file_hash, p.file_hash),
    tipo_documento = COALESCE(pps.tipo_documento, p.tipo_documento),
    id_cliente = COALESCE(pps.id_cliente, p.id_cliente),
    company_sigla = COALESCE(pps.company_sigla, p.company_sigla)
FROM policies p
WHERE pps.policy_id = p.id;

-- 1.2 Migrar clave primaria de policy_id a stat_id y eliminar ON DELETE CASCADE
DO $$
BEGIN
    -- Eliminar FK con ON DELETE CASCADE si existe
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_processing_stats_policy_id_fkey'
    ) THEN
        ALTER TABLE policy_processing_stats
            DROP CONSTRAINT policy_processing_stats_policy_id_fkey;
    END IF;

    -- Cambiar PK de (policy_id) a (stat_id) para permitir que policy_id sea NULLABLE
    -- cuando un documento operativo se reemplace, y permitir historial de reprocesos
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_processing_stats_pkey'
          AND pg_get_constraintdef(oid) LIKE '%(policy_id)%'
    ) THEN
        ALTER TABLE policy_processing_stats
            DROP CONSTRAINT policy_processing_stats_pkey;
        ALTER TABLE policy_processing_stats
            ALTER COLUMN stat_id SET NOT NULL;
        ALTER TABLE policy_processing_stats
            ADD CONSTRAINT policy_processing_stats_pkey PRIMARY KEY (stat_id);
    END IF;

    -- Permitir que policy_id sea NULL cuando se elimine el registro operativo de policies
    ALTER TABLE policy_processing_stats
        ALTER COLUMN policy_id DROP NOT NULL;

    -- Recrear FK con ON DELETE SET NULL (nunca borra la fila de estadísticas)
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_processing_stats_policy_id_set_null_fkey'
    ) THEN
        ALTER TABLE policy_processing_stats
            ADD CONSTRAINT policy_processing_stats_policy_id_set_null_fkey
            FOREIGN KEY (policy_id) REFERENCES policies(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_stats_policy_id ON policy_processing_stats(policy_id);
CREATE INDEX IF NOT EXISTS idx_stats_envelope_id ON policy_processing_stats(envelope_id);
CREATE INDEX IF NOT EXISTS idx_stats_file_hash ON policy_processing_stats(file_hash);

-- =============================================================================
-- 2. LIBRO MAYOR INMUTABLE DE AUDITORÍA Y MÉTRICAS (audit_metrics_ledger)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_metrics_ledger (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(50) NOT NULL CHECK (
        event_type IN (
            'DOCUMENT_EXTRACTED',
            'DOCUMENT_SKIPPED_DUPLICATE',
            'DOCUMENT_EXTRACTION_FAILED',
            'ENVELOPE_CREATED',
            'ENVELOPE_UPDATED',
            'DOCUMENT_DELETED',
            'ENVELOPE_DELETED'
        )
    ),
    policy_id UUID,
    envelope_id UUID,
    job_id UUID,
    numero_poliza VARCHAR(100),
    company_sigla VARCHAR(20),
    ramo VARCHAR(200),
    tipo_documento VARCHAR(150),
    id_cliente VARCHAR(50),
    nombre_cliente VARCHAR(255),
    file_name VARCHAR(255),
    file_hash VARCHAR(64),
    pages_count INT NOT NULL DEFAULT 0,
    tables_count INT NOT NULL DEFAULT 0,
    chunks_count INT NOT NULL DEFAULT 0,
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    duration_seconds NUMERIC(10,3) NOT NULL DEFAULT 0.000,
    openai_tokens INT NOT NULL DEFAULT 0,
    openai_cost_usd NUMERIC(10,5) NOT NULL DEFAULT 0.00000,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_ledger_event_type ON audit_metrics_ledger(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_ledger_company_sigla ON audit_metrics_ledger(company_sigla);
CREATE INDEX IF NOT EXISTS idx_audit_ledger_envelope_id ON audit_metrics_ledger(envelope_id);
CREATE INDEX IF NOT EXISTS idx_audit_ledger_policy_id ON audit_metrics_ledger(policy_id);
CREATE INDEX IF NOT EXISTS idx_audit_ledger_created_at ON audit_metrics_ledger(created_at);

-- 2.1 Poblado inicial idempotente de línea base histórica (Sobres existentes)
INSERT INTO audit_metrics_ledger (
    event_type, envelope_id, numero_poliza, company_sigla, ramo,
    id_cliente, nombre_cliente, metadata, created_at
)
SELECT
    'ENVELOPE_CREATED',
    pe.id,
    pe.numero_poliza,
    pe.company_sigla,
    pe.ramo,
    pe.id_cliente,
    pe.nombre_cliente,
    jsonb_build_object('retrofilled_baseline', true),
    COALESCE(pe.created_at, CURRENT_TIMESTAMP)
FROM policy_envelopes pe
WHERE NOT EXISTS (
    SELECT 1 FROM audit_metrics_ledger aml
    WHERE aml.envelope_id = pe.id AND aml.event_type = 'ENVELOPE_CREATED'
);

-- 2.2 Poblado inicial idempotente de línea base histórica (Documentos extraídos existentes)
INSERT INTO audit_metrics_ledger (
    event_type, policy_id, envelope_id, job_id, numero_poliza, company_sigla,
    ramo, tipo_documento, id_cliente, nombre_cliente, file_name, file_hash,
    pages_count, tables_count, chunks_count, file_size_bytes, duration_seconds,
    openai_tokens, openai_cost_usd, metadata, created_at
)
SELECT
    'DOCUMENT_EXTRACTED',
    p.id,
    p.envelope_id,
    pps.job_id,
    COALESCE(pps.policy_number, pe.numero_poliza),
    COALESCE(p.company_sigla, pps.company_sigla),
    pe.ramo,
    p.tipo_documento,
    COALESCE(p.id_cliente, pe.id_cliente),
    COALESCE(p.nombre_cliente, pe.nombre_cliente),
    p.file_name,
    p.file_hash,
    COALESCE(pps.total_pages, p.total_pages, 0),
    COALESCE(pps.tables_detected, 0),
    COALESCE(pps.total_chunks, 0),
    COALESCE(p.file_size_bytes, 0),
    COALESCE(pps.total_pipeline_time_seconds, pps.extraction_time_seconds, 0.000),
    COALESCE(pps.openai_total_tokens, 0),
    COALESCE(pps.openai_estimated_cost_usd, 0.00000),
    jsonb_build_object('retrofilled_baseline', true),
    COALESCE(p.created_at, pps.created_at, CURRENT_TIMESTAMP)
FROM policies p
LEFT JOIN policy_processing_stats pps ON pps.policy_id = p.id
LEFT JOIN policy_envelopes pe ON pe.id = p.envelope_id
WHERE NOT EXISTS (
    SELECT 1 FROM audit_metrics_ledger aml
    WHERE aml.policy_id = p.id AND aml.event_type = 'DOCUMENT_EXTRACTED'
);

-- =============================================================================
-- 3. SANEAMIENTO DE JOBS HUÉRFANOS EN processing_jobs
-- =============================================================================

-- Reconciliar jobs antiguos que quedaron en PROCESSING pero cuyo archivo ya fue completado
UPDATE processing_jobs pj
SET
    status = 'COMPLETED',
    policy_id = COALESCE(pj.policy_id, p.id),
    updated_at = CURRENT_TIMESTAMP
FROM policies p
WHERE pj.status = 'PROCESSING'
  AND pj.file_name = p.file_name;

-- Marcar como FAILED jobs huérfanos antiguos (> 2 horas en PROCESSING sin póliza asociada)
UPDATE processing_jobs
SET
    status = 'FAILED',
    error_message = COALESCE(error_message, 'Job huérfano reconciliado durante migración de auditoría'),
    updated_at = CURRENT_TIMESTAMP
WHERE status = 'PROCESSING'
  AND created_at < (CURRENT_TIMESTAMP - INTERVAL '2 hours');

-- =============================================================================
-- 4. BLINDAJE WORM A NIVEL DE MOTOR POSTGRESQL (PROHIBICIÓN DE DELETE / TRUNCATE)
-- =============================================================================

CREATE OR REPLACE FUNCTION prevent_audit_stats_deletion()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '[PRODUCCION-INMUTABLE] Operacion % bloqueada en la tabla %. Los registros de estadisticas, seguimiento y auditoria son permanentes y no pueden ser eliminados ni reseteados.',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = '42501'; -- insufficient_privilege
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Triggers sobre policy_processing_stats
DROP TRIGGER IF EXISTS trg_protect_processing_stats_delete ON policy_processing_stats;
CREATE TRIGGER trg_protect_processing_stats_delete
    BEFORE DELETE ON policy_processing_stats
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_stats_deletion();

DROP TRIGGER IF EXISTS trg_protect_processing_stats_truncate ON policy_processing_stats;
CREATE TRIGGER trg_protect_processing_stats_truncate
    BEFORE TRUNCATE ON policy_processing_stats
    FOR EACH STATEMENT
    EXECUTE FUNCTION prevent_audit_stats_deletion();

-- Triggers sobre audit_metrics_ledger
DROP TRIGGER IF EXISTS trg_protect_audit_ledger_delete ON audit_metrics_ledger;
CREATE TRIGGER trg_protect_audit_ledger_delete
    BEFORE DELETE ON audit_metrics_ledger
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_stats_deletion();

DROP TRIGGER IF EXISTS trg_protect_audit_ledger_truncate ON audit_metrics_ledger;
CREATE TRIGGER trg_protect_audit_ledger_truncate
    BEFORE TRUNCATE ON audit_metrics_ledger
    FOR EACH STATEMENT
    EXECUTE FUNCTION prevent_audit_stats_deletion();

-- Triggers sobre processing_jobs
DROP TRIGGER IF EXISTS trg_protect_processing_jobs_delete ON processing_jobs;
CREATE TRIGGER trg_protect_processing_jobs_delete
    BEFORE DELETE ON processing_jobs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_stats_deletion();

DROP TRIGGER IF EXISTS trg_protect_processing_jobs_truncate ON processing_jobs;
CREATE TRIGGER trg_protect_processing_jobs_truncate
    BEFORE TRUNCATE ON processing_jobs
    FOR EACH STATEMENT
    EXECUTE FUNCTION prevent_audit_stats_deletion();

