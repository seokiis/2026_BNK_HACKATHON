from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.cases import router as cases_router
from routers.analysis import router as analysis_router
from routers.reviews import router as reviews_router
from routers.research import router as research_router

app = FastAPI(title="AI 여신심사 어시스턴트 API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 기존 라우터 (cases 기반)
app.include_router(cases_router, prefix="/api")

# 새 라우터 (프론트 직접 연동)
app.include_router(analysis_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(research_router, prefix="/api")


@app.get("/health")
def health():
    from config import get_settings
    s = get_settings()
    azure_connected = s.azure_connected
    return {
        "status": "ok",
        "azure_connected": azure_connected,
        "mode": "azure" if azure_connected else "mock",
    }
