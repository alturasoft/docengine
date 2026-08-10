---
sigla: CRI
empresa: CREDINFORM INTERNATIONAL S.A
version: 3
estado: activo
ultima_revision: 2026-07-30
---

## Descripción

Reglas de extracción para pólizas de **Credinform International S.A.**

Completar este skill a medida que se analicen documentos y se identifiquen patrones
propios de esta aseguradora.

## Reglas de Post-Procesado

```yaml
kv_keys: []

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

table_split_hints: []

normalize_dates: false
currency_fields: []
```

## Notas de Análisis

Observaciones generales sobre la estructura y formato de los documentos de esta empresa.
Agregar notas cada vez que se identifique un patrón nuevo, independientemente del archivo analizado.

- [x] Eliminación del pie de página institucional multicolumna (Oficina Principal Calacoto, Sucursal 1 Ravelo, contactos y sucursales regionales en Santa Cruz, Cochabamba, Sucre, Potosí, Oruro, Tarija, Camiri, Yacuiba, Trinidad).

## Historial de Cambios

| Versión | Fecha | Cambio |
|---------|-------|--------|
| 3 | 2026-07-30 | Actualizados patrones de eliminación de pie de página institucional (Sucursal 1, direcciones, emails y teléfonos de sucursales) |
| 2 | 2026-07-30 | Agregados patrones de eliminación de encabezado institucional (Oficina Central / Central Piloto) |
| 1 | 2026-07-30 | Creación de plantilla inicial |