-- DocEngine — Migration 010: Policy Insured Persons (Pólizas Colectivas de Personas)
-- Target Database: PostgreSQL 15+
-- [ADITIVO]: Almacena de forma estructurada cada asegurado individual de una póliza colectiva / de grupo
-- (Salud, Accidentes Personales, Vida en Grupo).

CREATE TABLE IF NOT EXISTS policy_insured_persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    envelope_id UUID REFERENCES policy_envelopes(id) ON DELETE CASCADE,
    item_number INT NOT NULL DEFAULT 1,
    nombre_completo VARCHAR(255) NOT NULL,
    documento_identidad VARCHAR(50),
    fecha_nacimiento VARCHAR(20),
    edad INT,
    genero VARCHAR(20),
    parentesco_categoria VARCHAR(100) DEFAULT 'TITULAR', -- TITULAR, CONYUGE, HIJO, DEPENDIENTE, EMPLEADO, AFILIADO
    cargo_ocupacion VARCHAR(150),
    suma_asegurada_usd NUMERIC(15,2) DEFAULT 0.00,
    prima_usd NUMERIC(15,2) DEFAULT 0.00,
    raw_metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_policy_person_item UNIQUE (policy_id, item_number)
);

CREATE INDEX IF NOT EXISTS idx_pip_policy_id ON policy_insured_persons(policy_id);
CREATE INDEX IF NOT EXISTS idx_pip_envelope_id ON policy_insured_persons(envelope_id);
CREATE INDEX IF NOT EXISTS idx_pip_documento ON policy_insured_persons(documento_identidad);
CREATE INDEX IF NOT EXISTS idx_pip_nombre ON policy_insured_persons(nombre_completo);
CREATE INDEX IF NOT EXISTS idx_pip_item ON policy_insured_persons(policy_id, item_number);
