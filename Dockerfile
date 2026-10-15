FROM node:24-bookworm-slim AS web
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS engine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    COOLPILOT_DATA=/app/data OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 coolpilot \
    && mkdir -p /app/data && chown coolpilot:coolpilot /app/data
COPY coolpilot/ ./coolpilot/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
USER coolpilot

FROM engine AS app
COPY --from=web /build/dist /app/web/dist
EXPOSE 8000
CMD ["uvicorn", "coolpilot.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
