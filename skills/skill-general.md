---
sigla: GENERAL
empresa: (todas las empresas)
version: 8
estado: activo
ultima_revision: 2026-07-31
---

## Descripción

Reglas de extracción **base** aplicadas a todas las empresas antes de que
el skill individual de cada aseguradora agregue sus propias reglas.

Estas reglas provienen de patrones detectados durante el desarrollo del motor
y que son comunes a múltiples pólizas bolivianas de seguros.

> Las reglas de empresa **extienden** este skill (unión de listas).
> Los valores escalares de empresa sobreescriben los de este skill.

## Reglas de Post-Procesado

```yaml
# -------------------------------------------------------------------
# Campos KV comunes a pólizas bolivianas de seguros
# Detectados en policy_kv_formatter.py como patrones genéricos del motor.
# Se mueven aquí para que sean configurables y auditables.
# -------------------------------------------------------------------
kv_keys:
  - Producto
  - Tipo de Póliza
  - Tipo Póliza
  - Póliza
  - Poliza
  - Certificado
  - Frecuencia de Pago
  - Frecuencia Pago
  - Vigencia
  - Forma de Pago
  - Forma Pago
  - Agente
  - Corredor
  - Ejecutivo

# -------------------------------------------------------------------
# Patrones de cabecera/pie a eliminar en todos los documentos
# -------------------------------------------------------------------
header_patterns:
  # Marca de agua de versión trial de Syncfusion Essential PDF (incluyendo encabezados ##)
  - "(#+\\s*)?Created with a trial version of Syncfusion Essential PDF"
  # Encabezados genéricos de tabla K/V (Campo | Detalle / Valor)
  - "^\\|\\s*Campo\\s*\\|\\s*Detalle\\s*(/\\s*Valor)?\\s*\\|\\s*$"

table_split_hints: []

normalize_dates: false

currency_fields: []

# -------------------------------------------------------------------
# Formato e identificadores de página en el texto extraído
# -------------------------------------------------------------------
include_page_identifiers: true
page_identifier_format: "----> página {page_number}"

# -------------------------------------------------------------------
# Corrección de desface de columnas en tablas de coberturas y centros de convenio
# -------------------------------------------------------------------
table_column_alignment_fixes:
  - id: fix_franq_pct_zero_omission
    description: >-
      Corrige desface en tablas de coberturas donde la celda 'Franq.(%)' de valor 0.00
      es omitida por Docling, desplazando 'Valor Asegurado (Bs.)' a la columna 'Franq.(%)'.
    header_pattern: ["COBERTURAS", "Alc.", "Franq.(Bs.)", "Franq.(%)", "Valor Asegurado (Bs.)"]
    expected_columns: 5
    missing_column_name: "Franq.(%)"
    insert_at_index: 3
    fill_value: "0.00"
    condition: "row_cells == 4 and header_cells == 5"

  - id: fix_centro_convenio_table
    description: >-
      Corrige desface y mezcla de columnas en tablas de Centros de Convenio / Red de Proveedores
      donde Docling agrupa 'DIRECCION' y 'TELÉFONOS' en el encabezado y desorganiza las celdas de las filas.
    header_pattern: ["CENTRO DE CONVENIO", "PERSONA DE CONTACTO"]
    expected_columns: 4
    expected_header: ["CENTRO DE CONVENIO", "DIRECCION", "TELÉFONOS", "PERSONA DE CONTACTO"]
    rule_type: "reorder_split_provider_table"

  - id: fix_nomina_asegurados_incap_omission
    description: >-
      Corrige desface en tablas de Nómina de Asegurados donde la celda 'INCAP.' (igual valor a M. ACC.)
      es omitida por Docling, desplazando G. MED., SEP. y PRIMA a la izquierda.
    header_pattern: ["NOMINA DE ASEGURADOS", "DOC.", "M. ACC.", "INCAP.", "G. MED.", "SEP.", "PRIMA"]
    expected_columns: 7
    insert_at_index: 3
    fill_value: "copy_previous"
    condition: "row_cells == 6 and header_cells == 7"
```

## Notas de Análisis

Reglas detectadas automáticamente en el código fuente del motor:

- `kv_keys`: Migrados desde `policy_kv_formatter.py` (`_POLICY_KEYS`).
  Ahora son configurables desde aquí sin cambiar código Python.
- `header_patterns`: Patrón de marca de agua Syncfusion detectado en
  documentos de múltiples aseguradoras (coincide con texto plano o títulos tipo `## Created...`).
- `RepeatedElementsProcessor` ya elimina headers/footers repetitivos
  automáticamente por frecuencia — este skill complementa con patrones exactos.
- `include_page_identifiers`: Adiciona un identificador de página en el texto extraído (formato configurable mediante `page_identifier_format`, por ejemplo `----> página {page_number}`) para delimitar el inicio de cada página en el documento extraído.
- `table_column_alignment_fixes`: Lista de reglas para corregir desfaces de columnas en tablas Markdown. Especifica el patrón del encabezado (`header_pattern`), número de columnas esperado (`expected_columns`), índice de inserción (`insert_at_index`), valor a insertar (`fill_value`) y condición de activación (`condition`).

## Historial de Cambios

| Versión | Fecha | Cambio |
|---------|-------|--------|
| 8 | 2026-07-31 | Adición de la regla `fix_nomina_asegurados_incap_omission` en `table_column_alignment_fixes` para corregir desface por omisión de celda INCAP. (copiando valor previo M. ACC.) y limpieza de separadores huérfanos |
| 7 | 2026-07-31 | Adición de la regla `fix_centro_convenio_table` en `table_column_alignment_fixes` para corregir desface y mezcla de columnas en tablas de Centros de Convenio |
| 6 | 2026-07-31 | Actualizado `page_identifier_format` al formato solicitado `----> página {page_number}` para delimitar el inicio/fin de cada página |
| 5 | 2026-07-31 | Eliminado patrón de remoción de números de página de `header_patterns` y actualizado `page_identifier_format` a formato visible `--- Página {page_number} ---` |
| 4 | 2026-07-31 | Adición de `table_column_alignment_fixes` con regla `fix_franq_pct_zero_omission` para corregir desface por omisión de celda Franq.(%) con valor 0.00 |
| 3 | 2026-07-31 | Adición de la regla `include_page_identifiers` para adicionar un identificador de página en el texto extraído |
| 2 | 2026-07-30 | Actualizado patrón Syncfusion para eliminar también cuando aparece como título Markdown `## Created with...` |
| 1 | 2026-07-30 | Creación — reglas migradas desde código fuente y patrón Syncfusion |



