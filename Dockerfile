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
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
