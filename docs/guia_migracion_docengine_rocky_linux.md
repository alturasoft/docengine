# Guía de Migración y Despliegue de DocEngine en Rocky Linux 8.10

## 1. Resumen Ejecutivo

Este documento detalla el procedimiento para migrar y desplegar la plataforma **DocEngine** en un entorno **Rocky Linux 8.10 (Green Obsidian)** utilizando **Podman** / **Podman-Compose**, asegurando la propagación, observabilidad e inmutabilidad de los **Skills de Aseguradoras** (`skills/`) y las **Reglas de Agentes** (`.agents/AGENTS.md`).

---

## 2. Inclusión y Montaje Dinámico de Skills (`skills/` y `.agents/`)

### Diagnóstico de la Causa Raíz
En la configuración inicial del contenedor Docker/Podman, solo se copiaba la carpeta `app/` y el archivo `main.py`. Al ejecutar en el servidor, el cargador de reglas (`company_skill_loader.py`) intentaba leer `/app/skills/skill-general.md`, pero al no existir la ruta en el contenedor, degradaba a un objeto `CompanySkill` vacío.

### Solución Implementada
1. **Compilación de Imagen (`Dockerfile`)**:
   Se incorporaron las instrucciones explícitas para incluir las reglas en el build base:
   ```dockerfile
   # --- Copy application code and extraction skills ---
   COPY app/ ./app/
   COPY skills/ ./skills/
   COPY .agents/ ./.agents/
   COPY main.py .
   ```

2. **Montaje Dinámico en Lectura (`docker-compose.yml`)**:
   Para permitir la iteración continua durante la fase de pruebas (PC $\rightarrow$ Servidor) sin necesidad de reconstruir la imagen en cada ajuste de reglas:
   ```yaml
   volumes:
     # Persist extracted documents
     - ./outputs:/app/outputs
     # Read-only samples for testing
     - ./samples:/app/samples:ro
     # Insurance company extraction skills & rules
     - ./skills:/app/skills:ro
     # Agent rules and guidelines
     - ./.agents:/app/.agents:ro
   ```

---

## 3. Configuración del Entorno en Rocky Linux 8.10 (Podman)

### 3.1 Gestión de Motor de Contenedores (Podman)
En Rocky Linux 8.10, el motor predeterminado de contenedores es **Podman** (`podman version 4.9.x`).
- Instalación de `podman-compose` en el entorno virtual Python:
  ```bash
  cd /opt/docengine
  source .venv/bin/activate
  pip install podman-compose
  ```

### 3.2 Liberación de Puertos y Transición desde Systemd
Si previamente existía una instancia nativa o servicio systemd ejecutándose en el puerto 8000 (TCP):
1. **Desactivar el servicio systemd previo**:
   ```bash
   sudo systemctl stop docengine
   sudo systemctl disable docengine
   ```
2. **Liberar el puerto 8000 (TCP)**:
   ```bash
   sudo fuser -k -9 8000/tcp
   ss -tulpn | grep 8000  # Confirmar que la salida retorna vacía
   ```

---

## 4. Procedimiento de Despliegue y Reconstrucción

### 4.1 Despliegue Inicial / Reconstrucción de la Imagen
```bash
cd /opt/docengine
source .venv/bin/activate
git pull origin main
podman rm -a
podman-compose up -d --build
```

### 4.2 Verificación de Estado y Logs
Para verificar que la API está en línea y cargando los Skills correctamente:
```bash
podman logs -f docengine_api
```
Salida esperada en el log estructurado:
- `DoclingAdapter initialized`
- `Docling models loaded. Service ready`
- `GET /api/v1/health HTTP/1.1 200 OK`

---

## 5. Flujo de Trabajo en Fase de Pruebas (PC $\rightarrow$ Servidor Rocky Linux)

Para mantener la agilidad durante el perfeccionamiento de reglas:

1. **En la PC**: Se añaden o afinan reglas en `skills/skill-{sigla}.md` o `skills/skill-general.md` (respetando los principios de desarrollo aditivo en `.agents/AGENTS.md`).
2. **Publicar en Repositorio**:
   ```bash
   git add skills/
   git commit -m "feat(skills): agregar patrones de llaves KV para aseguradora XXX"
   git push origin main
   ```
3. **Sincronizar en Rocky Linux 8.10**:
   ```bash
   cd /opt/docengine
   git pull origin main
   ```
   *Debido al montaje de volumen (`./skills:/app/skills:ro`), los cambios son leídos de inmediato por la aplicación sin necesidad de reiniciar el contenedor.*
