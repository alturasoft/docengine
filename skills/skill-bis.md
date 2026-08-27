---
sigla: BIS
empresa: BISA SEGUROS Y REASEGUROS
version: 2
estado: activo
ultima_revision: 2026-08-26
---

## Descripción

Reglas de extracción y directivas de procesamiento para pólizas de **BISA Seguros y Reaseguros S.A.**

Este skill extiende las reglas base del `skill-general.md` integrando los hallazgos de extracción, principios de integridad numérica, alineación tabular multidimensional, preservación de límites de cobertura y tratamiento de carátulas sin bordes físicos.

## Reglas de Post-Procesado

```yaml
# -------------------------------------------------------------------
# Campos KV específicos para BISA Seguros
# -------------------------------------------------------------------
kv_keys:
  - Póliza
  - Poliza
  - Póliza Nro.
  - Póliza Nro
  - Nro. de Póliza
  - N° de Póliza
  - Número de Póliza
  - Vigencia
  - Periodo de Vigencia
  - Desde
  - Hasta
  - Asegurado
  - Tomador
  - Contratante
  - Prima Total Anual
  - Prima Total
  - Prima Neta
  - Prima
  - Forma de Pago
  - Forma Pago
  - Frecuencia de Pago
  - Frecuencia Pago
  - Moneda
  - Intermediario
  - Corredor
  - Agente
  - Deducible
  - Límite Territorial

# -------------------------------------------------------------------
# Patrones de cabecera/pie a eliminar en documentos BISA
# -------------------------------------------------------------------
header_patterns:
  - '^BISA SEGUROS Y REASEGUROS S\.A\.?$'
  - '^P[áa]gina\s+\d+\s+de\s+\d+$'
  - '^\|\s*Campo\s*\|\s*Detalle\s*(/\s*Valor)?\s*\|\s*$'

table_split_hints:
  - "CONDICIONES PARTICULARES"
  - "CONDICIONES GENERALES"
  - "TABLA DE BENEFICIOS"
  - "COBERTURAS Y DEDUCIBLES"
  - "EXCLUSIONES"

normalize_dates: false
currency_fields:
  - Prima Total Anual
  - Prima Total
  - Prima Neta
  - Deducible

# -------------------------------------------------------------------
# Identificación de metadatos en carátulas y encabezados repetitivos
# -------------------------------------------------------------------
header_metadata_patterns:
  - id: bis_header_policy_identification
    description: >-
      Extrae de carátulas tipo formulario y encabezados repetitivos el número de póliza,
      vigencia, tomador, asegurado, prima total anual, forma de pago y moneda.
    patterns:
      numero_poliza:
        - '(?:P[ÓO]LIZA|N[UÚ]MERO DE P[ÓO]LIZA)(?:\s*(?:NRO\.?|N°|NO\.?|:))?\s*([A-Z0-9\-\/]+)'
        - 'P10\d{8}'
      tomador:
        - '(?:TOMADOR|CONTRATANTE)(?:\s*[:\-])?\s*([A-Z0-9\.\,\s\-\&]+)'
      asegurado:
        - '(?:ASEGURADO)(?:\s*[:\-])?\s*([A-Z0-9\.\,\s\-\&]+)'
      vigencia:
        - '(?:VIGENCIA|PERIODO DE VIGENCIA)(?:\s*[:\-])?\s*([^\n\|]+)'
      prima_total:
        - '(?:PRIMA TOTAL ANUAL|PRIMA TOTAL)(?:\s*[:\-])?\s*([^\n\|]+)'
      forma_pago:
        - '(?:FORMA DE PAGO|FORMA PAGO)(?:\s*[:\-])?\s*([^\n\|]+)'
      moneda:
        - '(?:MONEDA)(?:\s*[:\-])?\s*([^\n\|]+)'

# -------------------------------------------------------------------
# Reglas de limpieza y corrección de celdas de tablas (Tabular Leakage / OCR)
# -------------------------------------------------------------------
table_cell_cleanup_rules:
  # Sub-tarea: Corrección de truncamiento y segmentación OCR en Intermediarios
  - id: bis_clean_broker_ocr_truncation
    description: >-
      Corrige el truncamiento de OCR donde 'Corredores' se corta como 'es' y reunifica
      el nombre oficial de intermediarios como 'Sudamericana S.R.L. Corredores Y Asesores De Seguros'.
    pattern: '(\|\s*Sudamericana\s+S\.?R\.?L\.?)\s+es(\s*\|)'
    replacement: '\1 Corredores Y Asesores De Seguros\2'

  - id: bis_clean_orphan_coverage_percentages
    description: >-
      Revincula valores de cobertura porcentuales que hayan quedado flotando o desalineados
      fuera de su columna correspondiente.
    pattern: '(\|\s*[^\n\|]+?)\s*<br>\s*(100%|[0-9]+%)\s*(\|+)'
    replacement: '\1 | \2\3'

# -------------------------------------------------------------------
# Corrección de alineación de columnas y desfaces en tablas
# -------------------------------------------------------------------
table_column_alignment_fixes:
  - id: fix_deducibles_multidimensional_bis
    description: >-
      Reconstruye la tabla multidimensional de deducibles anuales obligatorios por plan
      (Dentro vs. Fuera del país de residencia) cuando Docling fragmenta Plan 1, omite
      el límite internacional de US$ 5,000 y fusiona las columnas en los Planes 2, 3 y 4.
    rule_type: "reconstruct_multidimensional_deducibles"
    header_pattern: ["Plan", "Dentro del país de residencia", "Fuera del país de residencia"]
    expected_columns: 3

  - id: fix_transporte_evacuacion_bis
    description: >-
      Asegura la preservación de la columna derecha de cobertura (100%) en tablas
      de transporte o evacuación médica con bordes invisibles.
    header_pattern: ["Beneficio", "Límite de Cobertura"]
    expected_columns: 2
    insert_at_index: 1
    fill_value: "100%"
    condition: "row_cells == 1 and header_cells == 2"
```

