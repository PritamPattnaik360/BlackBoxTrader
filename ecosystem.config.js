/**
 * PM2 ecosystem config — runs both backend and frontend as managed background services.
 * Usage:
 *   pm2 start ecosystem.config.js   (start everything)
 *   pm2 save                         (persist across reboots after pm2-startup)
 */
module.exports = {
  apps: [
    {
      name: 'blackbox-backend',
      cwd: './backend',
      script: 'pm2_launcher.js',
      watch: false,
      autorestart: false,
      max_memory_restart: '500M',
      kill_timeout: 5000,
      env: {
        PYTHONUNBUFFERED: '1',
      },
      out_file: '../logs/backend.log',
      error_file: '../logs/backend-error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
    {
      name: 'blackbox-frontend',
      cwd: './frontend',
      script: './node_modules/vite/bin/vite.js',
      interpreter: 'node',
      watch: false,
      autorestart: false,
      max_memory_restart: '300M',
      kill_timeout: 3000,
      out_file: '../logs/frontend.log',
      error_file: '../logs/frontend-error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
}
