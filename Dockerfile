FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY static ./static
# Only the small versioned files the answers depend on go into the image. The CSV / Excel extracts are never
# copied: mount the folder that holds them at /app/source (.dockerignore keeps them out of the build context too).
COPY data/context*.md data/suggestions*.txt data/column_notes*.csv data/*Dictionary*.csv ./data/
# /app/state holds what the app writes (users and chats, the warehouse built from the extracts): mount a volume.
ENV SOURCE_DIR=/app/source     APP_DB_PATH=/app/state/app.db     WAREHOUSE_PATH=/app/state/warehouse.duckdb
RUN mkdir -p /app/source /app/state
# SSH server for Azure App Service's SSH console, so `python -m scripts.manage_users …` can be run against the
# live database. Port 2222 and root / Docker! are App Service's fixed convention; the port is reached only
# through the platform after Azure sign-in. Do not publish 2222 when running the image anywhere else.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* && echo "root:Docker!" | chpasswd
COPY docker/sshd_config /etc/ssh/sshd_config
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh /etc/ssh/sshd_config && chmod +x /entrypoint.sh
EXPOSE 8000 2222
CMD ["/entrypoint.sh"]
