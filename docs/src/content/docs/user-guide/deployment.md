---
title: "Deployment"
---

This guide describes current self-managed deployment of Webuse framework projects.
The local Node orchestrator can manage schedules and runs, or a project can be
packaged as a container and run as a batch command:

```bash
webuse crawl . --spider books -o /data/books.jsonl
```

This keeps deployment simple: Docker Compose can run one-off or scheduled jobs,
and Kubernetes can run the same image as a `CronJob`.


## Project Assumptions

This guide assumes a generated project layout:

```text
books_project/
  webuse.yaml
  spiders/
    books.py
    books.yaml
```

Run commands from the project directory, or pass the project directory as the
first `webuse crawl` argument.

## Docker Image

Create a `Dockerfile` at the project root:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN uv pip install --system webuse

COPY . /app

CMD ["webuse", "crawl", ".", "--spider", "books", "-o", "/data/books.jsonl"]
```

To use a wheel built from a local checkout, follow
[Package Release](../../advanced/package-release/) and copy the wheel into the
image:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY dist/*.whl /tmp/wheels/
COPY books_project /app/books_project

RUN uv pip install --system /tmp/wheels/*.whl

WORKDIR /app/books_project
CMD ["webuse", "crawl", ".", "--spider", "books", "-o", "/data/books.jsonl"]
```

## Docker Compose

Use Compose when you want simple local deployment, local scheduling, or a shared
volume for outputs.

```yaml
services:
  books:
    build: .
    command: webuse crawl . --spider books -o /data/books.jsonl
    working_dir: /app
    environment:
      WEBUSE_ENV: production
    volumes:
      - ./data:/data
```

Run once:

```bash
docker compose run --rm books
```

Pass spider attributes, similar to Scrapy spider args:

```yaml
services:
  books:
    build: .
    command:
      - webuse
      - crawl
      - .
      - --spider
      - books
      - --attribute
      - category=fiction
      - -o
      - /data/books.jsonl
    volumes:
      - ./data:/data
```

### Scheduling with Compose

Compose itself is not a scheduler. Use the host scheduler to run the service:

```text
0 * * * * cd /srv/books_project && docker compose run --rm books
```

For production scheduling on a cluster, prefer Kubernetes `CronJob`.

### Local UI Without Docker

For ad-hoc local users, Docker is optional. With Node.js 22.19+ on PATH, launch the
compiled control plane included in the Python package:

```bash
uv add webuse
uv run webuse serve
```

Node owns SQLite, schedules, and run state. It starts one Python crawler process
per active run, so no long-running Python server is required.
The launcher opens a browser and stores data in `~/.webuse/ui`. Use
`--no-open`, `--data-dir`, and `--port` to change these defaults.
Working source lives in `workspaces/` beside the database; override this with
`WEBUSE_WORKSPACE_DIR`. Jobs run directly from working files, with outputs in
`runs/`; there are no source snapshots or copies per run. Use Git for code history
and back up SQLite separately.
See [Harness Internals](../../advanced/harness-internals/#source-development)
for the source development workflow.

The UI defaults to port 2951 for development, preview, and production. Docker
Compose publishes `2951:2951` and PM2 uses the same port. Set `PORT` to
override a direct `npm run start`, or use Vite's `--port` option for
development and preview.

For a persistent local setup without Docker, use the PM2 entrypoint:

```bash
cd ui
pm2 start ecosystem.config.cjs
```

This PM2 setup manages the single SolidStart control-plane process. Python
crawler children are started and stopped with each run. On SIGINT or SIGTERM,
the manager stops scheduling, forwards the signal to crawler process groups, and
waits for cleanup, escalating to SIGKILL after 1.5 seconds if needed. The bundled
Compose service uses an init process and a 15-second shutdown grace period.

## Output Storage

`crawl -o` selects the built-in item pipeline by extension:

* `.jsonl` writes JSON Lines
* `.csv` writes CSV
* `.sqlite`, `.sqlite3`, or `.db` writes SQLite

For containers:

* Write local outputs to a mounted volume such as `/data`.
* Use spider pipelines for durable stores such as object storage, a database,
  or a queue.
* Avoid SQLite for multi-pod writes. It is fine for one job writing one file on
  one volume.

## Kubernetes CronJob

A Kubernetes `CronJob` is the closest fit for scheduled crawls. Build and
push your project image first:

```bash
docker build -t registry.example.com/books-project:latest .
docker push registry.example.com/books-project:latest
```

Minimal CronJob:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: books-crawl
spec:
  schedule: "0 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: books
              image: registry.example.com/books-project:latest
              imagePullPolicy: IfNotPresent
              command: ["webuse"]
              args:
                - crawl
                - .
                - --spider
                - books
                - -o
                - /data/books.jsonl
              volumeMounts:
                - name: output
                  mountPath: /data
          volumes:
            - name: output
              persistentVolumeClaim:
                claimName: books-output
```

Example PVC:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: books-output
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

## Environment and Secrets

Use Kubernetes `Secret` values for API keys, proxy credentials, or shared
LLM provider keys:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: webuse-secrets
type: Opaque
stringData:
  OPENAI_API_KEY: replace-me
```

Mount them into the CronJob:

```yaml
envFrom:
  - secretRef:
      name: webuse-secrets
```

Then read them from your spider or project code using `os.environ`.

## Multiple Spiders

Use one CronJob per schedule when spiders have different timing or resource
needs:

```yaml
args:
  - crawl
  - .
  - --spider
  - inventory
  - --attribute
  - market=us
  - -o
  - /data/inventory.jsonl
```

If several spiders should always run together, list them all in the project
root `spiders` section and omit `--spider`.

## Operational Notes

* Use `concurrencyPolicy: Forbid` for crawls that must not overlap.
* Set CPU and memory requests once crawl size is known.
* Prefer pipeline-backed durable storage over reading files from completed pods.
* Keep request page types serializable. Use
  `response.follow(..., page_type="detail")` and spider `routes` instead of
  callback functions.
* Keep output filenames unique if concurrent jobs can run.

## Deploy to webuse cloud

If you don't want to manage the infrastructure yourself, you can simply deploy to
the webuse cloud, see [Webuse Cloud](../cloud/) for details.

