FROM node:25-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    YLM_DATA_DIR=/data YLM_STATIC_DIR=/app/frontend/dist EXPORTER_LISTEN=0.0.0.0
WORKDIR /app
RUN groupadd --gid 10001 ylm \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin ylm \
    && install -d -o 10001 -g 10001 -m 0700 /data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend /build/dist/ ./frontend/dist/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/healthz', timeout=3)"]
ENTRYPOINT ["python", "-m", "backend.serve"]
CMD ["serve"]
