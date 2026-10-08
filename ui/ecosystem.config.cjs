module.exports = {
  apps: [{
    name: "webuse-ui",
    cwd: ".",
    script: "npm",
    args: "run start",
    env: {
      HOST: "127.0.0.1",
      PORT: "2951",
      WEBUSE_PYTHON_COMMAND: "../.venv/bin/python",
    },
  }],
};
