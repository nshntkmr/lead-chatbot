FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY static ./static
# Mount your data folder at /app/data and a volume for app.db, or bake data in:
COPY data ./data
ENV APP_DB_PATH=/app/state/app.db
RUN mkdir -p /app/state
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
