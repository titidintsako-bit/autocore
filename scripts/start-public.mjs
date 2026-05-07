import { spawn } from "node:child_process";

const env = {
  ...process.env,
  AUTOCORE_MODE: process.env.AUTOCORE_MODE ?? "public",
  AUTOCORE_HOST: process.env.AUTOCORE_HOST ?? "0.0.0.0",
  AUTOCORE_PORT: process.env.AUTOCORE_PORT ?? "8787",
  AUTOCORE_STATIC_DIR: process.env.AUTOCORE_STATIC_DIR ?? "dist",
};

console.log(`AutoCore public mode: http://127.0.0.1:${env.AUTOCORE_PORT}`);
console.log("Serving the built UI with read-only demo APIs.");

const child = spawn("python", ["-m", "autocore.server"], {
  env,
  stdio: "inherit",
  shell: false,
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 0);
});