## Directivas de Extracción Estructural y Semántica para BIS

### 1. Reglas Generales de Procesamiento Estructural
- **Principio de Integridad Numérica:** Ningún valor monetario, porcentaje, límite o deducible presente en el documento original en PDF puede ser omitido, redondeado o resumido en la extracción en Markdown.
- **Asociación Estricta Fila-Columna:** En cualquier tabla, toda celda de descripción debe conservar su correspondencia física y lógica con su respectiva celda de cobertura o valor. Si una celda de valor queda vacía, se debe disparar una verificación secundaria de alineación basada en coordenadas.

---

### 2. Instrucciones Específicas basadas en Hallazgos de Extracción

#### REGLA 1: Mapeo y Emparejamiento Multidimensional de Deducibles
- **Contexto del problema:** Omisión de montos de deducible internacional y colapso de filas en tablas con múltiples condiciones territoriales.
  *Ejemplo del error detectado en Docling:*
  ```markdown
  Opciones de deducible anual obligatorio:

  | **Plan** | 1 |

  Dentro del país de residencia:
  Doscientos cincuenta dólares (US$250)

  ## Fuera del país de residencia

  | **Plan** | 2 Dos mil dólares (US$2,000) Dos mil dólares (US$2,000) |
  | **Plan** | 3 Cinco mil dólares (US$5,000) Cinco mil dólares (US$5,000) |
  | **Plan** | 4 Diez mil dólares (US$10,000) Diez mil dólares (US$10,000) |
  ```
