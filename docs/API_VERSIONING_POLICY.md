# DocEngine — Política de Versionado de API

Esta política establece los principios y directrices técnicas que rigen la evolución de las APIs públicas de **DocEngine**, garantizando que los sistemas consumidores (agentes externos, portales web, microservicios y sistemas legados) operen de forma estable y continua sin sufrir disrupciones ante actualizaciones del motor.

---

## 1. Principio Fundamental: Evolución Estrictamente Aditiva

Toda modificación en la versión actual (`v1`) debe ser **100% retrocompatible**:

1. **Inmutabilidad de contratos existentes:** Los nombres de campos, tipos de datos y estructuras de respuesta ya expuestos en `v1` no se renombran, eliminan ni modifican.
2. **Nuevos atributos opcionales:** Cualquier nuevo campo incorporado en esquemas de solicitud (*request*) o respuesta (*response*) se declara con valor predeterminado nulo o por defecto (`default=None`), de modo que clientes que no lo conozcan continúen funcionando sin errores de validación.
3. **Parámetros de consulta opcionales:** Nuevos filtros o flags de operación (por ejemplo, `async_mode`, `ramo`, `vigencia_fecha`) se diseñan con valores por defecto que preservan el comportamiento original previo.

---

## 2. Esquema de Versionado por URI

Todas las rutas públicas de DocEngine siguen un esquema de versionado en la ruta raíz:

```text
/api/v{major}/[recurso]
```

- **Versión Activa:** `/api/v1/`
- Cualquier cambio estructural mayor que rompa la compatibilidad hacia atrás dará origen a un nuevo prefijo `/api/v2/`.
- Ambas versiones coexistirán en el mismo despliegue durante el período de migración.

---

## 3. Catálogo de Endpoints Versionados (v1)

| Endpoint | Método | Perfil Mínimo | Descripción |
|---|---|---|---|
| `/api/v1/query` | `POST` | `readonly` | Consulta semántica con respuesta generada por LLM (citas de fuentes). |
| `/api/v1/query/search` | `POST` | `readonly` | Búsqueda y re-ranking de fragmentos puros sin llamada a LLM. |
| `/api/v1/policies/recent` | `GET` | `readonly` | Listado paginado de pólizas digitalizadas recientes. |
| `/api/v1/policies/search` | `GET` | `readonly` | Búsqueda por identificador, número de póliza o cliente. |
| `/api/v1/policies/envelopes` | `GET` | `readonly` | Listado y detalle de sobres lógicos de pólizas. |
| `/api/v1/policies/{id}` | `GET` | `readonly` | Información básica y metadatos de cabecera. |
| `/api/v1/policies/{id}/structured` | `GET` | `readonly` | JSON completo atomizado (coberturas, límites, deducibles, vigencias). |
| `/api/v1/extract` | `POST` | `writer` | Extracción documental de PDF (modo síncrono o `async_mode=True`). |
| `/api/v1/extract/jobs/{job_id}` | `GET` | `readonly` | Consulta de estado de extracción asíncrona. |
| `/api/v1/extract/url` | `POST` | `writer` | Extracción de PDF desde URL pública. |
| `/api/v1/extract/folder` | `POST` | `admin` | Procesamiento masivo por lote de carpetas del servidor. |
| `/api/v1/policies/{id}` | `DELETE` | `admin` | Eliminación atómica de documento individual para reemplazo. |
| `/api/v1/policies/envelopes/{id}` | `DELETE` | `admin` | Eliminación completa de sobre y documentos vinculados. |
| `/api/v1/catalogs/*` | `GET` | `readonly` | Catálogos maestros (compañías, ramos, tipos de documento). |

---

## 4. Ciclo de Deprecación y Descontinuación

En caso de que una funcionalidad o campo deba considerarse obsoleto en el futuro:

1. **Notificación previa:** Se notificará con al menos **6 meses de anticipación** en la documentación de la API y en notas de lanzamiento.
2. **Cabeceras HTTP estándar (RFC 8594 / RFC 9110):** Los endpoints en fase de deprecación responderán incluyendo las cabeceras:
   - `Deprecation: true`
   - `Sunset: <fecha en formato HTTP-date>` (ej. `Sunset: Wed, 14 Oct 2027 00:00:00 GMT`)
3. **Mantenimiento en paralelo:** La versión descontinuada continuará respondiendo peticiones con normalidad hasta que venza la fecha límite establecida en la cabecera `Sunset`.

---

## 5. Especificación OpenAPI y Gobernanza

La especificación formal de la API se exporta y versiona en:
- Ruta dinámica: `/openapi.json`
- Archivo estático versionado en repositorio: `docs/openapi.json`
- Documentación interactiva Swagger UI: `/docs`
- Documentación ReDoc: `/redoc`

Cualquier cambio a la API se valida mediante la suite automatizada de pruebas unitarias y de integración antes de ser promovido al entorno de producción.
