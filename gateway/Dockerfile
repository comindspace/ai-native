FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GATEWAY_TRANSPORT=streamable-http \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssh-client git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md MANIFEST.in ./
COPY gateway*.py ./
COPY gateway_mcp ./gateway_mcp
COPY gateway-tools.json gateway-policy.json gateway-company-indexes.json gateway-factory-projects.json ./
COPY migrations ./migrations

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["gateway-mcp", "--transport", "streamable-http"]
