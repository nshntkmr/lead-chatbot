# ACO Data Assistant — project context for Claude Code

This is the complete handover for the `lead-chatbot` repository: what the app is for, who uses it, how it is built, what every file does, what the data and the column dictionary contain, which decisions were made and why, and what is still open. Read this before changing anything; `CLAUDE.md` is the short version that loads automatically.

Repo: https://github.com/nshntkmr/lead-chatbot · Deployed copy: `C:\Users\nisha\ACO-Lead-Document\aco-chat-app` (Windows, Python venv in `.venv`) · App version at handover: **2026.10.02-1**.

---

## 1. Purpose and end users

A login-protected web app in which business users chat with Claude about two CMS ACO financial-model extracts (one row per TIN). Claude answers by running SQL against a read-only DuckDB copy of the data and shows charts and tables in the reply. The user wanted "the same interface as Claude" but scoped to their data, with login, and with charts.

**Who asks the questions:** actuaries, the CEO, CFO and Chief Strategy Officer of a US healthcare organization (home-health / Medicare analytics). They are evaluating which provider TINs to recruit into an ACO under the CMS **LEAD** model or the **Medicare Shared Savings Program (MSSP)** for performance year 2027.

**The defining use case** (everything else is built around it):

> "I have these 5 TINs — what is my MLR, and which TINs can I include to keep my MLR within 85%?"

followed by conversational refinement ("add Optum", "drop the Mercy one", "what if costs run 3% hot", "compare LEAD vs MSSP for this group"). Conversation context must persist across turns and page reloads.

**How these users judge an answer:** combined MLR, benchmark $, margin $, person-years, whether the target is met, per-TIN detail in a table, and explicit caveats (approximations, overlapping populations, caps). They will cross-check figures in Excel, so every number must come from a query and reconcile to the workbook. "MLR" to them means **expense ÷ benchmark** (medical-loss-ratio style), *not* the MSSP "Minimum Loss Rate".

**Standards the user has set:** the column dictionary is the authoritative definition source; never modify the source CSVs; secrets live only in `.env`; answers were independently reviewed by other tools (Codex, ChatGPT), and the user will keep doing that, so wording precision matters (e.g. "scenario" vs "worst case", "projected" settlement).

---

## 2. Status at handover

Working and verified:

- Two datasets (LEAD, MSSP) with a dataset picker on every new chat; chats stay scoped to one dataset.
- Portfolio tools reproduce the workbooks' own per-TIN results to within rounding (all identities in §7 checked numerically against the CSVs).
- LEAD cohort basis bug fixed (cohorts now sum exactly to the total; High Needs shows as loss-making at ≈101.7% for the test portfolio).
- Per-user token and dollar tracking, persisted in SQLite, with a usage panel and admin per-user view.
- Claude via the Anthropic API **or** Microsoft Foundry (API key or Entra ID). The user runs **Opus 5.5 on Foundry**.
- `TESTING.md`: 37 test cases with golden answers computed from the raw CSVs (also saved in the claude.ai Project as `claude/aco-chat-test-script.md`).

Open items:

1. User to restart and confirm the startup log reads `Ready (app version 2026.10.02-1)` and that the 5-TIN LEAD answer reports High Needs ≈ 101.7% (loss-making). An earlier "fix" looked ineffective because the deployed copy was stale — hence the version stamp.
2. User to run `TESTING.md` against Opus 5.5 on Foundry and report misses.
3. The device folder is not yet a git clone (see README "Working on this project with Claude Code"); a stray empty `.git` with an `index.lock` may exist there from a dry run and should be deleted before `git init`.

---

## 3. Architecture

```
Browser (static/ vanilla JS)  ──SSE──►  FastAPI (app/main.py)
   login, chat list, picker,              │  JWT cookie auth, SQLite (app.db)
   streaming blocks, charts,              ▼
   tables, usage panel                 Agent (app/agent.py)  ──►  Claude (Anthropic API or Foundry)
                                          │   system prompt = schema + domain notes (cached)
                                          │   tools: search_columns, run_sql, create_chart,
                                          │          show_table, portfolio_metrics,
                                          │          portfolio_suggest, compare_programs
                                          ▼
                                Warehouse (app/data.py)  +  PortfolioCalc (app/portfolio.py)
                                          │
                                          ▼
                              DuckDB data/warehouse.duckdb (read-only, rebuilt from data/*.csv)
```

**Life of one question**

