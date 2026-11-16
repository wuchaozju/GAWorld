FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend

ARG FRONTEND_BASE_URL=/
ARG VITE_API_BASE_URL
ARG VITE_BILIBILI_VIDEO_BVID
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
ENV FRONTEND_BASE_URL=${FRONTEND_BASE_URL}
RUN FRONTEND_BASE_URL=${FRONTEND_BASE_URL} VITE_API_BASE_URL=${VITE_API_BASE_URL} VITE_BILIBILI_VIDEO_BVID=${VITE_BILIBILI_VIDEO_BVID} npm run build

FROM python:3.12-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libpq-dev \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY requirements.txt ./
COPY requirements-ci.txt ./

COPY requirements-gaworld.txt ./

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --default-timeout=1000 -c requirements-ci.txt -r requirements.txt \
    && pip install --no-cache-dir lxml-html-clean \
    && pip install --no-cache-dir --default-timeout=1000 -r requirements-gaworld.txt

COPY src ./src
COPY scripts ./scripts

# Install the application code (--no-deps is safe here because we installed requirements above)
RUN pip install --no-cache-dir --no-deps .

RUN rm -rf ./frontend/dist
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
COPY docker/backend-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV FOS_FRONTEND_DIST_PATH=/app/frontend/dist

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
