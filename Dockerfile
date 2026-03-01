# ============================================================
# Stage 1: Build Vue 3 frontend
# ============================================================
FROM node:22-alpine AS frontend-builder

WORKDIR /app/web

# Install dependencies (cache layer)
COPY web/package.json web/package-lock.json* ./
RUN npm ci

# Copy source and build
COPY web/ .
RUN npm run build

# ============================================================
# Stage 2: Python FastAPI backend
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python encoding — required for Chinese characters in logs
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUTF8=1

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/
COPY static/ ./static/
COPY assets/ ./assets/

# Copy built frontend into web/dist (served by FastAPI in production mode)
COPY --from=frontend-builder /app/web/dist ./web/dist

# Create writable directories
RUN mkdir -p /app/assets/saves /app/logs

# Railway injects $PORT; fall back to 8002 for local Docker runs
EXPOSE 8002
CMD ["sh", "-c", "uvicorn src.server.main:app --host 0.0.0.0 --port ${PORT:-8002}"]
