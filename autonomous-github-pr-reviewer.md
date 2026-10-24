# Autonomous GitHub PR Reviewer & Sandbox Verification Agent

An event-driven, multi-agent backend system that automatically reviews GitHub Pull Requests, catches static security/hygiene flaws, and verifies edge-case bugs inside an isolated Docker sandbox before posting a unified review.

---

## 1. Problem Statement & Engineering Goals

Standard LLM-based PR review bots suffer from three major flaws:
1. **High False-Positive Rates:** They guess about potential bugs without running the code, spamming developers with hallucinated warnings.
2. **Missing Context:** They only read the raw `git diff`, lacking visibility into surrounding functions or imported files.
3. **Poor Concurrency Handling:** When a developer pushes multiple commits rapidly, naive bots either time out the GitHub webhook, re-review already analyzed files, or miss intermediate commits when tasks are cancelled.

### How This System Solves It:
* **Asynchronous Event-Driven Pipeline:** Decouples fast HTTP webhook ingestion (`<100ms` response) from slow agent execution using **FastAPI** and **Redis Queue (`RQ`)**.
* **Fault-Tolerant Incremental Diffs:** Tracks `last_completed_sha` in **PostgreSQL** so cancelled runs never cause skipped commits, and subsequent pushes only analyze newly introduced changes.
* **Parallel Dual-Agent Architecture (LangGraph):**
  * **Agent 1 (Static Hygiene & Security):** Uses tool-calling to fetch surrounding file context and flag leftover debug statements, commented-out production guards, and hardcoded secrets.
  * **Agent 2 (Sandbox Edge-Case Prover):** Eliminates hallucinations by writing targeted `pytest` edge-case tests and executing them inside a network-disabled **Docker container** to prove bugs with real stack traces before commenting.

---

## 2. High-Level System Architecture

```text
[GitHub PR Webhook (opened / synchronize)]
     │
     ▼
[FastAPI Gateway] ──(1. Verify HMAC, Deduplicate & Cancel Old Job)──> [Redis (RQ)]
                                                                         │
                                                                         ▼
[PostgreSQL] <──────(2. Fetch last_completed_sha)────────────────── [RQ Worker]
    │                                                                     │
    │                                               ┌─────────────────────┴─────────────────────┐
    │                                               ▼ (Track A)                                 ▼ (Track B)
    │                                    [Agent 1: Static Hygiene]                   [Agent 2: Sandbox Tester]
    │                                    • Checks debug logs, secrets,               • Writes edge-case tests
    │                                      commented-out guards, logic               • Runs pytest in Docker
    │                                    • Tool: get_file_content                    • Tool: run_in_docker
    │                                               │                                           │
    │                                               └─────────────────────┬─────────────────────┘
    │                                                                     ▼
    └──────────────(3. Update last_completed_sha)─────────────── [Aggregator Node]
                                                                         │
                                                                         ▼
                                                      [Post 1 Unified GitHub PR Review]
```

## 3. Tech Stack & Component Responsibilities

| **Component**           | **Technology**                   | **Role in the System**                                                                                                                               |
| ----------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **API Gateway**         | Python, **FastAPI**              | Exposes `POST /webhooks/github`, validates `X-Hub-Signature-256`, ignores bot-triggered events, and enqueues jobs.                                   |
| **Queue & Cache**       | **Redis** + **RQ (Redis Queue)** | Manages background worker queue, deduplicates `X-GitHub-Delivery` UUIDs, and stores `active_job_id` per PR for instant task cancellation.            |
| **Database**            | **PostgreSQL** + **SQLAlchemy**  | Stores durable PR state (`pr_reviews` table), specifically `last_completed_sha` and run audit logs.                                                  |
| **Agent Orchestration** | **LangGraph** + **Pydantic**     | Manages the state graph, parallel fan-out for Agent 1 and Agent 2, tool execution loops, and structured JSON output enforcement.                     |
| **Sandbox Runtime**     | **Docker SDK for Python**        | Spins up ephemeral, isolated containers (`python:3.11-slim`, `--network none`, `512m` RAM limit, `20s` timeout) to execute untrusted PR code safely. |