- **Instrucción de corrección:** Al procesar tablas que segmenten deducibles u opciones por límites territoriales, debes asegurar la creación de una matriz clara en Markdown de 3 columnas (`Plan`, `Dentro del país de residencia`, `Fuera del país de residencia`). Cada fila de Plan (ej. `Plan 1`, `Plan 2`, `Plan 3`, `Plan 4`) debe contener de forma explícita y en la misma línea lógica los dos valores numéricos correspondientes. No conviertas texto intermedio de columnas (ej. `"Fuera del país de residencia"`) en encabezados Markdown (`#`, `##`, `###`, `####`), ya que esto fragmenta la estructura tabular y oculta valores financieros críticos (como omitir el límite de `Cinco mil dólares (US$5,000)` para el Plan 1).
  *Salida esperada:*
  ```markdown
  Opciones de deducible anual obligatorio:

  | Plan | Dentro del país de residencia | Fuera del país de residencia |
  | --- | --- | --- |
  | Plan 1 | Doscientos cincuenta dólares (US$250) | Cinco mil dólares (US$5,000) |
  | Plan 2 | Dos mil dólares (US$2,000) | Dos mil dólares (US$2,000) |
  | Plan 3 | Cinco mil dólares (US$5,000) | Cinco mil dólares (US$5,000) |
  | Plan 4 | Diez mil dólares (US$10,000) | Diez mil dólares (US$10,000) |
  ```

#### REGLA 2: Preservación Completa de Límites de Cobertura en Textos Extensos
- **Contexto del problema:** Pérdida de la columna de cobertura derecha (ej. `"100% habitación privada"`) cuando la celda de descripción de la izquierda es excesivamente larga.
- **Instrucción de corrección:** La longitud de un texto descriptivo de beneficio nunca debe provocar la omisión de su valor de cobertura asociado. Se debe mantener el diseño de la tabla Markdown de dos o más columnas (ej. `| Beneficio | Límite de Cobertura |`). Si el texto de descripción tiene más de 100 caracteres, la celda derecha de cobertura DEBE crearse y poblarse con el valor exacto (ej. `100% habitación privada`), sin omitirlo ni colapsarlo fuera de la estructura de la tabla.

#### REGLA 3: Prohibición de Truncamiento en Celdas de Descripción
- **Contexto del problema:** Truncamiento de frases restrictivas o aclaratorias al final de una celda (ej. omitir `"cuando el asegurado esté recibiendo un tratamiento cubierto"` en el beneficio de Cama Extra).
- **Instrucción de corrección:** Extraer el 100% del contenido de texto de cada celda de descripción. No apliques resúmenes, no cortes el texto de forma prematura ni asumas que las condiciones secundarias son irrelevantes. Toda cláusula legal o frase aclarativa es un límite contractual y debe figurar íntegramente en la celda de texto correspondiente.

#### REGLA 4: Reensamblado de Filas Fragmentadas por Saltos de Página o Bloque
- **Contexto del problema:** División de un beneficio continuo en dos tablas independientes debido a saltos de página físicos en el PDF (ej. `"Cirugía y Honorarios Médicos"`), dejando la segunda mitad del beneficio huérfana y sin su valor de cobertura.
- **Instrucción de corrección:** Antes de renderizar una tabla en Markdown, analiza si el texto de una celda se interrumpe físicamente debido a un salto de página o cambio de bloque en el PDF. Si detectas que una fila continúa en la siguiente sección o página, reensambla el texto completo en una sola celda y asígnale su valor de cobertura unificado (ej. `100%`). No generes dos tablas adyacentes ni dejes filas huérfanas sin columna de cobertura debido a cortes físicos del papel.

#### REGLA 5: Vinculación Estricta de Notas de Cobertura y Valores Huérfanos
- **Contexto del problema:** Extracción de valores porcentuales (ej. `"100%"`) de forma aislada y fuera de la tabla Markdown, rompiendo la relación lógica con notas aclaratorias (ej. notas sobre Cirugía Reconstructiva Cosmética).
- **Instrucción de corrección:** Todo valor porcentual o límite monetario debe ser encapsulado estrictamente dentro de los límites de la tabla (`|`). Queda prohibido imprimir valores de cobertura como texto libre flotante por encima o por debajo de la tabla Markdown. Si existe una nota aclaratoria relacionada con el beneficio, insértala como una fila interna de la tabla o bajo una celda que abarque las columnas necesarias, manteniendo el valor numérico de cobertura dentro del mismo bloque estructurado.

