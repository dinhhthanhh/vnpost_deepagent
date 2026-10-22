FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data HF_HOME=/data/cache/huggingface
WORKDIR /opt/chatbot
COPY pyproject.toml ./
COPY terminology.json* ./
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY examples/ ./examples/
RUN pip install --no-cache-dir -e ".[local-embedding]" && \
    useradd --uid 10001 --create-home chatbot && \
    mkdir -p /data/cache && chown -R chatbot:chatbot /data
COPY --from=ui /ui/dist/ ./frontend/dist/
USER chatbot
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-proxy-headers"]
