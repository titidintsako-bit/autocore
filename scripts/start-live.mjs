import { spawn } from "node:child_process";

const containment = process.argv.includes("--containment");
const env = {
  ...process.env,
  AUTOCORE_MODE: process.env.AUTOCORE_MODE ?? "live",
  AUTOCORE_HOST: process.env.AUTOCORE_HOST ?? "127.0.0.1",
  AUTOCORE_PORT: process.env.AUTOCORE_PORT ?? "8787",
};

if (containment) {
  env.AUTOCORE_ENABLE_DOCKER_CONTAINMENT = "1";
}

console.log(`AutoCore live mode: http://127.0.0.1:${env.AUTOCORE_PORT}`);
console.log(containment ? "Docker containment requested for eligible static checks." : "Using guarded local policy.");

const child = spawn("python", ["-m", "autocore.server"], {
  env,
  stdio: "inherit",
  shell: false,
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 0);
});
