# ServChart hub: Django API + built React UI + the local collector, in one image.

# --- 1. Build the web UI --------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY web/ ./
RUN npm run build   # -> /src/hub/web_dist

# --- 2. Runtime -----------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/agent \
    SERVCHART_DATA_DIR=/data
WORKDIR /app/hub

COPY hub/requirements.txt /app/hub/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/servchart_agent /app/agent/servchart_agent
COPY hub/ /app/hub/
COPY examples/ /app/examples/
COPY --from=web /src/hub/web_dist /app/hub/web_dist
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
 && SERVCHART_DATA_DIR=/tmp/build python manage.py collectstatic --noinput >/dev/null \
 && rm -rf /tmp/build \
 && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8484
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8484/healthz').status==200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
