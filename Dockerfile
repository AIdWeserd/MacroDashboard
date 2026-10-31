FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MACRO_DATA_DIR=/app/data

WORKDIR /app
RUN groupadd --gid 10001 macro \
    && useradd --uid 10001 --gid macro --create-home macro
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && pip check

# Explicit allowlist: local data, credentials, drafts and tests never enter the image.
COPY app.py scheduler.py config.py ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY .streamlit/ ./.streamlit/
RUN mkdir -p /app/data && chown macro:macro /app/data
USER macro
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"]
CMD ["python", "-m", "streamlit", "run", "app.py"]