1. `POST /api/chat` with `{message, conversation_id?, program?}`. A new chat must name a program when more than one dataset is loaded; it is stored in the conversation's `state` JSON.
2. `Agent.run()` compacts the history if it is over `COMPACT_AFTER_TOKENS`, appends the user turn, and loops up to `MAX_TOOL_ROUNDS` (15): stream a Claude response → execute tool calls in a thread → append `tool_result`s → repeat until `stop_reason != "tool_use"`. On the last round `tool_choice = none` forces a final answer.
3. The system prompt has two blocks: the big static block (template + schema summary + context files, ~15–20k tokens, `cache_control: ephemeral`) and a small dynamic block with the working portfolio (TIN list, target) when one exists. The last message also carries a cache breakpoint.
4. Each tool returns `(text for Claude, UI block for the browser)`. UI blocks are streamed as SSE events and also appended to `ui_messages` so the chat reloads identically.
5. Every API response's `usage` is emitted as a `usage` event; `main.py` prices it (`pricing.cost_usd`), writes a `usage` row, and appends one `{"type":"usage"}` block per answer ("≈ 76,000 tokens · $0.04 · 3 model calls").
6. `store.save_conversation` persists `api_messages` (exact Claude transcript), `ui_messages`, and `state`. If the turn errored, `repair_history` drops dangling tool_use/user turns first.

**Conversation state** (`conversations.state`): `{"program": "LEAD", "portfolio": ["10198331", …], "target_mlr": 0.85}`. It lives outside the transcript, so compaction never loses it, and it renders as chips in the header.

---

## 4. File-by-file reference

### Root

| File | What it is |
|---|---|
| `CLAUDE.md` | Short auto-loaded guide for Claude Code: map, rules, run commands. Points here. |
| `README.md` | Setup (Windows / Mac), Foundry setup, users, data refresh, tuning, two datasets, portfolio tools, long chats, usage & spend, cost, safety, deployment, Claude Code workflow, layout. |
| `TESTING.md` | Golden-answer test script (Parts A LEAD, B MSSP, C behaviour). Expected values were computed from the CSVs, not by the chatbot. Update only when the raw data says so. |
| `.env.example` | Template; Foundry option is the default block. Never commit a real `.env`. |
| `.gitignore` | Excludes `.env`, `.secret_key`, `app.db`, `data/warehouse.duckdb`, `data/*.building`, `__pycache__/`, `.venv/`, and all `data/*.csv|xlsx|xls` **except** `data/column_notes*.csv`, `data/*Dictionary*.csv`, `data/pricing.json`. |
| `requirements.txt` | fastapi, uvicorn[standard], anthropic ≥0.69 (1.9.0 in use), duckdb, pandas, openpyxl, bcrypt, PyJWT, azure-identity (Entra ID only). |
| `start.bat` | One-click Windows start: creates `.venv`, installs, creates `.env` from the example on first run, then runs uvicorn on 0.0.0.0:8000. |
| `Dockerfile`, `.dockerignore` | python:3.12-slim image; copies app/scripts/static/data; `APP_DB_PATH=/app/state/app.db` for a mounted volume. |

### `app/`

**`config.py`** — all settings, read from `.env` (tiny loader, no python-dotenv). Important names:

