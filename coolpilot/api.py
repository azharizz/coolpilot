"""Loopback-only web API. One coordinator protects benchmark comparability."""

import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import store
from .agent import execute
from .benchmark import environment
from .dataset import DATASET, manifest, prepare
from .models import RunRequest, pareto_frontier
from . import camera_dataset
from . import camera_comparison, decisions

_app_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_app_env)
_provider_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
for _key in ("AGENT_PROVIDER_API_KEY", "AGENT_PROVIDER_MODEL"):
    if not os.environ.get(_key) and _provider_env.get(_key):
        os.environ[_key] = _provider_env[_key]

tasks: dict[str, asyncio.Task] = {}
dataset_state = {"status": "preparing", "error": None}


class CameraCompareRequest(BaseModel):
    sample_time_s: float = Field(default=4.0, ge=0.0, le=60.0)
    request_decision: bool = False


async def load_dataset():
    try:
        await asyncio.to_thread(prepare)
        dataset_state["status"] = "ready"
    except Exception as error:  # noqa: BLE001 - startup boundary must report preparation failure
        dataset_state.update(
            status="failed",
            error=f"Dataset preparation failed ({type(error).__name__}). Check source connectivity and archive hashes, then restart.",
        )


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    loading = asyncio.create_task(load_dataset())
    yield
    for task in tasks.values():
        task.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)
    loading.cancel()
    await asyncio.gather(loading, return_exceptions=True)


app = FastAPI(title="COOLPilot", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
)


