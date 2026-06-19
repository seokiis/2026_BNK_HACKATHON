from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.cases import router as cases_router

app = FastAPI(title="AI 여신심사 어시스턴트 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "null", "*"],  # React dev server + HTML 직접 열기
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
