# KodGard AI

**English** | [Türkçe](README.tr.md)

Commit-based security and code quality analysis system that combines static scanners (Semgrep, Gitleaks), Claude structured review, and a pgvector-backed RAG assistant.

![Commit list view](docs/screenshots/01-commits.png)

## What it does

- **Automated Commit Documentation (`summary` & `detail`)**: Generates a 5–10 line Markdown summary and a file-by-file detailed Markdown report explaining changed functions/classes, side effects, and static analysis findings for each tracked commit.
- **Multi-Source Security & Quality Findings (Semgrep + Gitleaks + Claude)**:
  - **Semgrep**: Runs local Python and JavaScript rules (`rules/python-js.yml`) against changed files extracted from the commit tree.
  - **Gitleaks**: Scans the commit range (`<sha>^..<sha>`, or `<sha>` for root commits) for secrets and records the file, line, and rule ID (`severity: high`, `CWE-798`) without storing the secret value.
  - **Claude Review**: Analyzes the unified diff alongside pre-findings via structured Pydantic output, producing documentation and additional code/security findings with mandatory file and positive line references.
- **Finding Lifecycle (`open` / `ignored` / `fixed`)**:
  - Each finding has a deterministic SHA-256 fingerprint (`source | rule_id | file | line | summary`).
  - Users can mark a finding as `ignored` with a mandatory `ignore_reason` (`PATCH /findings/{id}`); if the same fingerprint recurs in later commits of the same repository, its `ignored` status and reason are preserved.
  - When a subsequent commit in the same repository modifies a file and an earlier `open` finding on that file does not recur, the earlier finding automatically transitions to `fixed`.
- **Markdown Export**: Summary and detailed reports can be downloaded directly as `<sha8>-summary.md` and `<sha8>-detail.md` (`GET /commits/{sha}/export?doc=summary|detail`).
- **RAG Assistant**: Indexes commit summaries, detailed docs, findings, diffs, and source files (`<= 200 KB`) into PostgreSQL `pgvector` (`vector(384)`, HNSW cosine index) using `sentence-transformers/all-MiniLM-L6-v2` and answers questions over Server-Sent Events (`POST /assistant/chat`) with numbered source citations (`[1]`, `[2]`, ...).

### Commit Summary (`02-commit-summary.png`)
![Commit summary view](docs/screenshots/02-commit-summary.png)

### File-by-File Detailed Documentation (`03-commit-detail-doc.png`)
![Commit detailed documentation view](docs/screenshots/03-commit-detail-doc.png)

### Findings & Lifecycle (`fixed` / `ignored`) (`04-findings.png`)
![Findings list and lifecycle statuses](docs/screenshots/04-findings.png)

### Credential / Secret Detection Findings (`05-secret-finding.png`)
![Hardcoded credential findings view](docs/screenshots/05-secret-finding.png)

### RAG Assistant with Citations (`06-assistant.png`)
![RAG assistant view](docs/screenshots/06-assistant.png)

## Architecture

```mermaid
flowchart LR
    A["git commit"] --> B["post-commit hook"]
    B --> C["POST /enqueue"]
    C --> D["API"]
    D --> E["PostgreSQL scans"]
    E --> F["worker"]
    F --> G["Semgrep Gitleaks Claude"]
    G --> H["docs findings"]
    H --> I["chunks pgvector"]
    H --> J["API"]
    I --> J
    J --> K["React UI"]
```

## Quick start (Docker)

1. Clone the repository and enter the directory:
   ```bash
   git clone <repo-url> KodGard-AI
   cd KodGard-AI
   ```
2. Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` and `REPOS_HOST_DIR` (the parent directory on the host containing the Git repositories you want to analyze):
   ```bash
   cp .env.example .env
   ```
3. Build and start the stack:
   ```bash
   docker compose up -d --build
   ```
4. Open the web UI at `http://localhost:5173` (API health check: `http://127.0.0.1:8000/health` or `http://localhost:5173/api/health`).

**Image sizes and first-run model download:**
- Measured Docker image sizes:
  - `kodgard-backend:latest`: `4.03GB` (includes Python 3.12, CPU-only PyTorch, `sentence-transformers`, Semgrep `1.182.1`, and Gitleaks `8.30.1`)
  - `kodgard-frontend:latest`: `94.7MB` (multi-stage Node 22 build served by `nginx:alpine`)
  - `pgvector/pgvector:pg16`: `631MB`
