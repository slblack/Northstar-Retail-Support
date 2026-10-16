# Northstar Retail Support — local demo image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip freeze > /app/requirements.lock

COPY northstar ./northstar
COPY .env.example README.md ./

# Non-root user; settings (including saved keys) live in the /data volume, mode 0600.
RUN useradd --uid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin northstar \
 && mkdir -p /data /certs \
 && chown northstar:northstar /data \
 && chmod 700 /data

USER northstar

# Inside the container the app must listen on all container interfaces so Docker can forward
# the port. Publish it ONLY on the host loopback: -p 127.0.0.1:5065:5065 (see README).
ENV NORTHSTAR_HOST=0.0.0.0 \
    NORTHSTAR_PORT=5065 \
    NORTHSTAR_DATA_DIR=/data \
    NORTHSTAR_EXTRA_CA_DIR=/certs

VOLUME ["/data"]
EXPOSE 5065

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; r=urllib.request.Request('http://127.0.0.1:5065/healthz', headers={'Host':'127.0.0.1:5065'}); sys.exit(0 if urllib.request.urlopen(r, timeout=4).status==200 else 1)"]

CMD ["python", "-m", "northstar"]
