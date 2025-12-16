from fastapi import FastAPI

app = FastAPI(title="Personal Assistant")

@app.get("/health")
def health():
    return {"status": "ok"}