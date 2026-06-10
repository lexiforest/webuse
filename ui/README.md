# webuse GUI

SolidStart app for generating `webuse fetch` and `webuse crawl` task configs.

## Run

```bash
npm install
npm run dev
```

The dev server prints a local URL, usually `http://127.0.0.1:5173/`.

Run the local worker in a second process:

```bash
uv run webuse ui
```

The SolidStart API routes proxy to the worker at
`WEBUSE_WORKER_URL` or `http://127.0.0.1:8787` by default. The worker owns the
SQLite database and stores projects, jobs, logs, and imported data items.

Useful worker environment variables:

```bash
WEBUSE_DB_PATH=/data/webuse.sqlite
WEBUSE_WORK_DIR=/data/jobs
WEBUSE_WORKER_COMMAND=webuse
```

The Python worker runs crawl jobs through `python -m webuse.cli` by default.
Set `WEBUSE_WORKER_COMMAND` when you want it to launch a specific executable,
for example a project-local virtualenv command.

## PM2

PM2 is useful when you do not want Docker but still want the UI and worker to
stay running:

```bash
cd ui
pm2 start ecosystem.config.cjs
```

This still requires Node for the SolidStart UI process. The worker process is
Python and is started with `webuse ui`.

## Docker Compose

Run the UI and worker as separate services:

```bash
docker compose -f ui/compose.yaml up --build
```

The UI is exposed on `http://127.0.0.1:3000/`. The worker owns the SQLite
database in the `webuse-data` volume.

## Build

```bash
npm run build
```
