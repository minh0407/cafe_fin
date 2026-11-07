# Local preview only; native Windows release continues to use its own packaging.
FROM node:24-bookworm-slim@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9 AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN VITE_CAFE_FIN_BROWSER_PREVIEW=1 npm run build && npm run notices

# Bookworm's system SQLite is older than the unchanged core WAL safety gate.
# Pin the official archive and independently check sqlite3.c against release notes.
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS sqlite
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev
ADD --checksum=sha256:83e6b2020a034e9a7ad4a72feea59e1ad52f162e09cbd26735a3ffb98359fc4f https://sqlite.org/2026/sqlite-autoconf-3530100.tar.gz /tmp/sqlite.tar.gz
WORKDIR /tmp/sqlite
RUN tar -xzf /tmp/sqlite.tar.gz --strip-components=1
RUN python -c "import hashlib,pathlib; assert hashlib.sha3_256(pathlib.Path('sqlite3.c').read_bytes()).hexdigest() == '414432ae5719f6cdc485f3927e12c7ad107e2b8c6b434e5df2eadb5312bfabb5'"
RUN mkdir -p /sqlite/lib /sqlite/notices && \
    gcc -O2 -fPIC -shared -Wl,-soname,libsqlite3.so.0 \
      -DSQLITE_THREADSAFE=1 -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_FTS5 \
      -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_MATH_FUNCTIONS \
      -o /sqlite/lib/libsqlite3.so.0 sqlite3.c -lm -ldl -pthread && \
    head -n 50 sqlite3.c > /sqlite/notices/sqlite-source-header.txt
RUN python -c "from pathlib import Path; Path('/sqlite/notices/README.txt').write_text('SQLite 3.53.1, public domain: https://sqlite.org/copyright.html\nOfficial source: https://sqlite.org/2026/sqlite-autoconf-3530100.tar.gz\nRelease/source hash: https://sqlite.org/releaselog/3_53_1.html\nArchive SHA256: 83e6b2020a034e9a7ad4a72feea59e1ad52f162e09cbd26735a3ffb98359fc4f\nsqlite3.c SHA3-256: 414432ae5719f6cdc485f3927e12c7ad107e2b8c6b434e5df2eadb5312bfabb5\nUnmodified amalgamation; compiled as a private shared library.\n', encoding='utf-8')"

FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev --no-editable --no-cache --python /usr/local/bin/python

FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS preview
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LD_LIBRARY_PATH=/opt/cafe-fin-sqlite/lib
WORKDIR /app
COPY --from=sqlite /sqlite/lib/ /opt/cafe-fin-sqlite/lib/
COPY --from=sqlite /sqlite/notices/ /app/notices/sqlite/
COPY --from=dependencies /app/.venv/ /app/.venv/
COPY --from=frontend /build/frontend/dist/ /app/frontend/dist/
COPY --from=frontend /build/desktop/notices/ /app/notices/frontend/
COPY scripts/preview.py /app/scripts/preview.py
RUN python -c "import sqlite3; assert sqlite3.sqlite_version_info == (3,53,1), sqlite3.sqlite_version; c=sqlite3.connect(':memory:'); assert c.execute('select sqlite_source_id()').fetchone()[0] == '2026-05-05 10:34:17 c88b22011a54b4f6fbd149e9f8e4de77658ce58143a1af0e3785e4e6475127e9'; assert c.execute('pragma integrity_check').fetchone() == ('ok',); print('Verified Python SQLite', sqlite3.sqlite_version)"
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 1420
CMD ["python", "/app/scripts/preview.py"]

# No data volume or host port. Only this fixed-provider relay has market egress.
FROM preview AS market-relay
COPY scripts/market_relay.py /app/scripts/market_relay.py
EXPOSE 8080
CMD ["python", "/app/scripts/market_relay.py"]

# Only this stateless gateway joins a publishable bridge. Backend stays isolated.
FROM nginx:1.30.6-alpine@sha256:583b7f2fce1cdb8da5ad5c39ebd3c33b98b87d493190e548bdee1fa8c619c311 AS gateway
COPY scripts/preview/nginx.conf /etc/nginx/preview.conf
USER 101:101
# Check syntax without requiring the runtime Compose DNS name during image build.
RUN sed 's#http://cafe-fin:1420#http://127.0.0.1:1420#' /etc/nginx/preview.conf > /tmp/preview-check.conf && nginx -t -c /tmp/preview-check.conf
EXPOSE 1420
ENTRYPOINT ["nginx"]
CMD ["-c", "/etc/nginx/preview.conf", "-g", "daemon off;"]
