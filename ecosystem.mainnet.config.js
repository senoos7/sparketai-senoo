// PM2 ecosystem config for Sparket MAINNET miner.
// Reads environment from `.env.mainnet` (instead of `.env`).
//
// Launch:   pm2 start ecosystem.mainnet.config.js
// Monitor:  pm2 logs sparket-miner-mainnet
// Stop:     pm2 stop sparket-miner-mainnet

const fs = require('fs');
const path = require('path');

function loadEnvFile(envPath) {
  const env = {};
  try {
    if (fs.existsSync(envPath)) {
      const content = fs.readFileSync(envPath, 'utf8');
      for (const line of content.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const match = trimmed.match(/^([^=]+)=(.*)$/);
        if (match) {
          const key = match[1].trim();
          let value = match[2].trim();
          if ((value.startsWith('"') && value.endsWith('"')) ||
              (value.startsWith("'") && value.endsWith("'"))) {
            value = value.slice(1, -1);
          }
          env[key] = value;
        }
      }
    }
  } catch (err) {
    console.error(`Error loading .env.mainnet: ${err.message}`);
  }
  return env;
}

const projectRoot = process.env.PROJECT_ROOT || path.resolve(__dirname);
const envPath = path.join(projectRoot, '.env.mainnet');
const envVars = loadEnvFile(envPath);

const interpreter = path.join(projectRoot, '.venv', 'bin', 'python');
const scriptPath = path.join(projectRoot, 'sparket/entrypoints/miner.py');
const logDir = path.join(projectRoot, 'sparket', 'logs', 'pm2-mainnet');

try { fs.mkdirSync(logDir, { recursive: true }); } catch (_) {}

console.log(
  `[mainnet] Loaded ${Object.keys(envVars).length} env vars from ${envPath}`
);

module.exports = {
  apps: [
    {
      name: 'sparket-miner-mainnet',
      script: scriptPath,
      interpreter,
      cwd: projectRoot,
      instances: 1,
      exec_mode: 'fork',
      env: {
        NODE_ENV: 'production',
        PYTHONUNBUFFERED: '1',
        SPARKET_ROLE: 'miner',
        PROJECT_ROOT: projectRoot,
        VENV_PYTHON: interpreter,
        SPARKET_AXON__HOST: '0.0.0.0',
        SPARKET_AXON__PORT: envVars.SPARKET_AXON__PORT || '8094',
        SPARKET_MINER_CONFIG_FILE: path.join(
          projectRoot, 'sparket', 'config', 'miner.mainnet.yaml'
        ),
        SPARKET_CONFIG_FILE: path.join(
          projectRoot, 'sparket', 'config', 'miner.mainnet.yaml'
        ),
        ...envVars,
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '4G',
      min_uptime: '30s',
      max_restarts: 15,
      restart_delay: 5000,
      error_file: path.join(logDir, 'error.log'),
      out_file: path.join(logDir, 'out.log'),
      log_file: path.join(logDir, 'combined.log'),
      time: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      kill_timeout: 10000,
    },
  ],
};
