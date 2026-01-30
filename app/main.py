from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.db.sqlite import init_db
from app.api import jobs, results, reviews

env_path = Path(__file__).resolve().parent.parent / ".env"
_ = load_dotenv(dotenv_path=env_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Sisyphus Problem Fixer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app.include_router(jobs.router, tags=["jobs"])
app.include_router(results.router, tags=["results"])
app.include_router(reviews.router, tags=["reviews"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/status/{job_id}", response_class=HTMLResponse)
async def status_page(request: Request, job_id: int):
    return templates.TemplateResponse(
        "status.html", {"request": request, "job_id": job_id}
    )


@app.get("/review/{job_id}", response_class=HTMLResponse)
async def review_page(request: Request, job_id: int):
    return templates.TemplateResponse(
        "review.html", {"request": request, "job_id": job_id}
    )
