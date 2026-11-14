import os

from fastapi import FastAPI

app = FastAPI(title="__PRODUCT__ / __NAME__")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def root():
    return {"service": "__PRODUCT__-__NAME__", "env": os.environ.get("ENV", "unknown")}
