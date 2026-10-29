"""FastAPI application for Lok Sabha RAG."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from lok_sabha_rag.api.routes import search, synthesize, members, ministries, stats, question_text, debug, profiles
from lok_sabha_rag.api.routes import corpus
from lok_sabha_rag.api.routes import rs_documents
from lok_sabha_rag.api.routes import bills
from lok_sabha_rag.api.routes import record_people
from lok_sabha_rag.api.routes import rs_profiles
from lok_sabha_rag.api.routes import minister_directory

app = FastAPI(
    title="Lok Sabha RAG",
    description="Search and synthesize answers from Lok Sabha Q&A documents",
    version="0.1.0",
)


@app.get('/api/ai-status')
def ai_status():
    from lok_sabha_rag.core.ai_provider import configuration
    return configuration()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(synthesize.router, prefix="/api", tags=["synthesize"])
app.include_router(members.router, prefix="/api", tags=["members"])
app.include_router(ministries.router, prefix="/api", tags=["ministries"])
app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(question_text.router, prefix="/api", tags=["question-text"])
app.include_router(debug.router, prefix="/api/debug", tags=["debug"])
app.include_router(profiles.router, prefix="/api", tags=["profiles"])
app.include_router(corpus.router, prefix='/api', tags=['coverage'])
app.include_router(rs_documents.router, prefix='/api', tags=['documents'])
app.include_router(bills.router, prefix='/api', tags=['bills'])
app.include_router(record_people.router, prefix='/api', tags=['record-people'])
app.include_router(rs_profiles.router, prefix='/api', tags=['rajya-sabha-profiles'])
app.include_router(minister_directory.router, prefix='/api', tags=['minister-directory'])

FRONTEND_DIR = Path(__file__).parent.parent.parent.parent / "frontend"


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get('/bills')
def serve_bills():
    return FileResponse(FRONTEND_DIR / 'bills.html')


@app.get('/ministers')
def serve_ministers():
    return FileResponse(FRONTEND_DIR / 'ministers.html')


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

