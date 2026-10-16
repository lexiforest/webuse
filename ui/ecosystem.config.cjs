module.exports = {
  apps: [{
    name: "webuse-ui",
    cwd: ".",
    script: ".output/server/index.mjs",
    interpreter: "node",
    kill_timeout: 10000,
    env: {
      HOST: "127.0.0.1",
      PORT: "2951",
      WEBUSE_PYTHON_COMMAND: "../.venv/bin/python",
    },
  }],
};
