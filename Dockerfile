# syntax=docker/dockerfile:1

# ---- build stage: resolve dependencies into a self-contained venv ----------
FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---- runtime stage --------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=SearchSmartly.settings

# Unprivileged runtime user; /data holds the SQLite file and any mounted
# import files, and is the only path the app needs to write to.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser
VOLUME ["/data"]
EXPOSE 8000

# Checks the app can answer, not merely that the process exists. The admin
# login page is the only guaranteed route in this project.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/admin/login/', timeout=4).status == 200 else 1)"

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "SearchSmartly.wsgi:application"]
