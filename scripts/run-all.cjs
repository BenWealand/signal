const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const backendDir = path.join(root, "backend");
const isWindows = process.platform === "win32";
const npmCmd = isWindows ? "npm.cmd" : "npm";
const nodeCmd = isWindows ? "node.exe" : "node";

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {};
  const values = {};
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

const fileEnv = {
  ...loadEnvFile(path.join(root, ".env")),
  ...loadEnvFile(path.join(backendDir, ".env")),
};
const env = { ...fileEnv, ...process.env };

function runStep(label, command, args, options = {}) {
  console.log(`\n[signal] ${label}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    env: { ...env, ...(options.env || {}) },
    stdio: "inherit",
    shell: false,
  });

  if (result.error) {
    throw new Error(`${label} failed: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`${label} exited with code ${result.status}`);
  }
}

function runCapture(label, command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    env: { ...env, ...(options.env || {}) },
    encoding: "utf8",
    shell: false,
  });
  if (result.error) {
    throw new Error(`${label} failed: ${result.error.message}`);
  }
  return result;
}

function canRun(command, args = ["--version"]) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "ignore",
    shell: false,
  });
  return !result.error && result.status === 0;
}

function findPython() {
  const candidates = isWindows ? ["python.exe", "py.exe", "python"] : ["python3", "python"];
  return candidates.find((candidate) => canRun(candidate));
}

function pythonExecutablePath(python) {
  const result = runCapture("checking Python executable", python, ["-c", "import sys; print(sys.executable)"]);
  return (result.stdout || "").trim();
}

function hasActiveVirtualenv(python) {
  if (env.VIRTUAL_ENV || env.CONDA_PREFIX) return true;
  const exe = pythonExecutablePath(python).toLowerCase();
  const backendVenv = path.join(backendDir, ".venv").toLowerCase();
  return exe.startsWith(backendVenv);
}

function assertDatabaseUrl() {
  const databaseUrl = (env.DATABASE_URL || "").trim();
  if (!databaseUrl) {
    throw new Error(
      "DATABASE_URL is required. Create a PostgreSQL database, then set DATABASE_URL in .env, backend/.env, or your shell."
    );
  }
  if (!/^postgres(ql)?:\/\//i.test(databaseUrl)) {
    throw new Error("DATABASE_URL must be a PostgreSQL URL. The current backend uses psycopg2, not SQLite.");
  }
}

function checkDatabaseConnectivity(python) {
  console.log("\n[signal] checking PostgreSQL connectivity");
  const code = [
    "import os, sys",
    "try:",
    "    import psycopg2",
    "except Exception as exc:",
    "    print(f'psycopg2 import failed: {exc}', file=sys.stderr)",
    "    sys.exit(2)",
    "url = os.environ.get('DATABASE_URL', '')",
    "try:",
    "    conn = psycopg2.connect(url, connect_timeout=8)",
    "    conn.close()",
    "except Exception as exc:",
    "    print(f'DATABASE_URL connection failed: {exc}', file=sys.stderr)",
    "    sys.exit(3)",
  ].join("\n");
  const result = spawnSync(python, ["-c", code], {
    cwd: backendDir,
    env,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) {
    throw new Error(`database connectivity check failed: ${result.error.message}`);
  }
  if (result.status === 2) {
    throw new Error("psycopg2 is not installed. Install backend requirements first.");
  }
  if (result.status !== 0) {
    throw new Error("Could not connect to PostgreSQL. Check DATABASE_URL, network access, password, and sslmode.");
  }
}

function startProcess(label, command, args, options = {}) {
  console.log(`[signal] starting ${label}`);
  const child = spawn(command, args, {
    cwd: options.cwd || root,
    env: { ...env, ...(options.env || {}) },
    stdio: "inherit",
    shell: false,
  });

  child.on("exit", (code) => {
    if (!shuttingDown) {
      console.log(`[signal] ${label} exited with code ${code}`);
      shutdown(code || 0);
    }
  });

  child.on("error", (error) => {
    console.error(`[signal] ${label} failed: ${error.message}`);
    shutdown(1);
  });

  children.push(child);
  return child;
}

let shuttingDown = false;
const children = [];

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill();
  }
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

try {
  const python = findPython();
  if (!python) {
    throw new Error("Python was not found. Install Python 3.11+ or make python.exe/python3 available on PATH.");
  }

  assertDatabaseUrl();

  if (!fs.existsSync(path.join(root, "node_modules"))) {
    runStep("installing frontend dependencies", npmCmd, ["install"]);
  }

  const inVenv = hasActiveVirtualenv(python);
  if (!inVenv && env.SIGNAL_ALLOW_GLOBAL_PIP !== "1") {
    throw new Error(
      "Refusing to install Python packages outside a virtualenv. Run `cd backend && python -m venv .venv && .venv\\Scripts\\activate`, then retry. Set SIGNAL_ALLOW_GLOBAL_PIP=1 only if you intentionally want a global install."
    );
  }
  if (!inVenv) {
    console.warn("[signal] WARNING: installing backend dependencies outside a virtualenv because SIGNAL_ALLOW_GLOBAL_PIP=1.");
  }

  runStep("installing backend core dependencies", python, ["-m", "pip", "install", "-r", "requirements-core.txt", "--disable-pip-version-check"], {
    cwd: backendDir,
  });
  checkDatabaseConnectivity(python);

  runStep("building frontend", npmCmd, ["run", "build"], {
    env: { VITE_SIGNAL_API_URL: env.VITE_SIGNAL_API_URL || "http://127.0.0.1:8000" },
  });
  runStep("creating backend tables", python, ["scripts/create_tables.py"], { cwd: backendDir });
  runStep("seeding source registry", python, ["scripts/seed_sources.py"], { cwd: backendDir });
  runStep("loading sample articles", python, ["scripts/load_sample_articles.py"], { cwd: backendDir });
  if (env.RSS_FEEDS) {
    runStep("fetching configured RSS feeds", python, ["scripts/fetch_rss.py"], { cwd: backendDir });
  }
  if (env.GDELT_QUERIES) {
    runStep("fetching GDELT candidates", python, ["scripts/fetch_gdelt.py"], { cwd: backendDir });
  }
  runStep("running backend article pipeline", python, ["scripts/run_pipeline.py"], { cwd: backendDir });

  console.log("\n[signal] ready");
  console.log("[signal] frontend: http://127.0.0.1:5175/");
  console.log("[signal] backend:  http://127.0.0.1:8000/");
  console.log("[signal] docs:     http://127.0.0.1:8000/docs");
  console.log("[signal] press Ctrl+C to stop both servers\n");

  startProcess("backend API", python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: backendDir,
  });
  startProcess("frontend", nodeCmd, ["serve-dist.cjs"], {
    cwd: root,
    env: { PORT: "5175" },
  });
} catch (error) {
  console.error(`\n[signal] ${error.message}`);
  process.exit(1);
}
