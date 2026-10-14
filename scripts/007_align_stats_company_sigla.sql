-- DocEngine — Migration 007: Alinear company_sigla en policy_processing_stats con cat_aseguradoras
-- Target Database: PostgreSQL 15+ with pgvector extension
-- Permite siglas oficiales de cat_aseguradoras (ej. CRE, BISA, FORT, UNIBIENES) sin restricciones obsoletas.

ALTER TABLE policy_processing_stats ALTER COLUMN company_sigla TYPE VARCHAR(20);
ALTER TABLE policy_processing_stats DROP CONSTRAINT IF EXISTS policy_processing_stats_company_sigla_check;
