# 🤖 Autonomous GitHub PR Reviewer & Sandbox Verification Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Sandbox-Docker-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Redis & RQ](https://img.shields.io/badge/Queue-Redis%20%2B%20RQ-DC382D.svg?logo=redis&logoColor=white)](https://python-rq.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An event-driven, multi-agent backend system that reviews GitHub Pull Requests, catches static security/hygiene flaws, and **empirically proves edge-case bugs inside an isolated Docker sandbox** before posting unified reviews with verified 1-click code suggestions.

---

## 🎯 Why This Project?

Standard LLM-based PR review bots suffer from three fatal flaws:
1. **High False-Positive Rates (Hallucinations):** They guess about edge-case bugs without executing the code, spamming developers with false warnings.
2. **Wasted Token Costs & Duplicate Comments:** On subsequent commits, naive bots re-review previously analyzed files, wasting tokens and reposting resolved feedback.
3. **Race Conditions on Rapid Pushes:** If a developer pushes Commit A and then Commit B five seconds later, stale jobs compete, creating ghost reviews and conflicting states.

### How This System Solves It:
- **Zero-Hallucination Sandbox Prover (Agent 2):** Generates targeted `pytest` tests and executes them inside an isolated, network-disabled Docker container (`--network none`, 512MB RAM, 20s timeout). Bugs are only flagged if backed by a **reproducible stack trace**.
- **Self-Correction Loop:** If the agent writes a test with a bad import or syntax error, it inspects `stderr`, self-corrects the test script, and retries (up to 2 attempts).
- **Fault-Tolerant Incremental Diffs:** Persists `last_completed_sha` in PostgreSQL. Subsequent pushes only evaluate newly introduced changes (`last_completed_sha...head_sha`).
- **Rapid-Push In-Flight Cancellation:** Instantly terminates running/queued Redis Queue (RQ) jobs for earlier commits when a newer commit arrives on the same PR.
- **AST-Validated 1-Click Code Suggestions:** Suggestions undergo Python AST parsing before rendering into GitHub's ```suggestion widget to guarantee that developers only get 1-click commit suggestions for syntactically valid code.

---

## 🏗️ System Architecture

```text
[GitHub Webhook Event (opened / synchronize)]
               │
               ▼
       [FastAPI Gateway]
       • HMAC SHA-256 Verification
       • Delivery UUID Deduplication (Redis SET NX)
       • Rapid-Push Cancellation of In-Flight Jobs
               │
               ▼
      [Redis Queue (RQ)]
               │
               ▼
          [RQ Worker]
       • Fetches last_completed_sha from PostgreSQL
       • Computes Incremental Diff (Compare API)
               │
               ▼
    [Parallel LangGraph Workflow]
    ┌─────────────────────────┴─────────────────────────┐
    ▼ (Track A)                                         ▼ (Track B)
[Agent 1: Static ReAct Reviewer]             [Agent 2: Dynamic Sandbox Prover]
• Leftover debug statements (print/log)       • Generates pytest edge-case tests
• Commented-out security guards               • Runs in Docker container (--network none)
• Hardcoded secrets & localhost URLs          • 2-retry autonomous self-correction loop
• Tool: get_file_content (GitHub API)         • Proves crashes with real tracebacks
    │                                                   │
    └─────────────────────────┬─────────────────────────┘
                              ▼
                      [Aggregator Node]
             • Merges static findings & bug proofs
             • AST validator checks code suggestions
                              │
                              ▼
                 [GitHub PR Review API]
             • Posts inline diff suggestions
             • Formats verified sandbox failure reports
                              │
                              ▼
             [PostgreSQL: Update last_completed_sha]
```

---

## 🧩 Tech Stack

| Component | Technology | Responsibility |
|---|---|---|
| **API Gateway** | **FastAPI**, Uvicorn | Ingests webhooks, validates HMAC signatures, manages job deduplication. |
| **Task Queue** | **Redis** + **RQ** | Asynchronous background execution, rapid-push cancellation, job registries. |
| **State Storage** | **PostgreSQL**, SQLAlchemy | Tracks `last_completed_sha`, PR review states, and run audits. |
| **Multi-Agent Engine** | **LangGraph**, LangChain | Parallel fan-out/fan-in DAG, ReAct context tools, structured Pydantic outputs. |
| **Sandbox Runtime** | **Docker SDK for Python** | Ephemeral `python:3.11-slim` containers (`--network none`, resource limits). |
| **Testing Engine** | **Pytest** | Dynamic edge-case execution inside the container. |
| **LLM Provider** | **OpenRouter** (GPT-4o, Claude, etc.) | High-reasoning structured analysis and test generation. |

---

## 📁 Repository Structure

