-- DocEngine: Migración 012 - Índices de búsqueda de clientes por nombre
-- Permite búsquedas rápidas ILIKE y LOWER en nombre_cliente

CREATE INDEX IF NOT EXISTS idx_envelopes_nombre_cliente_lower 
ON policy_envelopes (LOWER(nombre_cliente));

CREATE INDEX IF NOT EXISTS idx_policies_nombre_cliente_lower 
ON policies (LOWER(nombre_cliente));
