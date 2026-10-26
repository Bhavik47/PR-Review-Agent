# 🤖 Autonomous GitHub PR Reviewer & Sandbox Verification Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Kubernetes](https://img.shields.io/badge/Compute-Kubernetes_Jobs-326CE5.svg?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Sandbox-Docker-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An event-driven multi-agent backend that reviews GitHub Pull Requests. It combines static code analysis with **dynamic sandbox execution (Docker or Kubernetes Ephemeral Jobs)** to empirically prove edge-case bugs with real stack traces before posting review comments.

---

## 📌 What This Project Does

Standard AI review bots often hallucinate non-existent bugs. This system eliminates hallucinations using a dual-agent workflow:

- **Agent 1 (Static Analysis):** Inspects PR diffs for security risks, hardcoded secrets, and leftover debug statements.
- **Agent 2 (Sandbox Verification):** Writes targeted `pytest` edge-case tests and executes them inside an isolated sandbox. Bugs are only flagged if backed by a **reproducible stack trace**.
- **Dual Sandbox Compute Engine:**
  - **Docker Engine:** For fast, zero-setup local development.
  - **Kubernetes Ephemeral Jobs (`BatchV1Api`):** For secure cloud execution—eliminates the `/var/run/docker.sock` host-escape hazard, schedules jobs across a cluster, and enforces zero-trust NetworkPolicies.
- **Production Resilience:**
  - **Incremental Diffs:** Persists `last_completed_sha` in PostgreSQL to only review new changes across commits.
  - **Rapid-Push Cancellation:** Automatically cancels in-flight review jobs when a new commit is pushed to the same PR.
  - **AST-Validated Suggestions:** Validates code fixes via Python's AST parser before rendering GitHub ````suggestion`` blocks.

---

## 🏗️ High-Level Architecture

```text
               [GitHub Pull Request Webhook]
                             │
                             ▼
                     [FastAPI Gateway]
                 • Validates HMAC signature
                 • Deduplicates deliveries & cancels stale jobs
                             │
                             ▼
                     [Redis Queue (RQ)]
                             │
                             ▼
                        [RQ Worker]
                 • Computes incremental diff
                 • Dispatches parallel agent workflow
                             │
                             ▼
               [Parallel LangGraph Workflow]
        ┌────────────────────┴────────────────────┐
        ▼                                         ▼
[Agent 1: Static ReAct]                [Agent 2: Dynamic Sandbox]
• Secrets & hygiene checks             • Generates pytest edge cases
• ReAct context tools                  • Ephemeral Execution:
        │                                ├── Local Docker Container
        │                                └── Kubernetes Job Pod
        │                              • Captures real crash traces
        │                                         │
        └────────────────────┬────────────────────┘
                             ▼
                     [Aggregator Node]
             • Merges findings & validated AST fixes
                             │
                             ▼
                 [GitHub PR Review API]
             • Posts inline comments & bug proofs
```

---

## 🚀 How to Use the Project

### 1. Prerequisites
- Python 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- GitHub Personal Access Token (with `repo` permissions)
- [OpenRouter API Key](https://openrouter.ai/) (or OpenAI API Key)

### 2. Setup & Configuration
Clone the repository and copy the environment template:
```bash
git clone https://github.com/Bhavik47/PR-Review-Agent.git
cd PR-Review-Agent
cp .env.example .env
```

Configure credentials in `.env`:
```ini
DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5433/pr_agent
REDIS_URL=redis://localhost:6379/0

GITHUB_TOKEN=ghp_your_github_token_here
GITHUB_WEBHOOK_SECRET=your_secure_webhook_secret_here
GITHUB_BOT_USERNAME=pr-review-bot

OPENROUTER_API_KEY=sk-or-v1-your_openrouter_api_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini

# Compute Engine: "docker" (default) or "kubernetes"
SANDBOX_BACKEND=docker
```

### 3. Start Infrastructure & Build Sandbox Image
Start PostgreSQL and Redis:
```bash
docker-compose up -d redis db
```

Build the isolated test runner image:
```bash
docker build -f sandbox.Dockerfile -t pr-sandbox-runner:latest .
```

### 4. Install Dependencies & Run
Set up a Python virtual environment:
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

Launch the services in two separate terminals:

**Terminal 1 — API Gateway:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Background Worker:**
```bash
# Windows:
.\venv\Scripts\rq.exe worker pr_reviews --url redis://localhost:6379/0 --worker-class rq.SimpleWorker

# Linux/macOS:
rq worker pr_reviews --url redis://localhost:6379/0
```

---

## ☸️ Optional: Running with Kubernetes Compute

To execute untrusted test suites inside ephemeral Kubernetes Jobs instead of local Docker:

1. **Apply the Zero-Trust NetworkPolicy:**
   ```bash
   kubectl create namespace sandboxes
   kubectl apply -f k8s/networkpolicy-sandboxes.yaml
   ```

2. **Update `.env`:**
   ```ini
   SANDBOX_BACKEND=kubernetes
   K8S_SANDBOX_NAMESPACE=sandboxes
   K8S_IN_CLUSTER=false
   ```

3. Restart the background worker. The agent will now dynamically schedule single-use Kubernetes Jobs using the `BatchV1Api`, stream test execution logs, and automatically clean up pods.

---

## 🛡️ Security Highlights

- **Zero-Trust Compute Isolation:** Sandbox jobs run unprivileged (`runAsNonRoot: true`), drop all Linux capabilities (`CAP_DROP: ALL`), and have all network ingress/egress blocked via a Kubernetes `NetworkPolicy`.
- **Elimination of `docker.sock` Risks:** Prevents container-escape vulnerabilities by removing the need to mount host Docker sockets into worker containers.
- **Resource Limits & Deadlines:** Enforces strict cgroup CPU/memory caps and `activeDeadlineSeconds` timeouts to prevent runaway loops or fork bombs.

---

## 📜 License

Distributed under the [MIT License](LICENSE).
