"""Start the local web UI:  python run.py  ->  http://127.0.0.1:8080"""
import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8080")).start()
    uvicorn.run("app.server:app", host="0.0.0.0", port=8080, log_level="warning")
