# Product Roadmap — AI Task Planner

Target market: AI-powered agent for project managers — aids in task extraction, planning, and decision-making from meeting transcripts and SOWs.

---

## Current State
- Core AI agent pipeline: extract → normalize → match → decompose → prioritize → validate → format
- Project-scoped task isolation (thread_id = project_id)
- Async job pattern (POST /run + GET /jobs/{job_id})
- Pipeline result caching
- Streamlit UI with project selector
- Docker Compose for local full-stack dev

---

## Near Term (active)
- Extensive test runs across all 4 SOW inputs
- Agent behavior improvements and prompt tuning
- Extraction quality validation vs expected outputs

## Mid Term (next steps)
- **Auth** — user login, accounts, each user's projects isolated
  - No user login = cannot be a real product
  - Foundation already in place: project_id scopes data per project
- **Single server deployment (Step 2)** — deploy to a cloud VM (AWS EC2 / GCP / DigitalOcean)
  - Same `docker compose up` but running 24/7 on a real server
  - Gets a real public URL — sufficient for demos and early clients
  - ~$6-20/month on DigitalOcean or equivalent
- **Managed DB + hardening (Step 3)**
  - Replace Postgres container with managed DB (AWS RDS / GCP Cloud SQL) — backups, replication, failover
  - Replace raw threading with proper job queue (Celery + Redis)
  - Add reverse proxy (Nginx) in front of FastAPI
  - API authentication (JWT tokens or API keys)
  - Secrets manager instead of .env (AWS Secrets Manager / GCP Secret Manager)
  - Rate limiting on endpoints
  - Monitoring and alerting (Sentry, Datadog)

## Far Future (only if traffic justifies)
- **Kubernetes** — only when one server isn't enough
  - B2B PM tool with dozens to hundreds of concurrent users does NOT need Kubernetes
  - Real bottleneck is LLM API rate limits and cost, not server infrastructure
  - Each agent run is a long-running job (1-3 min), not high-throughput requests
  - Revisit when: multiple large enterprise clients running simultaneously, hundreds of concurrent pipeline runs
- **Dependency management** — migrate from requirements.txt to uv + pyproject.toml
- **Multi-cloud** — cloud provider chosen based on client requirements (AWS / GCP / Azure)

---

## Scaling Notes
- This is a B2B tool, not a consumer app — scaling profile is fundamentally different
- Consumer apps (millions of simultaneous users) need Kubernetes from early on
- B2B PM tools (dozens to hundreds of enterprise users) are well-served by a single well-configured server
- Do not over-engineer infrastructure before there are real users
