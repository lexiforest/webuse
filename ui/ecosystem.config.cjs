const workerScript =
  process.env.WEBUSE_PM2_WORKER ||
  (process.platform === "win32" ? ".venv\\Scripts\\webuse.exe" : ".venv/bin/webuse");

module.exports = {
  apps: [
    {
      name: "webuse-worker",
      cwd: "..",
      script: workerScript,
      args: "ui --host 127.0.0.1 --port 8787 --db-path ui/webuse.sqlite --work-dir ui/jobs",
      interpreter: "none",
      env: {
        WEBUSE_WORKER_COMMAND: workerScript,
      },
    },
    {
      name: "webuse-ui",
      cwd: ".",
      script: "npm",
      args: "run start",
      env: {
        WEBUSE_WORKER_URL: "http://127.0.0.1:8787",
        HOST: "127.0.0.1",
        PORT: "3000",
      },
    },
  ],
};
