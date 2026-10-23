-- DocEngine — Migration 008: Policy Section Summaries (Policy Map)
-- Target Database: PostgreSQL 15+
-- Aditivo: Almacena el mapa temático y resúmenes por sección/anexo de pólizas
-- para alimentar el contexto macro de pólizas GRANDES en RAG sin saturar tokens.

CREATE TABLE IF NOT EXISTS policy_section_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id UUID REFERENCES policies(id) ON DELETE CASCADE,
    envelope_id UUID REFERENCES policy_envelopes(id) ON DELETE CASCADE,
    section_index INT NOT NULL DEFAULT 0,
    section_title VARCHAR(300) NOT NULL,
    tipo_documento VARCHAR(100),
    source_file VARCHAR(300),
    chunk_start INT DEFAULT 0,
    chunk_end INT DEFAULT 0,
    summary_text TEXT NOT NULL,
    key_topics JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pss_policy_id ON policy_section_summaries(policy_id);
CREATE INDEX IF NOT EXISTS idx_pss_envelope_id ON policy_section_summaries(envelope_id);