- On first startup, the one-shot `model-init` service runs `python -m app.cli download-model` to download and verify the local embedding model (`sentence-transformers/all-MiniLM-L6-v2`) into the persistent `hf_cache` Docker volume before `api` and `worker` start.

## Connect your own repo

1. **Mount via `REPOS_HOST_DIR`**:
   In Docker mode, `REPOS_HOST_DIR` is mounted read-only into the `api` and `worker` containers at `/repos` (`${REPOS_HOST_DIR}:/repos:ro`). Any Git repository you want to scan must reside inside `REPOS_HOST_DIR`.
2. **Install the `post-commit` hook**:
   Run `scripts/install-hook.sh` on the host pointing to your target Git repository:
   ```bash
   ./scripts/install-hook.sh /path/to/repos/my-project
   ```
   - Resolves the hooks directory via `git -C <repo> rev-parse --git-path hooks` and **never modifies `core.hooksPath`**.
   - Adds a marked block (`# >>> kodgard >>>` ... `# <<< kodgard <<<`) to `.git/hooks/post-commit`. If a `post-commit` hook already exists, it backs it up to `post-commit.kodgard.bak` and appends the block without overwriting existing hook logic.
   - To remove only the KodGard block (or remove the standalone wrapper if created by KodGard):
     ```bash
     ./scripts/install-hook.sh --uninstall /path/to/repos/my-project
     ```
3. **Backfill existing commits**:
   To enqueue historical non-merge commits from a repository mounted under `/repos`:
   ```bash
   docker compose exec worker python -m app.cli backfill --repo /repos/my-project --limit 20
   ```
   `--limit` accepts `1..200` (default `20`). When `--limit` is greater than `20`, passing `--yes` is required because each commit triggers a Claude API call.
4. **Hook error log (`hook.log`)**:
   The `post-commit` hook runs asynchronously in the background and always exits `0` so it never blocks `git commit`. When `KODGARD_API_URL` is used and `POST /enqueue` returns a non-`2xx` HTTP status (or `000` on connection failure), the timestamp and HTTP code are appended to:
   ```text
   ${XDG_STATE_HOME:-$HOME/.local/state}/kodgard/hook.log
   ```

## Host mode (uv + npm)

You can run the backend, worker, CLI, and Vite dev server directly on the host while running PostgreSQL (`pgvector`) in Docker:

1. **Install dependencies**:
   ```bash
   uv sync
   npm --prefix frontend install
   ```
2. **Start PostgreSQL and run migrations**:
   ```bash
   docker compose up -d db
   uv run python -m app.db migrate
   ```
3. **Run the API server**:
   ```bash
   uv run uvicorn app.main:app --port 8000
   ```
4. **Run the worker**:
   ```bash
   # Process current pending queue once and exit:
   uv run python -m app.cli worker

   # Or poll continuously every 5 seconds:
   uv run python -m app.cli worker --loop --interval 5
   ```
5. **Run the frontend (Vite)**:
   ```bash
   npm run --prefix frontend dev
   ```
   (Other `frontend/package.json` scripts: `npm run --prefix frontend build`, `npm run --prefix frontend preview`.)
6. **CLI commands (`app/cli.py`)**:
   - `uv run python -m app.cli enqueue --repo <path> --sha <sha>`
   - `uv run python -m app.cli list [--repo <path>] [--limit 20]`
   - `uv run python -m app.cli worker [--loop] [--interval 5.0]`
   - `uv run python -m app.cli reindex (--sha <sha> | --all)`
   - `uv run python -m app.cli backfill --repo <path> [--limit 20] [--yes]`
   - `uv run python -m app.cli download-model`

**Difference between `KODGARD_HOME` and `KODGARD_API_URL`:**
- `KODGARD_HOME` points to the KodGard AI project root on disk (used to locate `migrations/`, `rules/python-js.yml`, and `.kodgardignore`, and used by the hook in CLI mode).
- `KODGARD_API_URL` points to the HTTP API base URL (e.g., `http://127.0.0.1:8000`). In `hooks/post-commit`, if `KODGARD_API_URL` is set (which `scripts/install-hook.sh` exports by default), the hook enqueues commits via `curl -X POST .../enqueue` without invoking `uv` on every commit. If `KODGARD_API_URL` is unset/empty, the hook falls back to `cd "$KODGARD_HOME" && uv run python -m app.cli enqueue`.

