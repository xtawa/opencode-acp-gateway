FROM node:22-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM node:22-bookworm-slim AS opencode
ARG OPENCODE_VERSION=1.18.34
RUN npm install --prefix /opt/opencode --no-audit --no-fund opencode-ai@${OPENCODE_VERSION}

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 gateway && useradd --uid 10001 --gid gateway --create-home gateway
WORKDIR /app
COPY pyproject.toml ./
COPY gateway/ ./gateway/
RUN pip install --no-cache-dir .
COPY --from=opencode /usr/local/bin/node /usr/local/bin/node
COPY --from=opencode /opt/opencode /opt/opencode
COPY --from=web /build/web/dist ./web/dist
RUN mkdir /data && chown gateway:gateway /data
USER gateway
ENV GATEWAY_HOST=0.0.0.0 GATEWAY_PORT=8080 GATEWAY_DATA_DIR=/data \
    GATEWAY_OPENCODE_BINARY=/opt/opencode/node_modules/.bin/opencode PYTHONUNBUFFERED=1
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["python", "-m", "gateway"]
