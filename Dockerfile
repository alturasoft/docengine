FROM python:3.12-slim

LABEL maintainer="DocEngine Team"
LABEL description="Motor de Extracción Documental — Docling / IBM Research"

# --- System dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- Working directory ---
WORKDIR /app

# --- Install Python dependencies ---
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Copy application code and extraction skills ---
COPY app/ ./app/
COPY skills/ ./skills/
COPY .agents/ ./.agents/
COPY main.py .

# --- Create output and sample directories ---
RUN mkdir -p outputs samples

# --- Non-root user for security ---
RUN addgroup --system docengine && adduser --system --group docengine && \
    chown -R docengine:docengine /app

USER docengine

# --- Expose API port ---
EXPOSE 8000

# --- Health check ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()"

# --- Startup command ---
# Docling models are downloaded on first use (or from artifacts_path if configured)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