#### REGLA 6: Preservación de Listas y Viñetas Internas en Celdas
- **Contexto del problema:** Fuga de viñetas hacia el exterior de la tabla (ej. listado de órganos cubiertos en Trasplantes que se salen de la estructura de tabla en Markdown).
- **Instrucción de corrección:** Cuando una celda contenga una lista con viñetas (ej. `corazón/pulmón`, `médula ósea`), procesa todo el listado dentro de la misma celda de la tabla. Utiliza saltos de línea HTML `<br>` combinados con caracteres de viñeta estándar (ej. `-` o `•`) para mantener el listado estructurado *dentro* de los delimitadores de la columna (`|`). No cierres la tabla de manera prematura ni conviertas las viñetas internas en una lista Markdown tradicional fuera de la tabla.

#### REGLA 7: Detección y Parseo Estricto de Filas Continuas sin Bordes
- **Contexto del problema:** Pérdida completa de la estructura de tabla en filas específicas que contienen listas (ej. `"Medicamentos con Receta"`), convirtiéndolas erróneamente en texto plano de párrafo.
- **Instrucción de corrección:** Vigilar las transiciones de filas. Si un beneficio (como medicamentos recetados) contiene explicaciones detalladas seguidas de diferenciación de límites por planes (ej. `Plan 1: hasta US$ 5,000; Planes 2 a 4: 100%`), esta información DEBE estructurarse dentro de las columnas de la tabla. No rompas los delimitadores `|` para transformarlos en encabezados de nivel 4 o texto plano de párrafo.

#### REGLA 8: Extracción de Exclusiones y Restricciones de Beneficios Ambulatorios
- **Contexto del problema:** Omisión completa de texto referente a exclusiones de póliza y referencias a numerales legales (ej. omitir las referencias a los numerales 4.18, 4.29, 4.46, 4.52 en el beneficio de Salud Mental).
- **Instrucción de corrección:** Las exclusiones, limitaciones y referencias numéricas a cláusulas generales dentro de una celda de beneficio son datos contractuales de máxima importancia. Queda estrictamente prohibido omitir el texto descriptivo de las exclusiones o sus llamadas numéricas. Capturar e incluir íntegramente frases como: `"Exclusiones y restricciones: Consultar los numerales X, Y, Z"` en la celda de descripción del beneficio.

#### REGLA 9: Mantenimiento de Columnas Invisibles de Cobertura en Tablas de Transporte
- **Contexto del problema:** Fusión de tablas multidimensionales en una sola columna plana, eliminando por completo los límites porcentuales de la columna derecha (ej. omitir el `100%` en Viaje de Traslado para Acompañante).
- **Instrucción de corrección:** En tablas de transporte o evacuación médica que presenten descripciones extensas, no colapsar las columnas. Aunque los bordes divisorios verticales sean invisibles o tenues en el PDF, identificar la separación espacial e interpretar la columna derecha de cobertura. Toda fila de beneficio de transporte debe cerrarse con su correspondiente delimitador de columna y su valor de cobertura (ej. `| Beneficio | 100% |`).

#### REGLA 10: Procesamiento de Carátulas de Póliza con Diseño de Formulario y Bordes Invisibles
- **Contexto del problema:** Colapso de datos clave de la póliza (número de póliza borrado, fechas de vigencia desaparecidas, fusión errónea de Prima Total Anual, Forma de Pago y Moneda en celdas desalineadas).
- **Instrucción de corrección:** Para tablas estilo "formulario" o carátulas de póliza (sin bordes de rejilla tradicionales), aplicar análisis de alineación por coordenadas de cajas de texto:
  1. Identificar y extraer con precisión pares de `Etiqueta | Valor` (ej. `Número de Póliza | P1010000046`, `Vigencia | Desde 01/11/2025 Hasta 01/11/2026`).
  2. Nunca reemplazar valores numéricos identificadores (números de póliza) con guiones (`-`) o valores en blanco.
  3. Asegurar que las fechas completas de vigencia sean mapeadas a su columna correspondiente en lugar de ser eliminadas.
  4. Mantener de forma separada campos financieros distintos como "Prima Total Anual" (ej. `US$ 3,300.86`), "Forma de Pago" (ej. `Anual`) y "Moneda" (ej. `Dólares Americanos`).