## 4. Core Features & Agent Specifications

### Backend Infrastructure Features

1. **Webhook Idempotency:** Uses Redis `SET NX EX 3600` on GitHub's delivery UUID to guarantee duplicate webhook deliveries are ignored.
2. **Rapid-Push Cancellation:** If Commit B is pushed while Commit A is still being analyzed, the system cancels Commit A's background job in Redis and starts a fresh run.
3. **Commit-Safe Incremental Diffing:**
   - If `last_completed_sha` is `NULL` (first run or previous run was cancelled before completion), diffs `base_sha ... head_sha`.
   - If `last_completed_sha` exists, diffs `last_completed_sha ... head_sha` so only new changes are reviewed.
   - Updates `last_completed_sha = head_sha` atomically in PostgreSQL **only after** the review is posted to GitHub.

### Agent 1: Static Hygiene, Security & Intent Reviewer

- **Objective:** Fast static inspection without spinning up Docker.
- **What it catches:**
  - Leftover debugging statements (`print()`, `console.log()`, `breakpoint()`).
  - Dangerous commented-out code (e.g., commented-out auth decorators, validation checks, or dead code blocks).
  - Hardcoded API keys, tokens, credentials, or local development URLs (`localhost`).
  - Obvious logic errors contradicting the PR description.
- **Agentic Tool (`get_file_content`):** When a diff hunk lacks surrounding context, Agent 1 autonomously fetches surrounding lines of the file via the GitHub API before deciding whether to flag an issue.

### Agent 2: Dynamic Sandbox & Edge-Case Prover

- **Objective:** Behavioral verification and edge-case fuzzing inside an isolated Docker container.
- **What it catches:**
  - Unhandled boundary conditions (`None`/`null` inputs, empty lists `[]`, division by zero, negative numbers, missing keys).
  - Regressions in existing unit tests caused by the PR changes.
- **Agentic Tool (`run_pytest_in_docker`) & Self-Correction Loop:**
  1. Writes a targeted `test_agent_edge_cases.py` file for modified functions.
  2. Executes `pytest` inside the Docker sandbox.
  3. **Self-Correction (Max 2 Retries):** If the test fails due to an agent syntax/import error, Agent 2 reads `stderr` and fixes its own test.
  4. **Bug Proof:** If the test crashes the developer's PR code, Agent 2 captures the exact failing input and stack trace, drafts a verified code fix, and sends it to the Aggregator.

## 5. Database Schema (PostgreSQL)

A single lean table (`pr_reviews`) tracks the state required for incremental diffing and audit metrics:

| **Column**           | **Type**             | **Description**                                                  |
| -------------------- | -------------------- | ---------------------------------------------------------------- |
| `id`                 | `SERIAL PRIMARY KEY` | Internal primary key                                             |
| `repo_full_name`     | `VARCHAR(255)`       | e.g., `"username/repo-name"`                                     |
| `pr_number`          | `INTEGER`            | GitHub Pull Request number                                       |
| `base_sha`           | `VARCHAR(40)`        | Base branch commit SHA (`main`)                                  |
| `last_completed_sha` | `VARCHAR(40) NULL`   | Last commit SHA that finished a full review and posted to GitHub |
| `status`             | `VARCHAR(50)`        | `"IDLE"`, `"RUNNING"`, `"COMPLETED"`, `"FAILED"`                 |
| `updated_at`         | `TIMESTAMP`          | Timestamp of last state transition                               |

*(Unique constraint on `(repo_full_name, pr_number)`)*

## 6. Project Folder Structure

