"""Central settings, read from environment variables (or a .env file)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

APP_NAME = os.getenv("APP_NAME", "ACO Data Assistant")
APP_VERSION = "2026.10.02-11"  # bump when app/ or data/context*.md change; printed at startup and shown in the usage panel

# --- Claude ---------------------------------------------------------------
# Where Claude is called: "anthropic" (Claude API) or "foundry" (Claude in Microsoft Foundry / Azure).
# Auto-detected from which credentials are present when CLAUDE_PROVIDER is left blank.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FOUNDRY_API_KEY = os.getenv("ANTHROPIC_FOUNDRY_API_KEY", "")
FOUNDRY_RESOURCE = os.getenv("ANTHROPIC_FOUNDRY_RESOURCE", "").strip()          # e.g. my-foundry-resource
FOUNDRY_BASE_URL = os.getenv("ANTHROPIC_FOUNDRY_BASE_URL", "").strip()          # or the full https://<resource>.services.ai.azure.com/anthropic/
FOUNDRY_USE_ENTRA_ID = os.getenv("FOUNDRY_USE_ENTRA_ID", "false").lower() == "true"
_provider = os.getenv("CLAUDE_PROVIDER", "").strip().lower()
if not _provider:
    _provider = "foundry" if (FOUNDRY_RESOURCE or FOUNDRY_BASE_URL) and not ANTHROPIC_API_KEY else "anthropic"
CLAUDE_PROVIDER = _provider
# On Foundry this is the DEPLOYMENT name (defaults to the model id, e.g. claude-opus-5-5).
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8000"))
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "15"))
# Optional beta features, comma-separated, sent as the anthropic-beta header (e.g. a long-context beta).
ANTHROPIC_BETAS = os.getenv("ANTHROPIC_BETAS", "").strip()
# Long chats: once the stored transcript is estimated above this many tokens, the older part is
# summarized and replaced (the working portfolio is kept separately, so nothing important is lost).
COMPACT_AFTER_TOKENS = int(os.getenv("COMPACT_AFTER_TOKENS", "120000"))
COMPACT_KEEP_TURNS = int(os.getenv("COMPACT_KEEP_TURNS", "6"))
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "")  # blank = same as ANTHROPIC_MODEL
# Spend estimates: list prices × this multiplier (1.1 for a Foundry US Data Zone deployment or inference_geo=us;
# below 1 for a negotiated discount). Per-model rates can be overridden in data/pricing.json.
PRICE_MULTIPLIER = float(os.getenv("PRICE_MULTIPLIER", "1.0"))

# --- Data -----------------------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
# Where the large CSV / Excel extracts are read from. Defaults to DATA_DIR. In a container, point it at a mounted
# volume so the extracts are never part of the image; DATA_DIR then holds only the small versioned files (domain
# notes, column notes, dictionary, suggestions), which are also searched for data files.
SOURCE_DIR = Path(os.getenv("SOURCE_DIR", DATA_DIR))
WAREHOUSE_PATH = Path(os.getenv("WAREHOUSE_PATH", DATA_DIR / "warehouse.duckdb"))
# Columns that must stay text (IDs with leading zeros etc.)
TEXT_COLUMNS = {c.strip() for c in os.getenv(
    "TEXT_COLUMNS",
    "TIN,NPI,CCN,ZIP,2026 prevalence matched TIN (source npi_org),2026 supplied TIN prevalence matched TIN (source npi_org)",
).split(",") if c.strip()}

# --- Programs / datasets ---------------------------------------------------
# A data file belongs to the first program whose keyword appears in its file name (case-insensitive).
# Files matching none go to a generic "DATA" program. Users pick a program when starting a chat.
PROGRAM_KEYWORDS = [k.strip().upper() for k in os.getenv("PROGRAM_KEYWORDS", "LEAD,MSSP").split(",") if k.strip()]
PROGRAM_INFO = {
    "LEAD": {"label": "LEAD model",
             "description": "CMS Innovation Center Long-term Enhanced ACO Design — PY2027 TIN-level projections "
                            "(Global risk option, A&D / High Needs / ESRD cohorts)."},
    "MSSP": {"label": "Medicare Shared Savings Program",
             "description": "MSSP ENHANCED track — PY2027 TIN-level projections (ESRD / Disabled / Aged-dual / "
                            "Aged-non-dual cohorts)."},
    "DATA": {"label": "Data", "description": "Other data files."},
}
QUERY_TIMEOUT_SECONDS = float(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))
# Warehouse build. These extracts are thousands of columns wide, and DuckDB buffers a block of rows per thread
# while loading, so a multi-threaded load of a large file runs out of memory (seen at 100,000 rows x 2,605
# columns on a 24 GB machine). One thread keeps memory within BUILD_MEMORY_LIMIT at any row count (~90 s per
# 100,000 rows of the widest extract). Raise BUILD_THREADS only for narrow files or with plenty of RAM.
BUILD_THREADS = int(os.getenv("BUILD_THREADS", "1"))
BUILD_MEMORY_LIMIT = os.getenv("BUILD_MEMORY_LIMIT", "4GB").strip()
# Memory cap for answering queries, e.g. "2GB" in a small container. Blank = DuckDB's default (80 % of RAM).
QUERY_MEMORY_LIMIT = os.getenv("QUERY_MEMORY_LIMIT", "").strip()
MAX_ROWS_TO_CLAUDE = int(os.getenv("MAX_ROWS_TO_CLAUDE", "200"))
MAX_ROWS_TO_UI = int(os.getenv("MAX_ROWS_TO_UI", "2000"))
# Size caps on a query result (JSON characters), on top of the row caps: these tables have thousands of columns,
# so a SELECT * of a few rows can be megabytes. Rows beyond the cap are dropped and the result is marked truncated.
MAX_RESULT_CHARS_TO_CLAUDE = int(os.getenv("MAX_RESULT_CHARS_TO_CLAUDE", "100000"))
MAX_RESULT_CHARS_TO_UI = int(os.getenv("MAX_RESULT_CHARS_TO_UI", "2000000"))
MAX_CELL_CHARS = int(os.getenv("MAX_CELL_CHARS", "2000"))
# Portfolio tools: per-TIN rows sent to Claude (the largest by benchmark; totals always cover every TIN).
MAX_TINS_TO_CLAUDE = int(os.getenv("MAX_TINS_TO_CLAUDE", "100"))

# --- App / auth -----------------------------------------------------------
APP_DB_PATH = Path(os.getenv("APP_DB_PATH", BASE_DIR / "app.db"))
SECRET_KEY = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    # Stable per-install secret so sessions survive restarts.
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        SECRET_KEY = key_file.read_text().strip()
    else:
        SECRET_KEY = secrets.token_urlsafe(48)
        key_file.write_text(SECRET_KEY)
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
