-- =============================================================================
-- DocEngine — Migración 014: Saneamiento de Jobs Huérfanos Históricos
-- =============================================================================
-- Propósito:
-- Eliminar registros huérfanos en processing_jobs que no corresponden a las pólizas
-- y sobres activos (caídas de workers del 27/10/2026 y pruebas eliminadas), y
-- deduplicar los registros duplicados de pólizas activas originados antes del parche
-- existing_job_id.
--
-- Reactiva inmediatamente el trigger WORM trg_protect_processing_jobs_delete
-- para mantener la inmutabilidad y protección de auditoría en producción.
-- =============================================================================

BEGIN;

-- 1. Desactivar temporalmente el blindaje WORM de DELETE en processing_jobs
ALTER TABLE processing_jobs DISABLE TRIGGER trg_protect_processing_jobs_delete;

-- 2. Eliminar jobs huérfanos sin póliza activa (fallos históricos 27/10 y pruebas eliminadas)
DELETE FROM processing_jobs
WHERE policy_id IS NULL OR policy_id NOT IN (SELECT id FROM policies);

-- 3. Deduplicar jobs de pólizas activas, conservando el job_id vinculado en policy_processing_stats
DELETE FROM processing_jobs pj
WHERE pj.job_id NOT IN (
    SELECT DISTINCT ON (pj2.policy_id) pj2.job_id
    FROM processing_jobs pj2
    LEFT JOIN policy_processing_stats pps ON pps.job_id = pj2.job_id
    ORDER BY pj2.policy_id, (pps.job_id IS NOT NULL) DESC, pj2.created_at ASC
);

-- 4. Reactivar de forma estricta el blindaje WORM de DELETE en processing_jobs
ALTER TABLE processing_jobs ENABLE TRIGGER trg_protect_processing_jobs_delete;

COMMIT;

