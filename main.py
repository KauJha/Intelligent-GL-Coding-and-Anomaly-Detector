from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402 — load_dotenv must run before env-dependent imports

from api.routes import router

app = FastAPI(title="GL Coding & Anomaly Detector", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