## Configuration

Every key in `.env.example`:

| Variable | Default in `.env.example` | Description |
| :--- | :--- | :--- |
| `KODGARD_BIND` | `127.0.0.1` | Host interface address to which Docker ports (`db`, `api`, `frontend`) bind. |
| `FRONTEND_PORT` | `5173` | Host port mapped to container port `8080` for the frontend UI. |
| `API_PORT` | `8000` | Host port mapped to container port `8000` for the FastAPI backend. |
| `DB_PORT` | `5432` | Host port mapped to container port `5432` for PostgreSQL (used in host mode). |
| `POSTGRES_USER` | `kodgard` | PostgreSQL username. |
| `POSTGRES_PASSWORD` | `kodgard` | PostgreSQL password (default is for local `127.0.0.1` use only). |
| `POSTGRES_DB` | `kodgard` | PostgreSQL database name. |
| `DATABASE_URL` | `postgresql://kodgard:kodgard@localhost:5432/kodgard` | PostgreSQL connection string for host mode (`docker-compose.yml` overrides host with `@db:5432` inside containers). |
| `KODGARD_HOME` | `/path/to/KodGard-AI` | Path to the KodGard AI repository root (host mode only; set to `/app` in Docker). |
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key required by `worker` (commit review) and `api` (RAG assistant). |
| `REPOS_HOST_DIR` | *(empty, required in Compose)* | Host parent directory containing Git repositories to mount read-only at `/repos`. |
| `REVIEW_MODEL` | `claude-sonnet-5-5` | Anthropic model used by `app/reviewer.py` for commit documentation and review. |
| `ASSISTANT_MODEL` | `claude-haiku-5-5` | Anthropic model used by `app/assistant.py` for RAG assistant responses. |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | Local HuggingFace / `sentence-transformers` model producing 384-dim embeddings. |
| `TOP_K_CHUNKS` | `8` | Maximum number of context chunks retrieved per RAG assistant query. |
| `HF_TOKEN` | *(empty)* | Optional HuggingFace token (not required for public default model). |

## Privacy and cost

- **Diffs sent to Anthropic API (`60,000` character cap)**: When a commit is scanned, `app/scanner.py` (`prepare_diff`) builds the unified diff for changed `.py` and `.js` files (excluding `.gitignore` and `.kodgardignore` matches) and caps the total diff payload at `MAX_DIFF_CHARS = 60000` characters. This diff and sanitized pre-finding metadata are sent to the Anthropic API (`REVIEW_MODEL`). If you use this tool on proprietary or regulated codebases, review your organization's policy and Anthropic's data retention/usage terms for your API tier.
- **API calls per operation**:
  - **Each scanned commit** makes **1** `REVIEW_MODEL` call (`max_tokens=4096`, `temperature=0`, up to 2 retries on failure).
  - **Each assistant question** (when indexed chunks exist) makes **1** `ASSISTANT_MODEL` streaming call (`max_tokens=1024`) with the retrieved chunks (`<= 8` chunks, each truncated to `1,500` chars) and up to the last `6` chat history messages.
  - **Embeddings** run locally on CPU via `sentence-transformers` (no external embedding API calls).
- **Secret handling & limitation**:
  - `parse_gitleaks_output` never stores or repeats the raw secret in the database (`findings` table) or in `pre_findings` metadata.
  - `filter_secret_safe_files` (`app/indexer.py`) excludes any file that has ever had a `source='gitleaks'` finding in that repository from `diff` and `file` RAG chunks so raw file/diff contents of secret-tainted files are not indexed into `chunks`.
  - **However**, if a secret is added inside a `.py` or `.js` diff, that unified diff is still sent to `REVIEW_MODEL` during the commit review step (even though the system prompt instructs the model never to repeat secret values in its output).
- **Container environment visibility**: While `api` and `worker` containers are running, `ANTHROPIC_API_KEY` is passed as a container environment variable; any local user in the `docker` group on the host can view container environment variables via `docker inspect`. (Subprocesses spawned for `git`, `semgrep`, and `gitleaks` strip `ANTHROPIC_API_KEY` via `_clean_subprocess_env` / `_clean_git_env`.)

## Security notes

