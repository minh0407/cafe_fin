# Local preview only; native Windows release continues to use its own packaging.
FROM node:24-bookworm-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9 AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN VITE_CAFE_FIN_BROWSER_PREVIEW=1 npm run build && npm run notices

FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev --no-editable --no-cache --python /usr/local/bin/python

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS preview
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=dependencies /app/.venv/ /app/.venv/
COPY --from=frontend /build/frontend/dist/ /app/frontend/dist/
COPY --from=frontend /build/desktop/notices/ /app/notices/frontend/
COPY scripts/preview.py /app/scripts/preview.py
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 1420
CMD ["python", "/app/scripts/preview.py"]
