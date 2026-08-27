---
sigla: CRI
empresa: CREDINFORM INTERNATIONAL S.A
version: 5
estado: activo
ultima_revision: 2026-08-26
---

## Descripción

Reglas de extracción para pólizas de **Credinform International S.A.**

Completar este skill a medida que se analicen documentos y se identifiquen patrones
propios de esta aseguradora.

## Reglas de Post-Procesado

```yaml
kv_keys:
  - Póliza
  - Poliza
  - Póliza Nro.
  - Póliza Nro
  - Nro. de Póliza
  - Asegurado
  - Tomador
  - Contratante
  - Dirección
  - Direccion
  - Zona
  - Teléfono
  - Telefono
  - E-mail
  - Email
  - Celular
  - Nro. NIT
  - NIT
  - Actividad
  - Distrito

header_patterns:
  # Dirección Oficina Principal / Sucursal 1
  - 'Calacoto Calle Julio Patiño'
  - 'Calle Capitan Ravelo Nro\.?\s*2328'
  - 'OFICINA (PRINCIPAL|CENTRAL)'
  - 'SUCURSAL\s*1'
  # Contactos institucionales (Piloto, Fax, Email, Ciudad)
  - 'Central Piloto:?\s*\(?0?2\)?\s*2775550'
  - 'Fax:\s*\(?591-02\)?\s*2203917'
  - 'credinformsa@credinformsa\.com'
  - 'La Paz\s*-\s*Bolivia'
  # Teléfonos de sucursales regionales (Telf: (02)..., Telf: (03)..., Telf: (04)...)
  - 'Telf:\s*\(0[234]\)\d+'
  # Nombres de ciudades/sucursales aisladas extraídas del pie de página
  - '^(OFICINA PRINCIPAL|SUCURSAL 1|SANTA CRUZ|COCHABAMBA|SUCRE|POTOSI|ORURO|TARIJA|CAMIRI|YACUIBA|TRINIDAD)$'
  # Encabezados de póliza y metadatos repetitivos por página
  - 'SERVICIOS PETROLEROS PONEX S\.R\.L CAC-SCE0651635'
  - 'SERVICIOS PETROLEROS PONEX S\.R\.L\s+CAC-[A-Z0-9]+'
  - 'Asegurado:\s*\|\s*\|\s*\|\s*\|'
  - '^\|\s*Asegurado:\s*\|\s*\|\s*\|\s*\|\s*$'
  - '^P[áa]gina\s+\d+\s+de\s+\d+$'

table_split_hints: []

normalize_dates: false
currency_fields: []

# -------------------------------------------------------------------
# Identificación de metadatos de póliza en encabezados repetitivos
# -------------------------------------------------------------------
header_metadata_patterns:
  - id: cri_header_policy_identification
    description: >-
      Identifica en los encabezados repetitivos de páginas escaneadas el número de póliza,
      el tomador y/o el asegurado para consolidar la información básica de la póliza.
    patterns:
      numero_poliza:
        - 'P[ÓO]LIZA(?:\s*(?:NRO\.?|N°|NO\.?|:))?\s*([A-Z0-9\-\/]+)'
        - 'CAC\-[A-Z0-9]+'
      tomador:
        - 'TOMADOR(?:\s*[:\-])?\s*([A-Z0-9\.\,\s\-\&]+)'
        - 'CONTRATANTE(?:\s*[:\-])?\s*([A-Z0-9\.\,\s\-\&]+)'
      asegurado:
        - 'ASEGURADO(?:\s*[:\-])?\s*([A-Z0-9\.\,\s\-\&]+)'

# -------------------------------------------------------------------
# Reglas de limpieza y corrección de celdas de tablas (Tabular Leakage)
# -------------------------------------------------------------------
table_cell_cleanup_rules:
  # Sub-tarea A: Eliminación de Prefijos Basura en Celdas de Nombres
  - id: cri_clean_table_name_prefixes
    description: >-
      Remueve índices numéricos y caracteres residuales de escaneo (ej. '1 .- ,', '3 .- ,')
      al inicio de celdas de texto limpio en tablas de asegurados.
    pattern: '(\|\s*)\d+\s*\.?\s*-\s*,\s*'
    replacement: '\1'

  # Sub-tarea B: Separación de Mezcla de Columnas y Sufijos de Tasas ('NT') en C.I.
  - id: cri_clean_ci_suffix_nt
    description: >-
      Remueve el sufijo flotante 'NT' y prefijos redundantes 'CI.' en celdas de documento
      de identidad, dejando únicamente el identificador numérico limpio.
    pattern: '(\|\s*)(?:CI\.?\s*)?(\d+)\s+NT(\s*\|)'
    replacement: '\1\2\3'
```

