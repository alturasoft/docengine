# Reglas del Proyecto DocEngine

## 🛑 PRINCIPIO FUNDAMENTAL: INMUTABILIDAD Y NO REGRESIÓN (ESTRICTO)

**Principio Base:** "Todo lo que actualmente está funcionando NO debe modificarse bajo ninguna circunstancia."

Al construir, editar o extender los Skills (tanto el Skill General como los Skills individuales por empresa aseguradora), debes cumplir estrictamente con las siguientes directivas:

### 1. Cero Refactorización No Solicitada

- Prohibido modificar, simplificar, "limpiar" o reestructurar expresiones regulares, reglas de extracción o lógica de procesamiento (Docling) que ya hayan sido validadas o estén operativas.
- Asume que toda regla existente cumple una función crítica en producción.

### 2. Desarrollo Estrictamente Aditivo

- Toda nueva funcionalidad, soporte para una nueva aseguradora o corrección de casos borde debe ser **única y exclusivamente aditiva**.
- Las correcciones o nuevas reglas deben encapsularse mediante nuevas funciones, clases o bloques condicionales aislados, sin alterar la línea de ejecución de las reglas existentes.

### 3. Jerarquía y Aislamiento de Ámbito (Scope)

- **Skill General** (`skills/skill-general.md`): Contiene el comportamiento base. Es **INMUTABLE** salvo que explícitamente se ordene una modificación global.
- **Skills Individuales** (`skills/skill-{sigla}.md`): Solo pueden extender funcionalidades o aplicar sobrescrituras (*overrides*) dentro de su propio ámbito. **NINGÚN** Skill de empresa debe alterar o romper la compatibilidad con el Skill General ni con los de otras aseguradoras.

### 4. Protocolo de Verificación Antes de Cada Cambio

Ante cualquier solicitud de modificación en este proyecto, debes:

1. **Identificar** si el cambio es aditivo o toca código/reglas ya existentes.
2. **Bloquear** cualquier acción que modifique reglas ya validadas sin orden explícita del usuario.
3. **Aislar** toda nueva lógica en su propio ámbito antes de escribir cualquier línea.
4. **Informar** al usuario si una solicitud implica romper este principio, y proponer una alternativa aditiva.

---

## Contexto del Proyecto

- **Motor:** DocEngine — extracción de datos de pólizas de seguros bolivianas usando Docling.
- **Skill General:** `skills/skill-general.md` — reglas base para todas las aseguradoras.
- **Skills de empresa:** `skills/skill-{sigla}.md` — extienden el Skill General por aseguradora.
- **Regla de composición:** Los skills de empresa **extienden** listas del general (unión). Los valores escalares de empresa sobreescriben los del general.
