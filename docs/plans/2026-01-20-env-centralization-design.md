# Environment Configuration Centralization

## Overview

Centralize all hardcoded URLs and configuration into a single source of truth with environment-based profiles (`local`, `docker`, `kubernetes`).

## File Structure

```
ultimate-rag-pipeline/
├── .env.base                    # Shared defaults (ports, model names, non-secret config)
├── .env.local                   # Local dev overrides (localhost URLs)
├── .env.docker                  # Docker Compose overrides (service name URLs)
├── .env                         # Active config (gitignored, generated from base + profile)
├── .env.example                 # Template showing all variables
├── frontend/
│   └── .env                     # Frontend-specific (generated from root)
└── services/shared/config/
    └── urls.py                  # Centralized URL constants with env overrides
```

## Implementation Phases

### Phase 1: Create centralized URL module

Create `services/shared/config/urls.py`:
- Define `DEPLOY_ENV` detection (local | docker | kubernetes)
- Host mappings per environment
- Single source of truth for ports
- Getter functions for all URLs with env var override support

### Phase 2: Create env file structure

- `.env.base` - shared defaults, ports, non-URL config
- `.env.local` - localhost URLs for local development
- `.env.docker` - Docker service name URLs
- Update `.env.example` as documentation template

### Phase 3: Update Makefile

- `env-local` target: generates `.env` from `.env.base` + `.env.local`
- `env-docker` target: generates `.env` from `.env.base` + `.env.docker`
- `env-frontend` target: generates `frontend/.env` from root config
- Update `dev` target to auto-generate `.env`

### Phase 4: Migrate service configs

Update to use centralized URL getters:
- `services/ingestion/config.py`
- `services/retrieval/config.py`
- `services/orchestrator/config.py`
- ~15 files with direct `os.getenv(..., "http://localhost:...")` patterns

### Phase 5: Simplify docker-compose.yml

- Add `env_file` directives to services
- Remove redundant hardcoded environment variables
- Keep only Docker-specific overrides (like `host.docker.internal`)

### Phase 6: Frontend sync

- Update `frontend/.env.example`
- Add Makefile target for frontend env generation
