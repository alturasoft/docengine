-- =============================================================================
-- DocEngine — Migración 015: Saneamiento de Métricas y Registros Sintéticos de Pruebas
-- =============================================================================
-- Propósito:
-- Eliminar registros sintéticos generados durante las pruebas unitarias/integración
-- (poliza_inmutable_*.pdf, TEST-IMM-*) que quedaron persistidos en audit_metrics_ledger,
-- policy_processing_stats y policy_envelopes debido a la protección WORM.
--
-- Reactiva inmediatamente los triggers de protección WORM para mantener la
-- inmutabilidad en producción.
-- =============================================================================

BEGIN;

-- 1. Desactivar temporalmente los triggers WORM de DELETE
ALTER TABLE audit_metrics_ledger DISABLE TRIGGER trg_protect_audit_ledger_delete;
ALTER TABLE policy_processing_stats DISABLE TRIGGER trg_protect_processing_stats_delete;
ALTER TABLE processing_jobs DISABLE TRIGGER trg_protect_processing_jobs_delete;

-- 2. Eliminar eventos de prueba en audit_metrics_ledger
DELETE FROM audit_metrics_ledger
WHERE numero_poliza LIKE 'TEST-IMM-%'
   OR file_name LIKE 'poliza_inmutable_%'
   OR id_cliente = '99887766'
   OR nombre_cliente = 'Cliente Prueba Inmutable';

-- 3. Eliminar filas de prueba en policy_processing_stats
DELETE FROM policy_processing_stats
WHERE policy_number LIKE 'TEST-IMM-%'
   OR file_name LIKE 'poliza_inmutable_%'
   OR file_hash LIKE 'hash_imm_%'
   OR id_cliente = '99887766';

-- 4. Eliminar sobres de prueba huérfanos en policy_envelopes
DELETE FROM policy_envelopes
WHERE numero_poliza LIKE 'TEST-IMM-%'
   OR id_cliente = '99887766'
   OR nombre_cliente = 'Cliente Prueba Inmutable';

-- 5. Eliminar cualquier job de prueba remanente en processing_jobs
DELETE FROM processing_jobs
WHERE file_name LIKE 'poliza_inmutable_%';

-- 6. Reactivar estrictamente los triggers WORM de protección
ALTER TABLE audit_metrics_ledger ENABLE TRIGGER trg_protect_audit_ledger_delete;
ALTER TABLE policy_processing_stats ENABLE TRIGGER trg_protect_processing_stats_delete;
ALTER TABLE processing_jobs ENABLE TRIGGER trg_protect_processing_jobs_delete;

COMMIT;
