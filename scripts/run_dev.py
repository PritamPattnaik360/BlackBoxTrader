"""Start backend (uvicorn) and frontend (Vite) concurrently on Windows."""
import subprocess
import sys
import os
import signal
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT, "backend")
FRONTEND_DIR = os.path.join(ROOT, "frontend")

procs = []


def cleanup(*_):
    print("\nShutting down...")
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def main():
    print("Starting BlackBoxTrader dev servers...\n")

    # Backend
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        cwd=BACKEND_DIR,
    )
    procs.append(backend)
    print(f"Backend:  http://localhost:8000  (PID {backend.pid})")

    time.sleep(2)  # Give backend a moment to start

    # Frontend
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend = subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND_DIR, shell=False)
    procs.append(frontend)
    print(f"Frontend: http://localhost:5173  (PID {frontend.pid})")

    print("\nPress Ctrl+C to stop both servers\n")

    while True:
        for p in procs:
            if p.poll() is not None:
                print(f"Process {p.pid} exited with code {p.returncode}")
                cleanup()
        time.sleep(1)


if __name__ == "__main__":
    main()