| Setting | Default | Notes |
|---|---|---|
| `APP_VERSION` | `"2026.10.02-1"` | Constant in code. Bump on every answer-affecting change. Logged at startup, shown in the usage panel. |
| `CLAUDE_PROVIDER` | auto | `anthropic` or `foundry`; auto = foundry when a Foundry resource/base URL is set and no Anthropic key. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_FOUNDRY_API_KEY`, `ANTHROPIC_FOUNDRY_RESOURCE`, `ANTHROPIC_FOUNDRY_BASE_URL`, `FOUNDRY_USE_ENTRA_ID` | | Credentials/provider. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | On Foundry this is the **deployment name**. User runs `claude-opus-5-5`. |
| `MAX_TOKENS` 8000, `MAX_TOOL_ROUNDS` 15, `ANTHROPIC_BETAS` "" | | |
| `COMPACT_AFTER_TOKENS` 120000, `COMPACT_KEEP_TURNS` 6, `SUMMARY_MODEL` "" | | History compaction. |
| `PRICE_MULTIPLIER` 1.0 | | 1.1 for a Foundry US Data Zone deployment. |
| `TEXT_COLUMNS` | TIN, NPI, CCN, ZIP, two "prevalence matched TIN" columns | Forced to text on load. |
| `PROGRAM_KEYWORDS` `LEAD,MSSP`; `PROGRAM_INFO` | | File-name → program; labels and descriptions shown in the picker. |
| `QUERY_TIMEOUT_SECONDS` 30, `MAX_ROWS_TO_CLAUDE` 200, `MAX_ROWS_TO_UI` 2000 | | |
| `APP_DB_PATH`, `SECRET_KEY` (else `.secret_key` file), `SESSION_HOURS` 12, `COOKIE_SECURE` | | |

**`main.py`** — FastAPI app.
- `lifespan`: `store.init()`, `Warehouse.open()`, `Agent(wh)`; logs `Ready (app version …): <tables>`; warns if no key / no users. Module-level dict is named `runtime` (it used to be `state`, which clashed with the per-chat `state`).
- Auth: `/api/login` (bcrypt verify; 8 failures per IP → 15-minute lockout), `/api/logout`; JWT HS256 in an httpOnly `session` cookie; `current_user` dependency.
- `/`, `/login` serve the static pages (no-store). `/api/config` (app name), `/api/me` (user + programs with rows/columns/sources and up to 4 starter suggestions from `data/suggestions-<program>.txt`).
- Conversations: list/get/rename/delete; get returns `ui_messages` + `state`.
- `/api/usage?conversation_id=` → `store.usage_summary` + `rate_card` + provider + app_version + note; admins also get `all_users`.
- `/api/chat` streaming (described in §3). `_busy` set prevents two answers in one chat at once (409). `_friendly_error` maps SDK exceptions to user text and is Foundry-aware (AuthenticationError, NotFoundError = wrong deployment name, PermissionDeniedError = RBAC).

**`agent.py`** — Claude integration.
- `TOOLS`: `search_columns(keywords, table?)`, `run_sql(sql, purpose)`, `create_chart(title, chart_type, sql, x, y[], point_label?, x_label?, y_label?, value_format?)`, `show_table(title, sql)`, `portfolio_metrics(tins?, action set|add|remove|current, save?, target_mlr?, expense_change_pct?, benchmark_change_pct?)`, `portfolio_suggest(target_mlr, tins?, exclude_tins?, name_like?, spending_class?, min/max_person_years?, limit?)`. `COMPARE_TOOL` (`compare_programs(tins?)`) is added only when more than one program has a calculator.
- `SYSTEM_TEMPLATE`: 10 working rules (every number from a query; quote identifiers; search_columns when unsure; IDs are text; aggregate in SQL; when to chart/table; answer style; say when data can't answer; **rule 9**: portfolio questions go through the portfolio tools, never average MLRs, lead with combined figures, use the tool's own numbers rather than recomputing; DuckDB dialect). Then `# Data` (schema summary) and the context files.
- `make_client()`: `AsyncAnthropic` or `AsyncAnthropicFoundry`. Foundry quirks handled: the SDK reads `ANTHROPIC_FOUNDRY_RESOURCE`/`_BASE_URL` from the environment and refuses both, so the unused one is popped during construction; Entra ID uses the **sync** `DefaultAzureCredential` wrapped in `asyncio.to_thread` (the async credential needs aiohttp).
- `Agent.__init__`: one `PortfolioCalc` and one system text per program (shared `context.md` + `context-<program>.md`).
- `_run_tool` dispatch; `_chart` validates columns and builds Chart.js-ready datasets (scatter supports `point_label`); `_portfolio_metrics` builds a table block with a TOTAL row, "MLR %" column, subtitle, and titles prefixed "Stress test (…)" or "What-if ·" when the saved portfolio is not changed; `_portfolio_suggest` tables the largest candidates; `_compare` builds a Measure × program table.
- `run()` loop (§3), `_compact_if_needed` (summarizes older turns with `SUMMARY_MODEL`, keeps last 6 exchanges verbatim, returns a usage event), `_usage_event`, `_state_text`, `_prepare` (deep-copies history, trims tool results older than the current turn to 1,500 chars, adds the cache breakpoint), `repair_history`.

