import os

from fastapi import FastAPI

app = FastAPI(title="orders / backend")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def root():
    return {"service": "orders-backend", "env": os.environ.get("ENV", "unknown")}