- **No authentication**: Neither the web UI nor the FastAPI endpoints implement user authentication or authorization.
- **Unauthenticated `/enqueue`**: `POST /enqueue` has no authentication token so local Git hooks can call it with minimal overhead.
- **Localhost binding (`KODGARD_BIND`)**: All published Docker ports (`db`, `api`, `frontend`) bind to `127.0.0.1` by default (`${KODGARD_BIND:-127.0.0.1}`). Do not set `KODGARD_BIND=0.0.0.0` on untrusted networks.
- **Default database password**: The default `POSTGRES_PASSWORD=kodgard` is intended strictly for local loopback (`127.0.0.1`) usage.
- **Remote access via SSH tunnel**: To access the UI/API from another machine, keep `KODGARD_BIND=127.0.0.1` and use SSH local port forwarding:
  ```bash
  ssh -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 <user>@<host>
  ```
- **Path containment on `/enqueue`**: `resolve_and_validate_repo` (`app/enqueue.py`) rejects `..` segments, resolves `realpath` to prevent symlink escapes, requires the target repository (and its `.git` entry) to reside inside `REPOS_HOST_DIR` / `/repos`, and verifies that `.git` exists before running any `git` command.

## Known limitations

- **Only `.py` and `.js` files for diff/Semgrep/file-chunking**: `app/ignore.py` (`ALLOWED_EXTENSIONS = {".py", ".js"}`) filters changed files to `.py` and `.js` (and excludes `.gitignore` and `.kodgardignore` patterns: `*.lock`, `dist/`, `build/`, `*.min.js`). `rules/python-js.yml` contains **8** local Semgrep rules (`kodgard-eval-usage-python`, `kodgard-eval-usage-js`, `kodgard-subprocess-shell-true`, `kodgard-hardcoded-password-python`, `kodgard-hardcoded-password-js`, `kodgard-sql-string-concat-python`, `kodgard-sql-string-concat-js`, `kodgard-innerhtml-assignment`). (Gitleaks scans the commit git log across all files in the commit.)
- **Top-4 finding limit in hybrid retrieval**: When a question matches security intent keywords, `app/assistant.py` retrieves at most `FINDING_HYBRID_LIMIT = 4` nearest `kind='finding'` chunks (merged with general chunks up to `TOP_K_CHUNKS = 8`). Repositories with many findings may have relevant findings outside the top 4 vector matches.
- **LLM output can be inaccurate**: Claude review summaries, detailed explanations, additional `source='llm'` findings, and RAG assistant answers may contain false positives, omissions, or hallucinations.
- **General-purpose embedding model**: `sentence-transformers/all-MiniLM-L6-v2` is a lightweight general-purpose 384-dimensional model, not a specialized code/security retrieval model.
- **Single-user and single-worker design**: Designed for a single local developer workflow with one sequential polling worker (`SELECT ... FOR UPDATE SKIP LOCKED`).
- **Turkish UI and generated documentation**: The React interface and the system prompt for generated commit documentation (`summary_md`, `detail_md`, and scanner finding messages) are in Turkish (the RAG assistant replies in the language of the user's question).

## Troubleshooting

- **`hook.log` shows `http_code=400` (or `000`)**:
  Check `${XDG_STATE_HOME:-$HOME/.local/state}/kodgard/hook.log`.
  - `http_code=400` typically means `repo_not_allowed`: the repository path passed by the hook is outside the configured `REPOS_HOST_DIR` (or is a symlink pointing outside `REPOS_HOST_DIR`). Ensure the repository is inside `REPOS_HOST_DIR`.
  - `http_code=000` means the API was unreachable at `KODGARD_API_URL` when the commit occurred; check `docker compose ps` or run `backfill` once the stack is up.
- **Inspecting worker logs**:
  If a scan remains `pending` or transitions to `failed`, inspect the worker output:
  ```bash
  docker compose logs -f worker
  ```
- **`MissingAPIKeyError`**:
  The scan status shows `failed` with error `RuntimeError` (or assistant chat returns `{"class": "RuntimeError"}`) when `ANTHROPIC_API_KEY` is empty or not set in `.env` / the environment. Set `ANTHROPIC_API_KEY`, restart `api` and `worker` (`docker compose up -d api worker`), and re-enqueue or backfill.
- **`REPOS_HOST_DIR tanimlanmali` error from Docker Compose**:
  `docker-compose.yml` enforces `${REPOS_HOST_DIR:?REPOS_HOST_DIR tanimlanmali}`. Set `REPOS_HOST_DIR` in `.env` to a valid directory on the host before running `docker compose`.
- **`commit_not_found`**:
  If the worker fails a scan with `error = commit_not_found`, the worker container could not find the commit SHA in the mounted repository (for example, if a commit was amended/rebased and garbage-collected or the wrong directory was mounted).

## Development

**Running tests:**
```bash
uv run pytest -q
```

**Project tree:**
```text
.
├── app/
│   ├── assistant.py     # RAG retrieval, prompt construction, SSE streaming
│   ├── cli.py           # CLI entrypoints (enqueue, list, worker, reindex, backfill, download-model)
│   ├── config.py        # Pydantic Settings and chunking/embedding constants
│   ├── db.py            # PostgreSQL connection pool, queries, and migration runner
│   ├── enqueue.py       # Repo path containment validation and commit enqueueing
│   ├── findings.py      # SHA-256 fingerprinting, ignored preservation, fixed transitions
│   ├── git_reader.py    # Git log/show reader and stable patch-id calculation
│   ├── ignore.py        # .py/.js filtering, .gitignore and .kodgardignore matching
│   ├── indexer.py       # Markdown/diff/code chunking, secret-safe filtering, pgvector indexing
│   ├── main.py          # FastAPI routes (/health, /commits, /findings, /assistant, /enqueue)
│   ├── reviewer.py      # Anthropic structured output commit review
│   ├── scanner.py       # Diff preparation (60k cap), Semgrep runner, Gitleaks runner
│   └── worker.py        # Sequential scan worker with SKIP LOCKED and graceful shutdown
├── frontend/            # React 18 + TypeScript + Vite UI (Nginx config for Docker)
├── hooks/
│   └── post-commit      # Non-blocking background post-commit hook
├── migrations/          # SQL migrations (001_init.sql, 002_scans_docs_findings.sql, 003_chunks.sql)
├── rules/
│   └── python-js.yml    # 8 local Semgrep rules for Python and JavaScript
├── scripts/
│   └── install-hook.sh  # Idempotent post-commit hook installer / uninstaller
├── tests/               # Pytest suite
├── Dockerfile           # Backend & worker image definition
└── docker-compose.yml   # Full stack orchestration (db, model-init, api, worker, frontend)
```

**Migration logic (`app/db.py`):**
Running `python -m app.db migrate` creates the `schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ)` table if it does not exist, iterates over `migrations/*.sql` in sorted filename order (`001_init.sql`, `002_scans_docs_findings.sql`, `003_chunks.sql`), executes any SQL file not yet recorded in `schema_migrations`, and records its filename in the same transaction. In Docker, the `api` container runs `python -m app.db migrate` automatically before starting Uvicorn.

## Third-party

Licenses below are listed specifically for packages whose license metadata was verified directly from installed package metadata (`importlib.metadata` / `package.json`); all other external tools, base images, and transitive dependencies are subject to their own respective licenses.

**Verified from package metadata:**
- **Backend Python packages**:
  - `fastapi`: MIT
  - `uvicorn`: BSD-3-Clause
  - `psycopg` / `psycopg-pool`: LGPL-3.0-only
  - `pydantic` / `pydantic-settings`: MIT
  - `python-dotenv`: BSD-3-Clause
  - `anthropic`: Apache-2.0
  - `sentence-transformers`: Apache-2.0
  - `langchain-text-splitters` / `langchain-huggingface`: MIT
  - `torch`: Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib
  - `pytest`: MIT
  - `httpx`: BSD-3-Clause
- **Frontend packages**:
  - `react` / `react-dom`: MIT
  - `@tanstack/react-query`: MIT
  - `react-markdown` / `remark-gfm`: MIT
  - `vite` / `@vitejs/plugin-react`: MIT
  - `typescript`: Apache-2.0
- **External binaries, models, and container images** (Semgrep, Gitleaks, PostgreSQL / `pgvector`, `sentence-transformers/all-MiniLM-L6-v2`, Nginx, Python, Node.js): each is subject to its own respective license.

> **UI Design Note:** The interface styling is inspired by a Linear-extracted `DESIGN.md` from the `awesome-design-md` collection and has no affiliation with Linear.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
