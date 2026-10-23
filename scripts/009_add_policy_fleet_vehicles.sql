-- DocEngine — Migration 009: Policy Fleet Vehicles
-- Target Database: PostgreSQL 15+
-- Aditivo: Almacena de forma estructurada cada vehículo de una póliza colectiva / flota.

CREATE TABLE IF NOT EXISTS policy_fleet_vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    envelope_id UUID REFERENCES policy_envelopes(id) ON DELETE CASCADE,
    item_number INT NOT NULL DEFAULT 1,
    tipo_vehiculo VARCHAR(100),
    marca VARCHAR(100),
    modelo VARCHAR(100),
    anio INT,
    placa VARCHAR(50),
    chasis VARCHAR(100),
    motor VARCHAR(100),
    color VARCHAR(50),
    uso VARCHAR(100),
    plaza VARCHAR(100),
    valor_asegurado_usd NUMERIC(15,2) DEFAULT 0.00,
    prima_usd NUMERIC(15,2) DEFAULT 0.00,
    raw_metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_policy_item UNIQUE (policy_id, item_number)
);

CREATE INDEX IF NOT EXISTS idx_pfv_policy_id ON policy_fleet_vehicles(policy_id);
CREATE INDEX IF NOT EXISTS idx_pfv_envelope_id ON policy_fleet_vehicles(envelope_id);
CREATE INDEX IF NOT EXISTS idx_pfv_placa ON policy_fleet_vehicles(placa);
CREATE INDEX IF NOT EXISTS idx_pfv_item ON policy_fleet_vehicles(policy_id, item_number);
