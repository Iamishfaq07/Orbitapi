from fastapi import FastAPI

app = FastAPI(title="OrbitAPI")


@app.get("/health")
def health():
    return {"status": "ok"}
