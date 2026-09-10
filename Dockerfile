FROM python:3.12-slim

LABEL maintainer="DocEngine Team"
LABEL description="Motor de Extracción Documental — Docling / IBM Research"

# --- System dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    g++ \
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
COPY requirements.txt requirements-dev.txt pdfextract-1.0.0-py3-none-any.whl ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-dev.txt && \
    pip install --no-cache-dir ./pdfextract-1.0.0-py3-none-any.whl

# --- Copy application code and extraction skills ---
COPY app/ ./app/
COPY skills/ ./skills/
COPY .agents/ ./.agents/
COPY webui/ ./webui/
COPY scripts/ ./scripts/
COPY main.py .

# --- Create output, sample and cache directories and pre-initialize models ---
RUN mkdir -p outputs samples /tmp/huggingface /home/docengine && \
    python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()"

# --- Non-root user for security ---
RUN addgroup --system docengine && adduser --system --home /home/docengine --group docengine && \
    chown -R docengine:docengine /app /home/docengine /tmp/huggingface /usr/local/lib/python3.12/site-packages

ENV HOME=/home/docengine
ENV HF_HOME=/tmp/huggingface

USER docengine


# --- Expose API port ---
EXPOSE 8000

# --- Health check ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()"

# --- Startup command ---
# Docling models are downloaded on first use (or from artifacts_path if configured)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
