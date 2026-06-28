import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.exit(subprocess.call([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]))
