# Why Plane isn't in docker-compose.yml

Plane's official self-hosted stack builds ~8 application services from
source (`web`, `admin`, `space`, `api`, `worker`, `beat-worker`, `migrator`,
`live`) on top of 5 infra containers (postgres, redis, rabbitmq, minio,
proxy). Vendoring that into this repo would mean maintaining a second,
drifting copy of Plane's own deployment — and it would make this repo look
like a Plane hosting project instead of an automation-agent project.

Since the orchestrator only ever talks to Plane over its REST API, it
doesn't matter *how* Plane is hosted. Pick one:

## Option A — Plane Cloud (fastest)

1. Create a free workspace at https://app.plane.so.
2. Create a project to use as the demo project.
3. Generate a personal API token: workspace settings → API tokens.
4. Set in `.env`:
   ```
   PLANE_API_BASE_URL=https://api.plane.so
   PLANE_API_KEY=<your token>
   PLANE_WORKSPACE_SLUG=<your workspace slug>
   ```

## Option B — Self-hosted Plane

1. Clone `https://github.com/makeplane/plane` into a sibling directory
   (not inside this repo) and follow their `docker-compose.yml` / setup
   script to bring it up on its own ports.
2. Generate an API token from the self-hosted instance's workspace
   settings the same way as Option A.
3. Point `PLANE_API_BASE_URL` at your instance (e.g.
   `http://localhost:3000/api`) instead of `https://api.plane.so`.

Either way, the connector in
[`app/src/app/connectors/plane.py`](../app/src/app/connectors/plane.py)
is the only place that needs to know the base URL — the pipeline code
doesn't care which option you chose.
