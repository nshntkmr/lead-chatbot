"""Force a rebuild of data/warehouse.duckdb from the CSV/Excel files in data/.
The app also rebuilds automatically on start when a data file is newer."""
import logging

from app.data import build_warehouse

logging.basicConfig(level=logging.INFO, format="%(message)s")
build_warehouse(force=True)
print("Done.")