Plaintext
```graphql
pr-review-agent/
├── ARCHITECTURE.md             # System design & documentation
├── docker-compose.yml          # FastAPI, RQ Worker, Redis, PostgreSQL
├── Dockerfile                  # App container definition
├── .env.example                # Environment variables template
├── requirements.txt            # Python dependencies
└── app/
    ├── main.py                 # FastAPI app & POST /webhooks/github endpoint
    ├── config.py               # Pydantic settings (.env loader)
    ├── db/
    │   ├── session.py          # PostgreSQL connection & SQLAlchemy setup
    │   └── models.py           # PRReview SQLAlchemy model
    ├── queue/
    │   ├── redis_conn.py       # Redis client, deduplication & cancellation helpers
    │   └── worker.py           # RQ background task entry point
    ├── github/
    │   └── client.py           # GitHub REST API wrapper (diffs, file lines, PR reviews)
    └── agents/
        ├── state.py            # LangGraph TypedDict state & Pydantic output schemas
        ├── graph.py            # LangGraph workflow (Agent 1 + Agent 2 -> Aggregator)
        ├── agent1_static.py    # Static hygiene & security node + get_file_content tool
        ├── agent2_sandbox.py   # Edge-case test generator node
        └── sandbox_runner.py   # Docker SDK container execution utility

```

## 7. Phased Implementation Roadmap

### Phase 1: The "Walking Skeleton" (End-to-End Pipeline + Agent 1)

- [x] Set up `docker-compose.yml` with FastAPI, Redis, PostgreSQL, and RQ Worker.
- [x] Implement `POST /webhooks/github` with HMAC signature verification and Redis deduplication.
- [x] Build the GitHub API client to fetch PR diffs and post inline PR review comments.
- [x] Build the LangGraph workflow with **Agent 1 (Static Reviewer)** and its `get_file_content` tool.
- [x] **Milestone Test:** Open a test PR with a leftover `print()` and a dummy API key; verify the bot posts inline comments on GitHub within 5 seconds.

### Phase 2: Concurrency Control & Incremental Diff Engine

- [x] Wire up the PostgreSQL `pr_reviews` table to track `last_completed_sha`.
- [x] Implement incremental diff calculation (`last_completed_sha ... head_sha` with fallback to `base_sha ... head_sha`).
- [x] Add Redis `active_job_id` tracking per PR to cancel in-flight worker jobs when a new commit is pushed rapidly.
- [x] **Milestone Test:** Push Commit A, then push Commit B 5 seconds later. Verify Run A is cancelled cleanly and Run B analyzes the combined diff of A + B without duplicate comments.

### Phase 3: Agent 2 (Docker Sandbox Prover) & Parallel Aggregation

- [ ] Build `sandbox_runner.py` using the Python `docker` SDK (`--network none`, memory/CPU limits, 20s timeout).
- [ ] Implement **Agent 2** in LangGraph with its 2-retry test self-correction loop.
- [ ] Connect Agent 1 and Agent 2 in parallel inside `graph.py`, merging into the `Aggregator` node to publish a single unified GitHub review.
- [ ] **Milestone Test:** Push a PR function with a division-by-zero edge case. Verify Agent 2 proves the crash inside Docker and posts the failing test + stack trace + suggested fix to the PR.

```php-template
<ElicitationsGroup message="Once you save this file, how would you like to start Phase 1?">
  <Elicitation label="Generate the Phase 1 foundation (docker-compose, config, DB, and Redis)" query="Let's start Phase 1: write the code for docker-compose.yml, requirements.txt, app/config.py, app/db/, and app/queue/redis_conn.py."/>
  <Elicitation label="Write the FastAPI webhook endpoint and GitHub API client" query="Write the code for app/main.py (GitHub webhook verification and queuing) and app/github/client.py (fetching diffs and posting reviews)."/>
  <Elicitation label="Write the LangGraph code for Agent 1 (Static Reviewer)" query="Write the Phase 1 LangGraph code in app/agents/ (state.py, agent1_static.py, and graph.py) using Pydantic structured outputs."/>
</ElicitationsGroup>
```
