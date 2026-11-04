"""Start MineSight with one command:  python run.py   (then open http://localhost:8000)"""
import os, sys, socket, subprocess, threading, webbrowser
if sys.version_info < (3, 8): sys.exit("MineSight needs Python 3.8 or newer. You have " + sys.version.split()[0])
os.chdir(os.path.dirname(os.path.abspath(__file__)))
try:
    import fastapi, uvicorn, sklearn, pandas, numpy, joblib, pydantic
except ImportError:
    print("Installing requirements (first run only)...")
    if subprocess.call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]):
        sys.exit("Install failed. Try a virtual environment:\n  python -m venv venv\n  (Windows) venv\\Scripts\\activate   (Mac/Linux) source venv/bin/activate\n  python run.py")
port = int(os.getenv("PORT", "8000"))
with socket.socket() as s:
    if s.connect_ex(("127.0.0.1", port)) == 0: sys.exit(f"Port {port} is already in use. Close the other program or run with PORT=8001 python run.py")
if not os.path.exists("model.joblib"):
    print("Training the prediction model (about 30 seconds)..."); subprocess.check_call([sys.executable, "train.py"])
print(f"\nMineSight is running. Open http://localhost:{port}  (press Ctrl+C to stop)\n")
threading.Timer(2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
import uvicorn; uvicorn.run("app:app", host="127.0.0.1", port=port)
