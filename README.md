# ACO Data Assistant

A small web app where people sign in and chat with Claude about your spreadsheet data. Claude answers by querying the data, and it can show interactive charts and downloadable tables in its replies.

```
Browser (chat UI) ──► FastAPI server ──► Claude API (tool use)
                            │
                            └──► DuckDB (read-only copy of your CSV / Excel files)
```

Claude never sees the whole file. On each question it:

1. reads the column list (sent once and cached),
2. calls **search_columns** when it's unsure which column fits,
3. runs **run_sql** to compute the numbers,
4. calls **create_chart** or **show_table** to display results. The server runs that SQL itself, so every chart shows real data.

Every figure in an answer comes from a query, and each query can be expanded in the chat to see its SQL.

## Quick start (Windows)

1. Install Python 3.10 or newer from python.org and tick "Add to PATH".
2. Put your `.csv` / `.xlsx` files in `data\`. Every file becomes a table, and every sheet of a multi-sheet workbook becomes its own table. A file with "dictionary" in its name is used for column definitions instead of becoming a table.
3. Double-click **start.bat**. The first run installs packages, creates `.env` and opens it. Paste your `ANTHROPIC_API_KEY`, save, and run `start.bat` again.
4. Create a login in a second terminal in this folder:
   ```
   .venv\Scripts\python -m scripts.manage_users add nishant --name "Nishant" --admin
   ```
5. Open http://localhost:8000.

Other people on your network can use `http://<your-machine-ip>:8000`.

## Quick start (Mac / Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add ANTHROPIC_API_KEY
python -m scripts.manage_users add nishant --admin
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Using Claude through Microsoft Foundry (Azure)

The app talks to Claude through the Anthropic SDK, which has a native Foundry client, so no code changes are needed — only `.env`:

1. In the Foundry portal deploy a Claude model (Discover → Models → *claude-opus-5-5* → Deploy). Note the **deployment name** (defaults to the model id) and, on the deployment's Details tab, the **Target URI** and **Key**.
2. In `.env`:
   ```
   CLAUDE_PROVIDER=foundry
   ANTHROPIC_FOUNDRY_RESOURCE=<resource>        # the first part of the Target URI: https://<resource>.services.ai.azure.com/...
   ANTHROPIC_FOUNDRY_API_KEY=<key>              # or leave blank and set FOUNDRY_USE_ENTRA_ID=true
   ANTHROPIC_MODEL=claude-opus-5-5              # your deployment name
   ```
3. For Entra ID instead of a key: `pip install azure-identity`, give the identity the **Foundry User** role on the resource, sign in with `az login` on the machine running the app (or run it under a managed identity in Azure), and set `FOUNDRY_USE_ENTRA_ID=true`.

Notes: billing goes through the Azure Marketplace in Claude Consumption Units; Opus 5.5 and Sonnet 5.5 have a 1M-token context window on Foundry without a beta flag; choose a **US Data Zone** deployment if inference must stay in the US (Sonnet 5.5 is Global only). Prompt caching, streaming and tool use — everything this app uses — are supported. The Message Batches API is not, but the app doesn't use it. Source: https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry

## Managing users

```
python -m scripts.manage_users add <username> [--name "Full Name"] [--admin]
python -m scripts.manage_users passwd <username>
python -m scripts.manage_users remove <username>
python -m scripts.manage_users list
```

Passwords are stored as bcrypt hashes in `app.db`. Sessions are signed httpOnly cookies that last 12 hours by default. After 8 failed sign-ins, an IP address is locked out for 15 minutes; the count is kept in `app.db`, so it is shared by every worker process and survives a restart. Behind a reverse proxy set `TRUSTED_PROXY_HOPS` (see Deploying), otherwise all users share the proxy's address and one person's typos lock everyone out. Each user only sees their own chat history.

## Updating the data