@app.middleware("http")
async def browser_boundary(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(
                {"detail": "Cross-origin changes are not permitted."}, status_code=403
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    with store.database() as db:
        db.execute("SELECT 1")
    return {"status": "ok", "dataset": dataset_state["status"]}


@app.get("/api/system")
def system():
    facts = environment()
    facts.pop("opencv_build")
    return {
        "runtime": facts,
        "dataset": manifest(),
        "dataset_state": dataset_state,
        "camera_datasets": camera_dataset.catalog(),
        "agent": {
            "model": os.environ.get("NEBIUS_MODEL", ""),
            "configured": all(
                os.environ.get(k)
                for k in ("NEBIUS_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL")
            ),
        },
        "cool": {
            "available": facts["distribution"] == "COOL",
            "detail": "COOL needs a licensed, compatible Graviton runtime. These local measurements use the installed OpenCV build.",
        },
    }


@app.get("/api/runs")
def runs():
    return store.list_runs()


@app.get("/api/history")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(8, ge=1, le=50),
    q: str = Query("", max_length=100),
    status: Literal["", "queued", "running", "completed", "failed", "cancelled", "interrupted"] = "",
):
    return store.history(page, page_size, q, status)


@app.post("/api/runs", status_code=201)
async def start_run(request: RunRequest):
    if request.workload == "tracking" and dataset_state["status"] != "ready":
        raise HTTPException(
            409, "The annotated dataset is not ready. Check Runtime before starting."
        )
    if request.strategy == "agent" and not all(
        os.environ.get(k) for k in ("NEBIUS_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL")
    ):
        raise HTTPException(
            409, "Configure Nebius in .env and restart before using the agent."
        )
    if request.camera:
        try:
            await asyncio.to_thread(camera_dataset.checked, request.camera)
        except (ValueError, KeyError, TypeError, OSError):
            raise HTTPException(422, "Camera dataset or frozen replay contract is invalid.") from None
    try:
        identifier = store.create_run(request.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(
            409,
            "Another run is active. Wait or cancel it before starting a new benchmark.",
        ) from None
    task = asyncio.create_task(execute(identifier))
    tasks[identifier] = task
    task.add_done_callback(lambda _: tasks.pop(identifier, None))
    return {"id": identifier}


@app.get("/api/runs/{identifier}")
def run(identifier: str):
    result = store.get_run(identifier)
    if result is None:
        raise HTTPException(404, "Run not found.")
    result["frontier"] = pareto_frontier(
        [e for e in result["experiments"] if not e["kind"].endswith("validation")]
    )
    return result


@app.post("/api/runs/{identifier}/cancel")
async def cancel(identifier: str):
    task = tasks.get(identifier)
    if task is None:
        raise HTTPException(409, "This run is not active.")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if store.get_run(identifier)["status"] == "queued":
        store.update_run(
            identifier, status="cancelled", error="Cancelled before execution started."
        )
    return {"status": "cancelled"}


@app.get("/api/runs/{identifier}/export")
def export(identifier: str):
    result = store.get_run(identifier, full=True)
    if result is None:
        raise HTTPException(404, "Run not found.")
    return JSONResponse(
        {"schema_version": 2, "dataset": result["experiments"][0].get("dataset") if result["request"].get("camera") and result["experiments"] else manifest(), "run": result},
        headers={
            "Content-Disposition": f'attachment; filename="coolpilot-{result["id"]}.json"'
        },
    )


@app.get("/api/experiments/{identifier}")
def experiment(identifier: int):
    result = store.experiment(identifier, trace=True)
    if result is None:
        raise HTTPException(404, "Experiment not found.")
    return result


@app.get("/api/camera/{dataset}/{clip}/video")
def camera_video(dataset: str, clip: str):
    try:
        data = camera_dataset.load(dataset)
        item = next(c for c in data["clips"] if c["id"] == clip)
        return FileResponse(item["file"], media_type="video/mp4", headers={"Cache-Control": "no-store"})
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        raise HTTPException(404, "Registered camera clip not found.") from None


@app.get("/api/camera-comparison")
def camera_comparison_sources():
    return {
        "sources": [
            {"id": camera, "label": info["label"], "video_url": f"/api/camera-comparison/{camera}/video"}
            for camera, info in camera_comparison.CAMERAS.items()
        ],
        "decision_configured": decisions.configured(),
        **environment(),
    }


@app.get("/api/camera-comparison/{camera}/video")
def camera_comparison_video(camera: str):
    try:
        return FileResponse(camera_comparison.video_path(camera), media_type="video/mp4", headers={"Cache-Control": "no-store"})
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Camera comparison video is not available.") from None


@app.post("/api/camera-comparison/analyze")
def analyze_camera_comparison(request: CameraCompareRequest):
    try:
        return camera_comparison.compare(request.sample_time_s, request.request_decision)
    except FileNotFoundError:
        raise HTTPException(404, "Camera comparison videos are not available.") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/frames/{split}/{index}")
def frame(split: str, index: int):
    if (
        split not in ("tuning", "validation")
        or not 0 <= index < 1000
        or manifest() is None
    ):
        raise HTTPException(404, "Frame not found.")
    # Names come from the prepared dataset, never from a user-supplied filesystem path.
    info = manifest()
    path = sorted((DATASET / "img").glob("*.jpg"))[
        info["splits"][split]["start"] + index
    ]
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/active")
def active(workload: Literal["tracking", "camera_health"] = "tracking"):
    return store.active_configuration(workload)


@app.post("/api/experiments/{identifier}/apply")
def apply(identifier: int):
    try:
        return store.promote(identifier)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@app.post("/api/active/rollback")
def rollback(workload: Literal["tracking", "camera_health"] = "tracking"):
    try:
        return store.rollback(workload)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@app.post("/api/active/benchmark", status_code=201)
async def benchmark_active(workload: Literal["tracking", "camera_health"] = "tracking"):
    current = store.active_configuration(workload)
    if current is None:
        raise HTTPException(409, "Apply a validated configuration first.")
    original = store.get_run(current["experiment"]["run_id"])
    values = {**original["request"], "name": "Active configuration verification", "strategy": "baseline"}
    if workload == "camera_health":
        values["camera"] = {**values["camera"], "baseline": current["experiment"]["config"]}
    else:
        values["baseline"] = current["experiment"]["config"]
    request = RunRequest.model_validate(values)
    return await start_run(request)


STATIC = Path(__file__).resolve().parent.parent / "web" / "dist"
if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
