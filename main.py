from fastapi import FastAPI
app=FastAPI(title="Pxxl FastAPI")
@app.get("/")
def root(): return {"service":"Pxxl FastAPI"}
@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/api")
def api(): return {"message":"Hello from FastAPI"}