**`data.py`** — data layer.
- `detect_program(filename)`: first `PROGRAM_KEYWORDS` keyword found in the file name (case-insensitive), else `DATA`. `_is_dictionary`: "dictionary" in the name. `_data_files()` lists `data/*.csv|xlsx|xlsm|xls` **excluding** dictionary files and `column_notes*`.
- `build_warehouse(force)`: rebuilds `warehouse.duckdb` when any source is newer. Large CSVs are read with pandas (DuckDB's sniffer failed on the 122 MB file) with `TEXT_COLUMNS` forced to string, then registered into DuckDB. Writes `_tables(table_name, source_file, program)` and `_column_dictionary` (standardized dictionary + `program` column). Uses a `*.building` temp file.
- `Warehouse.open()`: opens read-only with `enable_external_access=false` and locks configuration; loads `Column` objects (table, name, dtype, constant value, dictionary link, note kind/text); links dictionary entries (exact name / cell `SHEET__CELL` only for the dictionary's own program / name pattern); applies `_load_notes(program)` from `data/column_notes-<program>.csv` (exact names and `^regex` rows); `_annotate_constants` marks columns with one distinct value as `= value`; `_build_programs`.
- `schema_summary(program, max_chars=90_000)`: grouped listing — `_family_key` collapses variants like `[2024 ESRD]`, `(B26)`, `… | HN | BY2 2025` into one line per family with the variant list, so 1,235 / 2,605 columns fit in ~15–20k tokens. Label cells are aggregated into a single "Worksheet label/header cells … ignore" line.
- `search_columns(keywords, table, limit=25, program)`: keyword match over column names, notes and dictionary text; label cells are skipped unless matched by exact name and always ranked last; each match includes type, constant, note (kind + text), dictionary definition/units/formula, and a quick profile (`_profile`: non-null count, min/max/mean or top values). Also returns related dictionary entries.
- `query(sql, max_rows)`: single `SELECT` only (rejects anything else), 30-second interrupt timer, returns `{columns, rows, row_count, truncated}` or `{error}`.

**`dictionary.py`** — `Entry` (header, units, definition, notes, sheet, cell, formula, source_type), `standardize(df)` (tolerant to column-name variants), `Dictionary.link(column)` (exact → cell → pattern, with `_norm` that strips cohort/year tokens so `SAS Raw beneficiaries [2024 ESRD]` links `Raw beneficiaries [2024 HN]`), `Dictionary.search(terms)`.

**`portfolio.py`** — deterministic math (full identities in §7). `corridor_share`, `clean_tins` (accepts str/int/list; splits on whitespace/commas; strips dashes), `ProgramSpec` dataclass (SQL expressions for tin/npi/org/class/person-years/benes/benchmark $/expense $, cohorts, extra sums, params), `LeadSpec.share/worst_case`, `MsspSpec.share/worst_case`, `build_spec(wh, program)` (detects LEAD or MSSP by required headline columns), `Row`, `PortfolioCalc.metrics/suggest`, `compare_programs`.

**`store.py`** — SQLite via `sqlite3` (foreign keys on, one connection per call). Tables `users`, `conversations`, `usage` (schema below). Functions: `init`, `upsert_user`, `delete_user`, `list_users`, `verify_user`, `get_user`, `create_conversation(username, title, state)`, `list_conversations` (includes `program` from state), `get/save/rename/delete_conversation`, `record_usage`, `usage_summary(username, conversation_id)` → periods `today / month / all_time / this_chat` (tokens by type, cost, calls), `by_model`, `recent_chats`; `usage_all_users()`.

**`pricing.py`** — `DEFAULT_RATES` USD per MTok keyed by model-name substring (longest match wins): opus-5-5 4/20/5/0.20, sonnet-5-5 2/10/2.5/0.20, haiku-4-5 1/5/1.25/0.10, plus older models and the Fable/Mythos 5.x tiers. `data/pricing.json` can add deployment names. `cost_usd()` returns `(usd × PRICE_MULTIPLIER, rate_known)`; `rate_card()` for the UI.

### `static/`

- `index.html` — shell: sidebar (brand, New chat, chat list, footer with avatar / name+spend button / sign-out), top bar (title, program chip, portfolio chip), empty state (greeting, **program picker**, data chip, suggestions), thread, composer, usage modal.
- `app.js` (567 lines, vanilla, IIFE) — API helper, number formatting (`fmt` with currency/percent/compact), sidebar grouping by day with program mini-tags and rename/delete menu, `pendingProgram` picker (composer disabled until a dataset is chosen when >1), `renderState` (chips), block renderers: text (marked + DOMPurify), tool line (expandable SQL), chart card (Chart.js 4.5.1, palette, horizontal/stacked/pie/scatter, tick formatting, label truncation, PNG download), table card (sortable, CSV download, TOTAL row styling, subtitle), usage line, error. SSE reader with AbortController (stop button). Usage: `money()`, `refreshSpend()` (footer "$x this month · $y all time"), `openUsage()` modal (KPIs, token breakdown, by model, recent chats, admin all-users table, rate card, note + app version).
- `app.css` — theme tokens, layout, mobile sidebar/scrim, picker cards, chips, cards, modal.
- `login.html` — sign-in form posting to `/api/login`.
- `vendor/` — `marked.min.js` (12), `purify.min.js` (DOMPurify 3), `chart.umd.min.js` (4.5.1). No CDN at runtime (except the Inter font link).

### `scripts/`

- `manage_users.py` — `add <user> [--name] [--admin] [--password]`, `passwd`, `remove`, `list`.
- `rebuild_data.py` — `build_warehouse(force=True)`.
- `make_lead_notes.py` — generates `data/column_notes-lead.csv` (~355 rows) from rules established by value fingerprinting of raw cells. **Edit this script, not the CSV.**

### `data/` (committed part)

- `context.md` — shared notes (identifiers, MLR definition vs Minimum Loss Rate, PBPM/person-year rules, dictionary scope, no geography, prevalence columns, BY3 partial year, portfolio rules, abbreviations).
- `context-lead.md` — LEAD scenario, column-name traps, CMS LEAD facts, workbook constants and corridor tables, calculation chain, verified portfolio math and wording rules.
- `context-mssp.md` — MSSP rules in the workbook (ENHANCED sharing, caps not applied, regional weights, HEBA, risk caps, financial guarantee), CY2027 proposed-rule caveat, identities, chain, tips.
- `column_notes-lead.csv` — `column,kind,definition`; kinds: label 91, duplicate 89, raw 124, metric 39, parameter 12.
- `MSSP_TIN_Column_Dictionary.csv` — the column dictionary (§5.3).
- `suggestions-lead.txt`, `suggestions-mssp.txt` (4 starter questions each), `suggestions.txt` (empty fallback).
- Not committed (must be copied in): `LEAD_TIN_All_Components_BY3_200plus.csv` (122 MB), `MSSP_TIN_All_Components_BY3_200plus.csv` (302 MB), generated `warehouse.duckdb`.

---

## 5. The data

### 5.1 The two extracts

| | LEAD | MSSP |
|---|---|---|
| File | `LEAD_TIN_All_Components_BY3_200plus.csv` | `MSSP_TIN_All_Components_BY3_200plus.csv` |
| Table | `lead_tin_all_components_by3_200plus` | `mssp_tin_all_components_by3_200plus` |
| Shape | 11,865 TINs × 1,235 columns (19 TINs have zero benchmark) | 9,419 TINs × 2,605 columns |
| Model | CMS LEAD, PY2027, Global risk, renewing ACO from REACH, prospective alignment | MSSP ENHANCED, PY2027, prospective, BY1–3 weighted 1/3 each |
| Cohorts | Aged & Disabled (AD), High Needs (HN), ESRD | ESRD, Disabled, Aged/dual, Aged/non-dual |
| Headline columns | `TIN`, `NPI`, `Organization`, `ACO spending classification`, `Person years after exposure adjustment`, `Total cohort beneficiaries \| 2026`, `Benchmark PBPM before discount`, `Benchmark PBPM after discount and earned quality`, `Projected expense PBPM`, `Total benchmark`, `Pre-sharing MLR`, `Gross margin / total savings before risk corridors`, `Settlement \| …`, `Financial guarantee amount`, `Updated benchmark PBPM \| <cohort> \| PY2027`, `Projected expense PBPM \| <cohort> \| PY2027`, `Person years by cohort \| <cohort> \| PY2027` | `TIN`, `NPI`, `Organization`, `Projected person years`, `Projected beneficiaries`, `Projected benchmark`, `Projected expenditures`, `Pre-sharing MLR`, `Gross margin before sharing`, `Shared savings - original model`, `Shared losses signed - original model`, `Net shared result - original model`, `MSSP Shared Saving Losses — … (Bnn)` cells |
| Identifier overlap | `Input notes` flags NPIs shared by several TINs | `Qualifying TINs sharing this NPI - count` > 1 for 107 NPIs |

"200plus" = only TINs with ≥ 200 beneficiaries. 9,234 TINs appear in both files. Each row models the TIN as a standalone ACO; the figures are projections, not settlements. Every row shares one scenario, visible as `= value` constants in the schema.

Column-naming conventions: LEAD uses `Metric | cohort | year` and `<Sheet>__<Cell>` raw cells (`PROSP__G3`); MSSP uses `<Sheet> — <label> [<context>] (<cell>)`, `SAS … [<year> <cohort>]`, and `<year> MSSP claims - <cohort> <category> paid PMPM|USD`.

### 5.2 Column traps (why `column_notes-lead.csv` exists)

- About 100 LEAD columns are **worksheet label cells**: they hold a caption or a year in every row. The worst-named: `ESRD` (= 2024), `High Needs (HN)` / `High Needs (HN) - 2025` (= 2025), `Risk Score [Aged & Disabled (A&D)]` (= 2026), `Beneficiary Counts [...]`, `Renormalization Factors - [...]`, `Trend Factor`, `Historical Benchmark Calculation`. The user initially read `High Needs (HN) - 2025` as HN data for 2025; it was proven to be a label by its constant value. These are excluded from search (unless named exactly) and listed in the schema as "ignore".
- `Benchmark discount` is a **rate** (0.03 / 0.0175); `Administrative add-on` is total **dollars**.
- Many exact duplicates (same values every row): `Spending classification` = `ACO spending classification`; `Benchmark PBPM after discount` = `… after discount and earned quality` (quality score 1); `Retained savings or losses after risk corridors` = `Settlement | shared savings or losses`; etc. Notes of kind `duplicate` name the canonical column.
- `Exposure retention factor (workbook label: Churn Rate)` is a retention share (~0.97).
- Raw cells (`PROSP__*`, `Assignable__*`, `National […]`, `PQEM__*`) were decoded by value fingerprinting (a raw cell is called a duplicate only when identical to a named column in every row).
- MSSP: `Pre-sharing MLR` (expense ÷ benchmark) vs `Minimum Loss Rate (%)` (−0.5% threshold) — the "MLR collision". Cohort cells may contain `'-'` as text, hence `TRY_CAST` (`_n()` in portfolio.py).

### 5.3 The column dictionary

`data/MSSP_TIN_Column_Dictionary.csv`: 2,605 rows (one per MSSP column), 9 fields: `database_ordinal`, `header`, `units`, `definition`, `source_type`, `sheet`, `cell`, `original_formula`, `notes`.

- `source_type`: model_cell 1,861 · cohort_field 432 · year_total 48 · headline_or_audit 38.
- `units` (top): USD/person-year 512, factor 444, risk score 310, beneficiaries 271, ratio 206, USD/member-month 156, USD 155, member-months 139, text 115, year/period 81.
- `sheet` (17): SAS cohort inputs, MSSP Assumptions, MSSP Assignable, MSSP ACPT, MSSP Historical Benchmark, MSSP Parameters, MSSP PROSP, MSSP Trend Factor, MSSP Regional Adjustment, MSSP Updated Benchmark, SAS total inputs, MSSP Prior Savings Adj, MSSP Shared Saving Losses, MSSP Inputs by Track, MSSP PY Risk, MSSP Health Equity Adj, MSSP PROSP COUNTY.
- `original_formula` holds the workbook's Excel formula for 1,103 entries — the authoritative description of how a figure is computed; `search_columns` returns it.

How it is used: loaded into `_column_dictionary` with a `program` column (MSSP). Linking to data columns: exact header match; `SHEET__CELL` position match **only for MSSP** (LEAD sheets have different layouts, so cell links there were wrong and were removed); name-pattern match with cohort/year tokens normalized. For LEAD ≈ 245 columns link by pattern; the rest are covered by the LEAD column notes, which take precedence. Dictionary entries are also searchable on their own, and "label" cells are never matched to dictionary definitions.

### 5.4 Domain essentials (details in `data/context-*.md`)

LEAD (Long-term Enhanced ACO Design, 2027–2036, successor to REACH): Global option up to 100% savings/losses with corridors 0–15% kept 100%, 15–35% 50%, 35–50% 25%, >50% 10%; 2% sequestration; discount 1.75% (High Spending) / 3% (Low Spending); 1.5% admin add-on for High Spending; quality withhold 3% (fully earned back here, score = 1); Base PCC 3.164% + Enhanced PCC 3.836% ≈ 7% (Enhanced PCC repaid at settlement); financial guarantee 4% × annualized BY3 cost; BY3 = 2026 is Jan–May ×2.4 ×1.0612 blended 30/70. Risk caps ±3% (AD, ESRD) / ±4% (HN). Benchmark update = 2/3 national-regional trend + 1/3 ACPT.

MSSP ENHANCED (this workbook): MSR/MLR band ±0.5% of benchmark; 75% of savings above, 40% of losses below; caps 20% / 15% of benchmark **not applied** by the workbook (53 TINs exceed, $23.7M overstated); regional adjustment weight 35% below region / 15% above, caps +5% / −1.5%; HEBA eligibility at 15% dual/LIS share here (CMS says 20%); financial guarantee 0.5% × BY3 cost; sequestration not modeled. The July 2026 CY2027 PFS proposed rule would change several of these — proposals only.

---

## 6. Claude integration details

- **Model:** `ANTHROPIC_MODEL` is the Foundry deployment name. The recommendation given: Sonnet 5.5 is fine for single-metric questions and cheaper; Opus 5.5 is stronger on multi-step portfolio reasoning and wording discipline — the user chose Opus 5.5. A 1M context is not needed because state is explicit and history is compacted.
- **Prompt caching:** static system block cached; dynamic portfolio block after it; cache breakpoint on the last message. First question of a chat pays a cache write (~25k tokens); later ones mostly cache reads.
- **Compaction:** when the estimated transcript exceeds 120k tokens, everything but the last 6 exchanges is summarized (goals, TIN lists, targets, key numbers with column names) and replaced by a summary turn. Older tool results are trimmed to 1,500 chars on every call.
- **Betas:** `ANTHROPIC_BETAS` is passed through as the `anthropic-beta` header if set.
- **Foundry:** `AsyncAnthropicFoundry(resource=… | base_url=…, api_key=… | azure_ad_token_provider=…)`. Billing in Claude Consumption Units at the same USD rates; US Data Zone ×1.1 → `PRICE_MULTIPLIER=1.1`. Errors: wrong deployment name → NotFoundError; missing RBAC → 403.
- **Usage/spend:** every call (chat and summary) is one `usage` row; cost = tokens × rate card ÷ 1e6 × multiplier; `rate_known=0` when the model name matches no rate (shown as "unpriced").

---

## 7. Portfolio math (all verified against the CSVs)

Common: combined **MLR = Σ expense $ ÷ Σ benchmark $** (never an average); margin = benchmark − expense (savings positive); room under target = target × benchmark $ − expense $ per TIN (`room_under_target_usd` in tool output, `Row.headroom()` in code); a set meets the target iff the sum ≥ 0 (this makes "fewest TINs to add/remove" a sort by that value). Stress test rescales every TIN's expense/benchmark by a percentage and never saves the portfolio.

LEAD: benchmark $ = `Benchmark PBPM after discount and earned quality` × `Person years after exposure adjustment` × 12 = `Total benchmark`; expense $ = `Projected expense PBPM` × PY × 12; shared = corridor_share(margin) then −2% sequestration; `total_monies_owed = net shared + Settlement | enhanced PCC repayment`; financial guarantee = Σ `Financial guarantee amount` (= 4% × Σ BY3 claim payments × 2.4); quality withhold at risk = 3% of benchmark. **Cohorts:** `Updated benchmark PBPM | k | PY2027` is pre-discount, so it is multiplied by (`Benchmark PBPM after discount and earned quality` ÷ `Benchmark PBPM before discount`) — without this, cohorts summed to $180.0M vs a $174.6M total and High Needs looked profitable (this was the bug Codex/ChatGPT flagged). `shared_loss_if_loss_equals_benchmark_usd` = 33.75% of benchmark is a **scenario** (LEAD corridors have no ceiling); MSSP's `max_shared_loss_under_enhanced_cap_usd` = 15% of benchmark is a **hard cap**.

MSSP: benchmark $ = `Projected benchmark`; expense $ = `Projected expenditures`; params read from workbook constants (MSR 0.005 from B26, sharing 0.75 from B36, loss 0.40 from B37, savings cap 0.20 from Inputs by Track G8, loss cap 0.15); status Saving / Losses / No shared savings; both uncapped and capped figures returned (`cap_binding`). Cohorts: `Updated Benchmark Expenditures ($) — k (D35–D38)` × `Projected cohort person years — k (C15–C18)`; expense `Projected expense — k (B10–B13)` × PY. Financial guarantee B47; HEBA C11 × PY.

Warnings emitted: unknown TINs, zero-benchmark TINs excluded, TINs sharing one NPI (double-count), mixed High/Low Spending (approximation; a real ACO gets one classification).

Golden numbers for the reference portfolios (full list in `TESTING.md`): LEAD 5 TINs 10198331, 10211494, 10211501, 10211534, 10211551 → MLR 97.27%, benchmark $174,608,462, margin $4.77M, 10,044 PY, net shared $4.67M, EPCC repayment −$6.90M, total monies owed −$2.23M, guarantee $6.32M; cohorts A&D 91.55% / +$6.72M, HN 101.68% / −$1.47M, ESRD 106.56% / −$0.48M. Adding 910214500 (Optum Care Washington) and 271081647 (UNC Physicians Network) → 83.6%. MSSP 3 TINs 941156581, 363738206, 340714585 → MLR 98.16%, benchmark $3.69B, shared $50.9M. Trap: 954373071 / 954415773 / 721524529 share NPI 1235107566.

---

## 8. Storage schema (`app.db`)

```sql
users(username PK, display_name, password_hash bcrypt, is_admin, created_at)
conversations(id PK, username FK, title, api_messages JSON, ui_messages JSON, state JSON, created_at, updated_at)
usage(id, username, conversation_id, ts, model, provider, kind chat|summary,
      input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, cost_usd, rate_known)
```
`state` was added later with an `ALTER TABLE` migration in `store.init()`. Delete `usage` rows to reset spend.

---

## 9. Security and safety

- Warehouse opened read-only; `enable_external_access=false` and configuration locked, so SQL cannot read other files or the network. Only single `SELECT` statements; 30 s timeout.
- Only query results (≤ 200 rows per call) go to the model, never whole files. The data has TIN/NPI identifiers, no member-level data.
- bcrypt passwords, httpOnly JWT cookie (12 h), IP lockout after 8 failed logins, each user sees only their own chats; admins additionally see the all-users usage table.
- Secrets only in `.env`; `.secret_key` auto-generated. Set `COOKIE_SECURE=true` behind HTTPS.

---

## 10. Operations

- **Start / restart (Windows):** `start.bat`, or `.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000`. Stop with Ctrl+C. Watch for `Ready (app version 2026.10.02-1): lead_… (11,865 rows), mssp_… (9,419 rows)`.
- **Users:** `.venv\Scripts\python -m scripts.manage_users add nishant --name "Nishant" --admin`.
- **Data refresh:** drop new files in `data\`, restart (auto-rebuild when a source is newer; ~5–40 s), or `python -m scripts.rebuild_data`. After a LEAD extract change, re-run `python -m scripts.make_lead_notes` and re-verify the fingerprinted raw cells.
- **Deployment verification:** the earlier stale-copy incident was caught by md5-comparing every file between the authoring copy and the device, and by the `APP_VERSION` stamp. Keep doing both after a deploy.
- **Docker / Azure:** see README (Container Apps or App Service; mount `/app/state`; Entra ID via Easy Auth header in `current_user`).

---

## 11. History: problems hit and how they were solved

| Problem | Resolution |
|---|---|
| DuckDB CSV sniffer failed on the 122 MB LEAD file | Read with pandas (forced text ID columns), register into DuckDB |
| Column notes CSV was ingested as a data table | `_data_files()` excludes `column_notes*` |
| Dictionary cell-position links wrong for LEAD | Cell links only for the dictionary's own program; LEAD raw cells decoded by value fingerprinting |
| `ESRD` search returned the label cell first | Labels skipped unless exact name, ranked last |
| `clean_tins` iterated characters of a string | Accept str/int as a single value |
| `state` module dict clashed with per-chat `state` | Module dict renamed `runtime` |
| `KeyError 'rows'` on MSSP HEBA (text `'-'` cells) | `TRY_CAST` via `_n()` |
| Foundry SDK: "base_url and resource are mutually exclusive" (reads both env vars) | Pop the unused env var during client construction |
| `azure.identity.aio` needs aiohttp | Sync credential in `asyncio.to_thread` |
| LEAD cohort MLRs ~3% too low; cohorts didn't sum to total | Scale cohort benchmark by after-discount ÷ before-discount |
| "Worst-case loss" mislabel | LEAD: scenario with note; MSSP: hard cap with note; prompt and context wording updated |
| Fix "didn't work" after restart | Deployed `portfolio.py`/`context-lead.md` were stale; re-deployed, md5-verified, added `APP_VERSION` |
| Chart currency ticks / label clipping on mobile | Formatting and truncation in `app.js` |
| 302 MB MSSP copy to the device timed out | Chunked `dd` copy, `cmp`-verified |
| pandas ingest needs the whole table in RAM (~8 GB at 200,000 rows × 2,605 columns) | Data CSVs now load through DuckDB's reader (`_load_csv`: explicit dialect + `strict_mode = false`, which is what the sniffer failure above needed). Verified cell-for-cell against the pandas-built warehouse; integer columns with blanks are now BIGINT instead of DOUBLE |
| DuckDB's multi-threaded load also ran out of memory on the wide table (100,000 rows, 24 GB machine) | Build is single-threaded with `BUILD_MEMORY_LIMIT` (4 GB default): 109 s and 4 GB peak for 103,609 × 2,605 |
| Start-up profiled every column on each start (~13 s at 200,000 rows) | Profile stored in `_column_stats` at build time; old warehouses fall back to profiling at start |
| `SELECT *` (7 MB for 200 rows) or a 10,000-TIN portfolio (2 MB) would overflow the model's context | Size caps on every tool result (`MAX_RESULT_CHARS_*`, `MAX_TINS_TO_CLAUDE`); browser tables capped too |
| Blank expense treated as $0 (MLR 0 %, top candidate) | Such TINs are excluded with a warning in `metrics` and never offered by `suggest` |
| What-if (`save=false`) overwrote the saved target; LEAD chat could query the MSSP table; prompt date fixed at start-up | Target saved only when `save` is true; `Warehouse.query(program=…)` refuses other datasets' tables; date moved to the uncached system block |
| Prompt had to forbid the words "headroom" / "slack" that the tools themselves returned | Tool output renamed to `room_under_target_usd` / `shortfall_to_target_usd`; rule removed |
| `suggest` pulled every candidate row into Python | Screening, ranking and the add-plan run in SQL (window sums); identical output on 154 old-vs-new scenarios |
| `TESTING.md` was manual, so prompt edits could regress silently | `evals/` runs it automatically (54 offline checks, 25 chat cases). First run found two real misses, fixed in `context-lead.md`: the 19 zero-benchmark TINs counted as MLR ≤ 85 %, and an MSSP-only question answered with LEAD counts |

---

## 12. Known limitations and ideas

- No geography columns → "TINs in Texas" cannot be answered (the prompt says so and offers a name filter).
- Model parameters (discount, corridors) cannot be re-run; only expense/benchmark stress tests are offered.
- Mixed High/Low Spending portfolios are approximate (per-TIN classification).
- Distinct NPIs rule out the workbook's known overlap but cannot prove zero beneficiary overlap.
- Spend figures are estimates from token counts; the Azure/Anthropic invoice is authoritative.
- Possible next steps the user has discussed or that follow naturally: run `TESTING.md` on Opus 5.5 / Foundry and fix misses; Entra ID SSO for the app itself; Azure Container Apps deployment; a saved-portfolio library per user; exporting an answer (tables + charts) to Excel/PDF; per-user monthly spend caps.

---

## 13. Change checklist

1. Never touch `data/*_200plus.csv` or the dictionary; never commit `.env`, `app.db`, `.secret_key`, the warehouse or the big CSVs.
2. Keep every identity in §7 true; if `portfolio.py`, `agent.py`, `data.py` or `data/context*.md` change, run `python -m evals.run` (at minimum `--offline`) and add a case to `evals/cases.py` for the new behaviour.
3. Bump `APP_VERSION`; after deploying, confirm the startup log shows it and md5-compare changed files.
4. Edit `scripts/make_lead_notes.py` (not the CSV) for LEAD column notes; keep the dictionary authoritative for MSSP.
5. Keep the front end CDN-free and the SQL path read-only / single-SELECT.
6. Put behaviour in code or tool output first (names, limits, formats); use `data/context*.md` for facts about the data and the prompt rules only for what neither can carry. Prefer context over code when the model's *column choice* is wrong; change `portfolio.py` only when a *number* is wrong, and prove it against the CSV first.
