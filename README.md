# 🤖 Autonomous GitHub PR Reviewer & Sandbox Verification Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Kubernetes](https://img.shields.io/badge/Compute-Kubernetes_Jobs-326CE5.svg?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Sandbox-Docker-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Redis & RQ](https://img.shields.io/badge/Queue-Redis%20%2B%20RQ-DC382D.svg?logo=redis&logoColor=white)](https://python-rq.org/)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An event-driven, multi-agent backend system that reviews GitHub Pull Requests, catches static security/hygiene flaws, and **empirically proves edge-case bugs inside an isolated sandbox (Local Docker or Kubernetes Ephemeral Jobs)** before posting unified reviews with verified 1-click code suggestions.

---

## 🎯 Why This Project?

Standard LLM-based PR review bots suffer from three fatal flaws:
1. **High False-Positive Rates (Hallucinations):** They guess about edge-case bugs without executing the code, spamming developers with false warnings.
2. **Wasted Token Costs & Duplicate Comments:** On subsequent commits, naive bots re-review previously analyzed files, wasting tokens and reposting resolved feedback.
3. **Race Conditions on Rapid Pushes:** If a developer pushes Commit A and then Commit B five seconds later, stale jobs compete, creating ghost reviews and conflicting states.

### How This System Solves It:
- **Zero-Hallucination Sandbox Prover (Agent 2):** Generates targeted `pytest` tests and executes them inside an isolated sandbox container. Bugs are only flagged if backed by a **reproducible stack trace**.
- **Dual Sandbox Compute Engine (Docker or Kubernetes):** 
  - **Docker Engine:** For fast, zero-setup local development.
  - **Kubernetes Ephemeral Jobs (`BatchV1Api`):** For hardened, multi-tenant cloud platforms. Eliminates the dangerous `/var/run/docker.sock` host-escape risk, schedules jobs across a cluster, and enforces zero-trust NetworkPolicies.
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
• Leftover debug prints & logs                • Generates pytest edge-case tests
• Hardcoded secrets & URLs                    • 2-retry autonomous self-correction
• ReAct tool: get_file_content                • Dispatches to configured Compute Engine:
    │                                            ├── Option 1: Local Docker Container
    │                                            └── Option 2: Ephemeral K8s Job Pod
    │                                         • Proves crashes with real tracebacks
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
| **Compute Sandbox** | **Kubernetes Jobs** / **Docker** | Ephemeral, network-isolated containers/pods running generated `pytest` suites. |
| **Testing Engine** | **Pytest** | Dynamic edge-case execution inside the sandboxed environment. |
| **LLM Provider** | **OpenRouter** (GPT-4o, Claude, etc.) | High-reasoning structured analysis and test generation. |

---

## 📁 Repository Structure

```text
PR-Review-Agent/
├── app/
│   ├── main.py                     # FastAPI webhook receiver & job dispatcher
│   ├── config.py                   # Pydantic Settings configuration loader
│   ├── db/
│   │   ├── session.py              # SQLAlchemy engine & session factory
│   │   └── models.py               # PRReview persistence model
│   ├── queue/
│   │   ├── redis_conn.py           # Redis client, delivery deduplication & cancellation
│   │   └── worker.py               # RQ worker entrypoint & incremental diff orchestrator
│   ├── github/
│   │   └── client.py               # GitHub REST API client (Diffs, Compare, Reviews)
│   └── agents/
│       ├── state.py                # LangGraph TypedDict state & Pydantic output schemas
│       ├── graph.py                # Parallel LangGraph DAG (Agent 1 + Agent 2 -> Aggregator)
│       ├── agent1_static.py        # Static hygiene & security reviewer (ReAct agent)
│       ├── agent2_sandbox.py       # Dynamic edge-case test generator & self-correction loop
│       ├── sandbox_runner.py       # Unified sandbox dispatcher (Docker vs Kubernetes)
│       └── k8s_sandbox_runner.py   # Kubernetes-native ephemeral Job compute engine
├── k8s/
│   └── networkpolicy-sandboxes.yaml# Zero-trust network isolation for sandbox pods
├── docker-compose.yml              # Container configuration for Redis, Postgres, API & Worker
├── sandbox.Dockerfile              # Ephemeral sandbox runner container definition
├── requirements.txt                # Python dependencies
└── .env.example                    # Safe environment variable template
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- A [GitHub Personal Access Token](https://github.com/settings/tokens) with `repo` permissions.
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

# Compute Sandbox Engine: "docker" or "kubernetes"
SANDBOX_BACKEND=docker
K8S_SANDBOX_NAMESPACE=sandboxes
K8S_SANDBOX_IMAGE=pr-sandbox-runner:latest
```

### 4. Start Infrastructure (PostgreSQL & Redis)
```bash
docker-compose up -d redis db
```

### 5. Build the Sandbox Image
Build the isolated runner image used for testing:
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

## ☸️ Running with Kubernetes Ephemeral Compute

To execute tests on Kubernetes instead of local Docker:

1. **Apply the Zero-Trust NetworkPolicy:**
   ```bash
   kubectl create namespace sandboxes
   kubectl apply -f k8s/networkpolicy-sandboxes.yaml
   ```

2. **Switch Backend in `.env`:**
   ```ini
   SANDBOX_BACKEND=kubernetes
   K8S_SANDBOX_NAMESPACE=sandboxes
   K8S_IN_CLUSTER=false
   ```

3. Restart your RQ worker. When Agent 2 proves bugs, it will automatically schedule ephemeral, single-use Kubernetes Jobs using `BatchV1Api`, stream test logs, and clean up the pods upon completion.

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
> **The following issues are NOT hallucinations.** They were proven by executing real `pytest` tests inside an isolated sandbox container.

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

## 🛡️ Enterprise Security & Hardening

- **Elimination of `docker.sock` in Production:** In multi-tenant environments, running Docker-in-Docker requires mounting `/var/run/docker.sock`, which gives the container root-equivalent host access. In Kubernetes mode, tests run as ephemeral unprivileged `Job` pods with zero host-level access.
- **Kernel-Level Hardening:** Sandbox pods run with `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, and `capabilities: { drop: ["ALL"] }`.
- **Zero-Trust Network Isolation:** Sandbox pods are bounded by a `NetworkPolicy` with both `ingress: []` and `egress: []` denied, ensuring untrusted PR code cannot reach the internet or internal cloud metadata (`169.254.169.254`).
- **Resource Constraints & Deadlines:** Bounded by strict CPU (`1000m`) and memory (`512Mi`) cgroup limits with an `activeDeadlineSeconds` control-plane timeout to guard against infinite loops or fork bombs.
- **HMAC Signature Verification:** Verifies the cryptographic `X-Hub-Signature-256` header on incoming webhooks.
- **AST Guardrails:** Code suggestions are syntax-checked with Python's `ast` parser prior to submission.

---

## 📜 License

Distributed under the [MIT License](LICENSE).
