-- DocEngine — Migration 006: Catálogos Maestros (Aseguradoras, Ramos, Tipos de Documento)
-- Target Database: PostgreSQL 15+ with pgvector extension

-- 1. Modificar policies.company_sigla y tipo_documento
ALTER TABLE policies ALTER COLUMN company_sigla TYPE VARCHAR(20);
ALTER TABLE policies DROP CONSTRAINT IF EXISTS policies_company_sigla_check;
ALTER TABLE policies ALTER COLUMN tipo_documento TYPE VARCHAR(150);

-- 2. Tabla Maestra de Aseguradoras
CREATE TABLE IF NOT EXISTS cat_aseguradoras (
    id INT PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    sigla VARCHAR(20) NOT NULL UNIQUE,
    sigla_anterior VARCHAR(10),
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Tabla Maestra de Tipos de Documento
CREATE TABLE IF NOT EXISTS cat_tipos_documento (
    id INT PRIMARY KEY,
    documento VARCHAR(255) NOT NULL,
    codigo_normalizado VARCHAR(50),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Tabla Maestra de Ramos de Seguros (Normativa APS)
CREATE TABLE IF NOT EXISTS cat_ramos (
    codigo INT PRIMARY KEY,
    tipo VARCHAR(100) NOT NULL,
    ramo VARCHAR(255) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Campos aditivos opcionales en policy_envelopes y policies
ALTER TABLE policy_envelopes
    ADD COLUMN IF NOT EXISTS id_aseguradora INT REFERENCES cat_aseguradoras(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS codigo_ramo INT REFERENCES cat_ramos(codigo) ON DELETE SET NULL;

ALTER TABLE policies
    ADD COLUMN IF NOT EXISTS id_documento INT REFERENCES cat_tipos_documento(id) ON DELETE SET NULL;

-- 6. Población de Catálogo de Aseguradoras
INSERT INTO cat_aseguradoras (id, nombre, sigla, sigla_anterior) VALUES
(1, 'LA BOLIVIANA CIACRUZ DE SEGUROS Y REASEGUROS', 'LBC', 'LBC'),
(2, 'CREDINFORM INTERNATIONAL S.A.', 'CRE', 'CRI'),
(3, 'SEGUROS ILLIMANI', 'ILLI', NULL),
(4, 'ALIANZA CIA DE SEGUROS Y REASEGUROS SA.', 'ALI-SEG', 'ALI'),
(5, 'BISA SEGUROS Y REASEGUROS', 'BISA', 'BIS'),
(8, 'FORTALEZA COMPAÑÍA DE SEGUROS Y REASEGUROS', 'FORT', 'FOR'),
(9, 'NACIONAL SEGUROS PATRIMONIALES Y FIANZAS S.A.', 'NSPF', 'NPF'),
(10, 'BUPA ISURANCE S.A.', 'DHI', NULL),
(11, 'LA VITALICIA DE SEGUROS Y REASEGUROS', 'VIT', 'VIT'),
(12, 'LA BOLIVIANA CIACRUZ SEGUROS PERSONALES', 'LBC-P', 'LBP'),
(14, 'NACIONAL SEGUROS VIDA Y SALUD S.A.', 'NAL-VIDA', 'NVS'),
(15, 'ALIANZA VIDA SEGUROS Y REASEGUROS S.A.', 'ALI-VIDA', 'ALV'),
(16, 'CREDISEGURO S.A. SEGUROS PERSONALES', 'CRESEG', 'CRP'),
(17, 'SEGUROS Y REASEGUROS PERSONALES UNIVIDA S.A.', 'UNIVIDA', 'UNI'),
(18, 'COMPAÑÍA DE SEGUROS DE VIDA FORTALEZA S.A.', 'FORT-P', 'FOV'),
(19, 'UNIBIENES SEGUROS Y REASEGUROS', 'UNIBIENES', 'UBI'),
(21, 'CREDISEGURO S.A. SEGUROS GENERALES', 'CRDI-G', 'CRG'),
(22, 'MERCANTIL SANTA CRUZ SEGUROS Y REASEGUROS GENERALES S.A.', 'MSC', 'MSC')
ON CONFLICT (id) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    sigla = EXCLUDED.sigla,
    sigla_anterior = EXCLUDED.sigla_anterior;

-- 7. Población de Tipos de Documento
INSERT INTO cat_tipos_documento (id, documento, codigo_normalizado) VALUES
(1, 'Condicionado General', 'CONDICIONADO_GENERAL'),
(2, 'Condicionado(s) Particular(es) por Riesgo o Ramo o Anexo de Liquidación Anual', 'CONDICIONADO_PARTICULAR'),
(3, 'Liquidación de Cobranzas/Plan de Pagos (CLIENTE)', 'LIQUIDACION_PAGOS'),
(4, 'Clausulas y/o anexos', 'ANEXO'),
(5, 'Certificados', 'CERTIFICADO'),
(6, 'Anexo, Certificado, Aplicación y Liquidación de cobranzas (Si corresponde)', 'ANEXO_LIQUIDACION')
ON CONFLICT (id) DO UPDATE SET
    documento = EXCLUDED.documento,
    codigo_normalizado = EXCLUDED.codigo_normalizado;

-- 8. Población de Ramos (APS)
INSERT INTO cat_ramos (codigo, tipo, ramo) VALUES
(9101, 'SEGUROS GENERALES', 'Incendio y Aliados'),
(9102, 'SEGUROS GENERALES', 'Robo'),
(9103, 'SEGUROS GENERALES', 'Transportes'),
(9104, 'SEGUROS GENERALES', 'Naves o Embarcaciones'),
(9105, 'SEGUROS GENERALES', 'Automotores'),
(9106, 'SEGUROS GENERALES', 'Aeronavegación'),
(9107, 'SEGUROS GENERALES', 'Ramos Técnicos'),
(9108, 'SEGUROS GENERALES', 'Responsabilidad Civil'),
(9109, 'SEGUROS GENERALES', 'Riesgos varios y misceláneos'),
(9110, 'SEGUROS GENERALES', 'Agropecuarios'),
(9111, 'SEGUROS GENERALES', 'Salud o enfermedad'),
(9112, 'SEGUROS GENERALES', 'Accidentes personales'),
(9127, 'SEGUROS GENERALES', 'Seguro comprensivo para deshonestidad destrucción y desaparición (3-D)'),
(9212, 'SEGUROS PERSONAS', 'Accidentes personales'),
(9221, 'SEGURO DE FIANZAS', 'Seriedad de Propuesta'),
(9222, 'SEGURO DE FIANZAS', 'Cumplimiento de obra'),
(9223, 'SEGURO DE FIANZAS', 'Buena ejecución de obra'),
(9224, 'SEGURO DE FIANZAS', 'Cumplimiento de servicios'),
(9225, 'SEGURO DE FIANZAS', 'Cumplimiento de suministros'),
(9226, 'SEGURO DE FIANZAS', 'Inversión de Anticipos'),
(9227, 'SEGURO DE FIANZAS', 'Fidelidad de Empleados'),
(9228, 'SEGURO DE FIANZAS', 'Créditos'),
(9229, 'SEGURO DE FIANZAS', 'Cumplimiento de obligaciones aduaneras'),
(9230, 'SEGURO DE FIANZAS', 'Cumplimiento de obligaciones legales y contractuales de telecomunicaciones'),
(9231, 'SEGURO DE FIANZAS', 'Garantía de funcionamiento de maquinaria y/o equipo para entidades públicas'),
(9341, 'SEGUROS PERSONAS', 'Vida Individual Largo Plazo'),
(9342, 'SEGUROS PERSONAS', 'Vida individual corto plazo'),
(9343, 'SEGUROS PERSONAS', 'Rentas'),
(9344, 'SEGUROS PERSONAS', 'Defunción o sepelio largo plazo'),
(9345, 'SEGUROS PERSONAS', 'Defunción o sepelio corto plazo'),
(9346, 'SEGUROS PERSONAS', 'Vida en grupo corto plazo'),
(9347, 'SEGUROS PERSONAS', 'Salud o enfermedad'),
(9348, 'SEGUROS PERSONAS', 'Desgravamen hipotecario largo plazo'),
(9349, 'SEGUROS PERSONAS', 'Desgravamen hipotecario corto plazo'),
(9350, 'SEGUROS PERSONAS', 'Accidentes personales'),
(9455, 'SEGUROS OBLIGATORIOS', 'Accidentes de tránsito'),
(9456, 'SEGUROS OBLIGATORIOS', 'Accidentes del trabajador'),
(9561, 'SEGUROS PERSONAS', 'Salud o enfermedad'),
(9562, 'SEGUROS PERSONAS', 'Defunción o sepelio')
ON CONFLICT (codigo) DO UPDATE SET
    tipo = EXCLUDED.tipo,
    ramo = EXCLUDED.ramo;

-- 9. Índices de optimización
CREATE INDEX IF NOT EXISTS idx_cat_aseguradoras_sigla ON cat_aseguradoras(sigla);
CREATE INDEX IF NOT EXISTS idx_cat_ramos_tipo ON cat_ramos(tipo);

-- 10. Homologación retroactiva de datos existentes (siglas históricas a nuevas oficiales)
UPDATE policies p
SET company_sigla = c.sigla
FROM cat_aseguradoras c
WHERE p.company_sigla = c.sigla_anterior
  AND c.sigla_anterior IS NOT NULL
  AND c.sigla <> c.sigla_anterior;

UPDATE policy_envelopes pe
SET company_sigla = c.sigla
FROM cat_aseguradoras c
WHERE pe.company_sigla = c.sigla_anterior
  AND c.sigla_anterior IS NOT NULL
  AND c.sigla <> c.sigla_anterior;

-- 11. Vinculación retroactiva de IDs foráneos en envelopes y policies
UPDATE policy_envelopes pe
SET id_aseguradora = c.id
FROM cat_aseguradoras c
WHERE pe.company_sigla = c.sigla
  AND pe.id_aseguradora IS NULL;

UPDATE policies p
SET id_documento = d.id
FROM cat_tipos_documento d
WHERE (UPPER(p.tipo_documento) = UPPER(d.documento) OR UPPER(p.tipo_documento) = UPPER(d.codigo_normalizado))
  AND p.id_documento IS NULL;
