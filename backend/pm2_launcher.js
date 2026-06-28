const { spawn, execSync } = require('child_process');

// Resolve the real Python path once using the shell, then spawn without shell
let pythonPath = 'python3';
try {
  pythonPath = execSync('where python3', { windowsHide: true, shell: true })
    .toString().split('\n')[0].trim();
} catch {
  try {
    pythonPath = execSync('where python', { windowsHide: true, shell: true })
      .toString().split('\n')[0].trim();
  } catch {}
}

const proc = spawn(pythonPath, ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8001'], {
  cwd: __dirname,
  shell: false,
  windowsHide: true,
  stdio: 'inherit',
  env: { ...process.env, PYTHONUNBUFFERED: '1' },
});

proc.on('exit', (code) => process.exit(code ?? 1));