#### REGLA 11: Alineación de Campos Multicolumna en Condiciones Particulares
- **Contexto del problema:** Valores de columnas adyacentes (ej. `"Dólares Americanos"` en la columna Moneda) que se desalinean, saliéndose de la tabla y quedando como texto plano debajo de ella, dejando celdas vacías.
- **Instrucción de corrección:** Asegurar que los campos distribuidos horizontalmente en una sola fila física del PDF (ej. `Forma de Pago: Anual | Moneda: Dólares Americanos`) se representen estrictamente como celdas adyacentes en la misma fila de la tabla en Markdown:
  ```markdown
  | **Forma de Pago** | **Moneda** |
  | Anual | Dólares Americanos |
  ```
  No desplazar valores a la siguiente línea de texto plano ni dejar columnas de cabecera vacías si su valor se encuentra impreso horizontalmente a la derecha en el PDF original.

#### REGLA 12: OCR de Alta Precisión y Segmentación Semántica de Intermediarios
- **Contexto del problema:** Palabra `"Corredores"` truncada y leída como `"es"`, y asumida erróneamente como un nuevo encabezado de columna `"Corredor"`, fragmentando el nombre de un agente de seguros (`Sudamericana S.R.L. Corredores Y Asesores De Seguros`).
- **Instrucción de corrección:** Al procesar nombres de intermediarios, agentes o entidades legales corporativas:
  1. Evitar la segmentación de palabras largas que queden al borde de la caja de texto (ej. `"Corredores"` no debe truncarse en `"es"`).
  2. No interpretar palabras descriptivas del tipo de entidad (ej. `"Corredores y Asesores de Seguros"`) como si fuesen etiquetas de nuevas filas o columnas.
  3. Mantener el nombre completo y oficial del intermediario en una sola celda unificada de valor de texto continuo.

---

## Notas de Análisis

Observaciones generales sobre la estructura y formato de los documentos de esta empresa.
Agregar notas cada vez que se identifique un patrón nuevo, independientemente del archivo analizado.

- [x] **Principio de Integridad Numérica:** Configuración de preservación estricta de valores monetarios, límites, porcentajes y deducibles.
- [x] **Mapeo de Metadatos de Formulario/Carátula:** Reglas `header_metadata_patterns` para carátulas de póliza BISA (Póliza `P1010000046`, Vigencia `Desde 01/11/2025 Hasta 01/11/2026`, Prima Total Anual, Forma de Pago, Moneda, Tomador y Asegurado).
- [x] **Mapeo Multidimensional de Deducibles:** Matriz de Plan 1/2 con montos explícitos Dentro/Fuera del país (incluyendo límites como `US$ 5,000` en Plan 1).
- [x] **Corrección de Tablas y Rupturas:** Reglas `table_column_alignment_fixes` para tablas de deducibles territoriales y tablas de transporte/evacuación médica.
- [x] **Limpieza y OCR de Intermediarios:** Regla `table_cell_cleanup_rules` para resolver truncamiento de "Corredores" a "es" y reunificación de intermediarios (`Sudamericana S.R.L. Corredores Y Asesores De Seguros`).
- [x] **Preservación de Viñetas Internas y Descripciones Extensas:** Uso de `<br>` con viñetas internas y prohibición de truncamiento en textos legales y citas a numerales (4.18, 4.29, etc.).

## Historial de Cambios

| Versión | Fecha | Cambio |
|---------|-------|--------|
| 2 | 2026-08-26 | Implementación completa de directivas y reglas de extracción para BIS (12 reglas de extracción estructural, alineación tabular multidimensional, preservación de límites de cobertura, carátulas tipo formulario sin bordes y corrección de OCR en intermediarios) |
| 1 | 2026-07-30 | Creación de plantilla inicial |