Replace the files in `data\` and restart the app. It rebuilds `data\warehouse.duckdb` automatically whenever the set of source files changes — a file added, removed, resized or replaced, including by a copy with an older date — which takes about 40 seconds for the current two files. To force a rebuild, run `python -m scripts.rebuild_data`. Stop every running copy of the app first: the warehouse cannot be replaced while another process has it open.

The build streams each CSV through DuckDB on one thread with a memory cap (`BUILD_MEMORY_LIMIT`, default 4 GB), so file size is limited by disk, not RAM. Measured on 200,000-row copies of both extracts (201,705 × 1,235 and 207,218 × 2,605 columns): build 5 minutes, 4.3 GB peak, 2.2 GB warehouse, start-up under a second afterwards.

The app assumes one row per TIN. Several files for one program are fine if they have the same header: they load as one table. If a program ends up with two tables of headline figures, or a TIN on more than one row, the portfolio tools switch themselves off for that program and say why, rather than compute on part of the data.

After changing the data, the prompt or the domain notes, run `python -m evals.run` — it asks the questions in `TESTING.md` and grades the answers (about $1.60 and 4 minutes; `--offline` is free and checks the portfolio math, the guard rails and the plumbing without the model).

## Tuning Claude for your data

| File | What it does |
|---|---|
| `data\context*.md` | Domain notes added to Claude's instructions (see "Two datasets"). These files are the biggest lever on answer quality. |
| `data\column_notes-<program>.csv` | Curated definitions for columns whose names mislead (`column,kind,definition`; a column starting with `^` is a regex). Kinds: `label` (worksheet caption/year cell, excluded from data), `duplicate` (same values as another column), `raw` (workbook cell with an inferred meaning), `parameter`, `metric`. The LEAD file is generated by `python -m scripts.make_lead_notes`; edit the script or the CSV. |
| `data\*Dictionary*.csv` | Column definitions. They are linked to data columns by exact name, by workbook sheet and cell (`PROSP__G3`), or by field pattern (`SAS Raw beneficiaries [2024 ESRD]` ↔ `Raw beneficiaries [2024 HN]`). Every entry can also be searched by Claude. |
| `data\suggestions-<program>.txt` | The up to 4 starter questions shown after picking a dataset, one per line. |
| `.env` → `ANTHROPIC_MODEL` | `claude-sonnet-5-5` (default, fast and cheaper) or `claude-opus-5-5` (stronger on multi-step analysis). |

Restart the app after editing any of these.

## Two datasets: LEAD and MSSP

Each data file is assigned to a **program** from its file name (`PROGRAM_KEYWORDS`, default `LEAD,MSSP`): `LEAD_TIN_…csv` → LEAD, `MSSP_TIN_…csv` → MSSP. When more than one program is loaded, every new chat starts with a dataset picker, and the chat stays scoped to that dataset (its own column list, domain notes, starter questions and portfolio math). The dataset shows as a tag in the header and the sidebar.

| File | Used for |
|---|---|
| `data\context.md` | Notes shared by all datasets (identifiers, MLR definition, portfolio rules). |
| `data\context-lead.md`, `data\context-mssp.md` | Program-specific model notes. Add `context-<program>.md` for any new program keyword. |
| `data\suggestions-lead.txt`, `data\suggestions-mssp.txt` | Starter questions per dataset (`suggestions.txt` is the fallback). |

Program labels and descriptions are in `app/config.py` (`PROGRAM_INFO`). A file matching no keyword goes to a generic "DATA" program.

**compare_programs** gives side-by-side figures for the same TINs under every program (9,234 TINs appear in both files), each under its own sharing rules.

## Portfolio questions

Actuarial and finance users usually ask about *groups* of TINs. Two dedicated tools do that math deterministically (same identities as the workbook, verified to the dollar):

- **portfolio_metrics** — "I have these 5 TINs: what's my MLR?" Combined benchmark $, expense $, margin, MLR (= Σ expense ÷ Σ benchmark, not an average), shared savings after the Global corridors, sequestration, EPCC repayment, and an A&D / High Needs / ESRD split. It also saves the list as the chat's **working portfolio** (shown as a chip in the header), so "add TIN X", "drop the Mercy one", "what's my MLR now" keep working for the whole chat.
- **portfolio_suggest** — "Which TINs can I include and stay under 85%?" Slack against the target, the fewest TINs to remove or add to reach it, and screened candidates (largest by benchmark / margin), with filters by name, spending class and size.

Program-specific math: LEAD applies the Global risk corridors and 2% sequestration; MSSP applies the ENHANCED sharing rules (75% of savings above the 0.5% MSR, 40% of losses beyond it) and reports both the workbook's uncapped figure and the figure with the 20% / 15% caps. Both reproduce the workbook's own per-TIN results to within rounding.

Known approximation (LEAD): each TIN's benchmark carries its own High/Low-Spending classification (discount and regional adjustment). A real ACO gets one classification for the whole population, so mixed portfolios are approximate; the tool says so when it applies.

## Long chats and context

Every question is answered with the full chat history, so context is kept. Two things keep that affordable:

- Old tool results are trimmed, and once a chat passes about 120k tokens the older part is summarized (`COMPACT_AFTER_TOKENS`). The working portfolio lives outside the transcript, so it is never summarized away.
- The 20k-token schema/domain prompt is cached.

A 1M-token context window is *not* needed for this: the state that matters (the TIN list, the target) is stored explicitly. If you still want it, `ANTHROPIC_BETAS` passes the beta header through; check the current docs for the flag and pricing (input beyond 200k tokens has historically been billed at a higher rate).

## Usage and spend per user

Every model call's token counts (input, output, cache write, cache read) are stored in `app.db` (`usage` table) against the signed-in user and chat, and priced with the rate card in `app/pricing.py` (Anthropic list prices; Foundry bills the same USD rates as CCUs). Users see:

- a line under each answer — `≈ 76,000 tokens · $0.04 · 3 model calls`;
- their spend this month and all time in the sidebar footer;
- a **Usage and spend** panel (click your name): this chat / today / this month / all time, token breakdown, by model, recent chats, and the rates used. Admin users (`--admin`) also get a per-user table.

Adjust pricing without code: `PRICE_MULTIPLIER=1.1` in `.env` for a Foundry US Data Zone deployment (or a negotiated discount below 1), and `data\pricing.json` to add or override a model/deployment name:

```json
{ "aco-opus": { "input": 4, "output": 20, "cache_write": 5, "cache_read": 0.2 } }
```

The figures are estimates from token counts; the Anthropic Console or Azure Cost Management is the invoice of record. Delete rows from the `usage` table to reset.

## Cost

The column list for the current file is about 15k tokens. It's prompt-cached, so repeat questions pay roughly 10% of that. A typical question uses 2–5 tool calls. Expect a few cents per question with Sonnet. Old tool results are trimmed from long chats to keep costs flat.

## Safety

- The warehouse is opened **read-only**. Only single `SELECT` statements are accepted, and DuckDB's file and network access is disabled and locked, so Claude's SQL can't read other files on the server.
- Queries are stopped after 30 seconds (`QUERY_TIMEOUT_SECONDS`).
- Data rows go to the Anthropic API only as query results, never as the whole file. Check that this fits your data-handling policy, since this dataset contains TIN/NPI identifiers but no member-level data.

## Deploying for a team

- **Docker:** `docker build -t aco-chat . && docker run -p 8000:8000 --env-file .env -v %cd%/data:/app/source:ro -v %cd%/state:/app/state aco-chat`
  - The image contains code and the small versioned files only (domain notes, column notes, dictionary, suggestions). **The CSV extracts are never copied into it**: mount the folder that holds them at `/app/source` (read-only is fine).
  - `/app/state` holds everything the app writes: `app.db` (users, chats, usage) and `warehouse.duckdb`, which is built from `/app/source` on first start and rebuilt when an extract is newer. Mount a persistent volume there.
  - Set `SECRET_KEY` in the environment, otherwise sessions are signed with a key that is lost when the container is replaced.
- **Azure:** the same image runs on Azure Container Apps or App Service for Containers. Store the Claude key and `SECRET_KEY` as secrets, mount persistent storage at `/app/state` and the extracts at `/app/source`, and set `COOKIE_SECURE=true` behind HTTPS. Set `TRUSTED_PROXY_HOPS=1` (the platform's ingress is one proxy; add one for each further layer such as Front Door or Application Gateway) so the login lockout counts each user's own address. Leave it at 0 when users connect to the app directly: the forwarded-address header is then ignored, because a client can forge it.
- **Single sign-on:** login is handled in `app/main.py` (`/api/login` + `current_user`). To use Microsoft Entra ID instead of local passwords, put the app behind App Service Authentication ("Easy Auth") and read the `X-MS-CLIENT-PRINCIPAL-NAME` header in `current_user`.

## Working on this project with Claude Code

Two ways, pick either:

- **Desktop app, local folder (no git needed):** open the Claude desktop app → *Code* → *Open folder* → choose `C:\Users\nisha\ACO-Lead-Document\aco-chat-app`. Claude Code then edits the files in place, can run `start.bat` / `pytest`, and the data files never leave your machine.
- **Web (claude.ai/code) or any machine via GitHub:** push the folder to a private GitHub repo and connect that repo in Claude Code. `.gitignore` keeps `.env`, `app.db`, `.secret_key`, the DuckDB warehouse and the large source CSVs (122 MB / 302 MB, over GitHub's 100 MB limit) out of git. Only the small `column_notes-*.csv`, the column dictionary and `pricing.json` in `data\` are committed, so after cloning on another machine copy the CSVs into `data\` and create `.env` from `.env.example`.

```
cd C:\Users\nisha\ACO-Lead-Document\aco-chat-app
git init -b main
git add .
git status            # confirm no .env / app.db / *_200plus.csv in the list
git commit -m "ACO Data Assistant"
gh repo create aco-chat-app --private --source . --push   # or create the repo on github.com and `git remote add origin … && git push -u origin main`
```

## Project layout

```
app/
  main.py      routes: login, chats, streaming /api/chat
  agent.py     system prompt, tool definitions, Claude tool loop
  data.py      CSV/Excel → DuckDB, column search, safe query runner
  store.py     SQLite users + conversations
  config.py    settings from .env
static/        chat UI (plain HTML/CSS/JS; marked, DOMPurify, Chart.js vendored — no CDN needed)
scripts/       manage_users.py, rebuild_data.py
data/          your files + context.md + suggestions.txt
```
