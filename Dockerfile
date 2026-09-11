FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COUNTERPARTY_DB=/app/data/counterparty.sqlite3 \
    COUNTERPARTY_REQUIRE_INTERNAL_AUTH=1

WORKDIR /app
COPY pyproject.toml ./
COPY counterparty ./counterparty
RUN pip install --no-cache-dir . \
    && groupadd --system counterparty \
    && useradd --system --gid counterparty --home-dir /app counterparty \
    && mkdir -p /app/data \
    && chown -R counterparty:counterparty /app

USER counterparty
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1

CMD ["uvicorn","counterparty.app:app","--host","0.0.0.0","--port","8000","--workers","1","--proxy-headers","--no-server-header"]