## Notas de Análisis

Observaciones generales sobre la estructura y formato de los documentos de esta empresa.
Agregar notas cada vez que se identifique un patrón nuevo, independientemente del archivo analizado.

- [x] Eliminación del pie de página institucional multicolumna (Oficina Principal Calacoto, Sucursal 1 Ravelo, contactos y sucursales regionales en Santa Cruz, Cochabamba, Sucre, Potosí, Oruro, Tarija, Camiri, Yacuiba, Trinidad).
- [x] Identificación y extracción de metadatos de póliza (Tomador, Asegurado, Número de Póliza) en encabezados repetitivos de páginas en documentos PDF escaneados (Condicionados Particulares).
- [x] Agregada lista de `kv_keys` específicos para campos de cabecera de pólizas CRI (`Asegurado`, `Tomador`, `Nro. NIT`, `Dirección`, etc.).
- [x] **Corrección de fugas de delimitadores y mezcla de columnas (Tabular Leakage):**
  - **Sub-tarea A (Prefijos basura en filas de tablas):** Eliminación de secuencias residuales como `\d+\s*\.-\s*,\s*` al inicio de celdas (ej. `| 1 .- , IVAN FERNANDO NATANAEL PICARDI |` $\rightarrow$ `| IVAN FERNANDO NATANAEL PICARDI |`).
  - **Sub-tarea B (Sufijos de tasas 'NT' y prefijo 'CI.' en documentos de identidad):** Limpieza de celdas de identificación con sufijo flotante `NT` (ej. `| CI. 18207 NT |` $\rightarrow$ `| 18207 |`, `| 6232690 NT |` $\rightarrow$ `| 6232690 |`).
- [x] **Eliminación de ruido de maquetación y reconstrucción de tablas:**
  - Supresión de encabezados de póliza intermedios (`SERVICIOS PETROLEROS PONEX S.R.L CAC-SCE0651635`).
  - Supresión de filas de metadatos/tablas vacías (`Asegurado: | | | |`).
  - Supresión de números de página intermedios (`Página X de Y`).
  - **Reconstrucción de flujo continuo:** Cuando el ruido de maquetación divide una tabla a la mitad, se eliminan las líneas intrusivas y se unen las filas de la tabla de forma continua y sin rupturas.
- [x] **Arquitectura de Pipeline en 3 Fases:**
  1. *Fase 1 (Sustitución Determinista):* Regex para barrer patrones exactos de maquetación (páginas, encabezados, metadatos vacíos).
  2. *Fase 2 (Sustitución de Tablas):* Regex específicas para celdas de tablas (prefijos basura y sufijos NT en C.I.).
  3. *Fase 3 (Refinamiento Semántico):* Reconstrucción del flujo Markdown continuo, resolución de guiones de fin de línea y unificación de tablas huérfanas.

## Historial de Cambios

| Versión | Fecha | Cambio |
|---------|-------|--------|
| 5 | 2026-08-26 | Adición de reglas de limpieza tabular (`table_cell_cleanup_rules` para prefijos basura y sufijos NT en C.I.), eliminación de ruido de maquetación Ponex/CRI, patrones de reconstrucción de tablas divididas y especificación del pipeline de 3 fases |
| 4 | 2026-08-25 | Agregados `kv_keys` específicos para Credinform y regla `header_metadata_patterns` para extraer tomador/asegurado y número de póliza desde encabezados repetitivos |
| 3 | 2026-07-30 | Actualizados patrones de eliminación de pie de página institucional (Sucursal 1, direcciones, emails y teléfonos de sucursales) |
| 2 | 2026-07-30 | Agregados patrones de eliminación de encabezado institucional (Oficina Central / Central Piloto) |
| 1 | 2026-07-30 | Creación de plantilla inicial |