```text
PR-Review-Agent/
├── app/
│   ├── main.py                 # FastAPI webhook receiver & job dispatcher
│   ├── config.py               # Pydantic Settings configuration loader
│   ├── db/
│   │   ├── session.py          # SQLAlchemy engine & session factory
│   │   └── models.py           # PRReview persistence model
│   ├── queue/
│   │   ├── redis_conn.py       # Redis client, delivery deduplication & cancellation
│   │   └── worker.py           # RQ worker entrypoint & incremental diff orchestrator
│   ├── github/
│   │   └── client.py           # GitHub REST API client (Diffs, Compare, Reviews)
│   └── agents/
│       ├── state.py            # LangGraph TypedDict state & Pydantic output schemas
│       ├── graph.py            # Parallel LangGraph DAG (Agent 1 + Agent 2 -> Aggregator)
│       ├── agent1_static.py    # Static hygiene & security reviewer (ReAct agent)
│       ├── agent2_sandbox.py   # Dynamic edge-case test generator & self-correction loop
│       └── sandbox_runner.py   # Isolated Docker execution utility
├── docker-compose.yml          # Container configuration for Redis, Postgres, API & Worker
├── sandbox.Dockerfile          # Ephemeral Docker image definition for isolated tests
├── requirements.txt            # Python dependencies
└── .env.example                # Safe environment variable template
```

---

## 🚀 Getting Started

### 1. Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- Python 3.11+.
- A [GitHub Personal Access Token](https://github.com/settings/tokens) with `repo` (or Fine-grained token with `Pull requests: Read & write` and `Contents: Read & write`).
- An [OpenRouter API Key](https://openrouter.ai/).

### 2. Clone the Repository
```bash
git clone https://github.com/Bhavik47/PR-Review-Agent.git
cd PR-Review-Agent
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your credentials in `.env`:
```ini
DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5433/pr_agent
REDIS_URL=redis://localhost:6379/0

# GitHub Settings
GITHUB_TOKEN=ghp_your_github_token_here
GITHUB_WEBHOOK_SECRET=your_secure_webhook_secret_here
GITHUB_BOT_USERNAME=pr-review-bot

# OpenRouter Settings
OPENROUTER_API_KEY=sk-or-v1-your_openrouter_api_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

### 4. Start Infrastructure (PostgreSQL & Redis)
```bash
docker-compose up -d redis db
```

### 5. Build the Sandbox Docker Image
Build the local sandbox container used by Agent 2:
```bash
docker build -f sandbox.Dockerfile -t pr-sandbox-runner:latest .
```

### 6. Install Python Dependencies
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 7. Run the Application
Open two terminal windows:

**Terminal 1 (FastAPI Webhook Gateway):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 (RQ Background Worker):**
```bash
# On Windows:
.\venv\Scripts\rq.exe worker pr_reviews --url redis://localhost:6379/0 --worker-class rq.SimpleWorker

# On Linux/macOS:
rq worker pr_reviews --url redis://localhost:6379/0
```

---

## 🔗 Connecting to GitHub Webhooks

1. Expose your local port `8000` via a tunnel like [smee.io](https://smee.io/) or [ngrok](https://ngrok.com/):
   ```bash
   ngrok http 8000
   ```
2. In your GitHub repository:
   - Navigate to **Settings → Webhooks → Add webhook**.
   - **Payload URL:** `https://<your-tunnel-url>/webhooks/github`
   - **Content type:** `application/json`
   - **Secret:** The same string as `GITHUB_WEBHOOK_SECRET` in your `.env`.
   - **Events:** Select **Let me select individual events** → Check **Pull requests**.
   - Save the webhook.

---

## 🧪 What a Review Looks Like on GitHub

When a PR is opened or updated, the bot publishes:

### 1. Inline Diff Suggestions (Agent 1)
- Validated via Python AST before posting.
- Shows GitHub's native ```suggestion widget for 1-click merging.

### 2. Empirical Sandbox Bug Proofs (Agent 2)
```markdown
### 🤖 Autonomous PR Review & Sandbox Verification

**Static Review Summary:**
Found 1 leftover debug print and 1 unhandled division-by-zero vulnerability.

### 🧪 ⚠️ Verified Runtime Bugs (Sandbox Proved)
> **The following issues are NOT hallucinations.** They were proven by executing real `pytest` tests inside an isolated Docker sandbox container.

#### Bug #1: `calculate_average_discount` crashed in `pricing.py`
- **Error Type:** `ZeroDivisionError`
- **Failing Input:** `discounts = []`

**Reproducing Test:**
```python
def test_calculate_average_discount_empty():
    assert calculate_average_discount([]) == 0.0
```

**Stack Trace:**
```text
pricing.py:8: in calculate_average_discount
    return total / len(discounts)
E   ZeroDivisionError: division by zero
```

**Suggested Fix:**
```python
def calculate_average_discount(discounts: list) -> float:
    return sum(discounts) / len(discounts) if discounts else 0.0
```
```

---

## 🛡️ Security Features

- **Network-Isolated Execution:** Ephemeral containers run with `--network none`, guaranteeing sandbox code cannot make outbound network requests or access host internal networks.
- **Resource Constraints:** Containers are strictly capped at 512MB RAM and 1 CPU core to prevent fork bombs or memory exhaustion.
- **Hard Execution Timeout:** Kills any container exceeding 20 seconds, defending against infinite loops and ReDoS attacks.
- **HMAC Signature Verification:** Verifies the cryptographic `X-Hub-Signature-256` header to ensure only authentic GitHub events are ingested.
- **AST Code Guardrails:** Prevents corrupted markdown or arbitrary prose from breaking GitHub suggestion widgets.

---

## 📜 License

Distributed under the [MIT License](LICENSE).
