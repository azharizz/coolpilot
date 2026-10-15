"""Loopback-only web API. One coordinator protects benchmark comparability."""

import asyncio
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Lock
from typing import Literal
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv
from pydantic import Field, model_validator
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import store
from .agent import execute
from .runtime import environment
from .models import CameraConfiguration, Contract, RunRequest
from . import camera_dataset
from . import decisions
from .simulation import camera_comparison

_app_env = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_app_env)
_provider_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
for _key in ("AGENT_PROVIDER_API_KEY", "AGENT_PROVIDER_MODEL"):
    if not os.environ.get(_key) and _provider_env.get(_key):
        os.environ[_key] = _provider_env[_key]

tasks: dict[str, asyncio.Task] = {}
comparison_active = False


class CameraCompareRequest(Contract):
    faults: dict[Literal["left", "centre", "right"],
                 Literal["random", "reference", "blur", "underexposure", "glare", "obstruction", "blackout", "freeze",
                         "interruption", "jitter", "decode_failure", "timestamp_fault", "processing_delay", "resolution"]] = Field(
                     default_factory=lambda: dict.fromkeys(camera_comparison.CAMERAS, "random"),
                     min_length=3, max_length=3)
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)
    mode: Literal["local", "scheduled", "hybrid"] = "local"
    review_interval_s: Literal[1, 2, 5] = 5
    review_limit: int = Field(default=4, ge=1, le=10)
    api_timeout_s: float = Field(default=5, ge=1, le=20)
    allow_image_requests: bool = False

    @model_validator(mode="after")
    def image_consent(self):
        if self.mode != "local" and not self.allow_image_requests:
            raise ValueError("Remote review requires explicit image-upload consent.")
        return self


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield
    for task in tasks.values():
        task.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)


app = FastAPI(title="COOLPilot", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
)

@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, error: RequestValidationError):
    # Do not echo inputs: non-finite JSON values cannot be serialized, and inputs can contain secrets.
    return JSONResponse(status_code=422, content={"detail": [
        {key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()
    ]})


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
    return {"status": "ok"}


@app.get("/api/system")
def system():
    facts = environment()
    facts.pop("opencv_build")
    return {
        "runtime": facts,
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
            "detail": "COOL is a licensed OpenCV distribution for supported AWS Graviton hosts, not an OpenCV version flag. Detection uses the vendor /opt/cool/ module location on Linux ARM64; license and speedup are not verified. Upgrading the standard wheel does not enable COOL.",
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
    if request.strategy == "agent" and not all(
        os.environ.get(k) for k in ("NEBIUS_MODEL", "NEBIUS_API_KEY", "NEBIUS_BASE_URL")
    ):
        raise HTTPException(
            409, "Configure Nebius in .env and restart before using the agent."
        )
    try:
        await asyncio.to_thread(camera_dataset.checked, request.camera)
    except (ValueError, KeyError, TypeError, OSError):
        raise HTTPException(422, "Camera dataset or frozen replay contract is invalid.") from None
    if comparison_active:
        raise HTTPException(409, "A three-camera comparison is active. Wait for it to finish.")
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
        {"schema_version": 3, "dataset": result["experiments"][0].get("dataset") if result["experiments"] else None, "run": result},
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
        "faults": ("random", "reference", *camera_comparison.STREAM_FAULTS),
        **environment(),
    }


@app.get("/api/camera-comparison/{camera}/video")
def camera_comparison_video(camera: str):
    try:
        return FileResponse(camera_comparison.video_path(camera), media_type="video/mp4", headers={"Cache-Control": "no-store"})
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Camera comparison video is not available.") from None


@app.post("/api/camera-comparison/analyze")
async def analyze_camera_comparison(request: CameraCompareRequest):
    global comparison_active
    if comparison_active or tasks:
        raise HTTPException(409, "Another measurement is active. Wait for it to finish.")
    if request.mode != "local" and not decisions.configured():
        raise HTTPException(422, "The Decisions model/key is not configured. Local replay remains available.")
    comparison_active = True
    cancel, lock = Event(), Lock()
    latest = {}

    def emit(message):
        # Bounded latest state per camera: a slow browser never stalls image analysis.
        with lock:
            latest[message.get("camera", "ready")] = message

    async def measure():
        global comparison_active
        try:
            config = CameraConfiguration(width=320, mode=request.mode, review_interval_s=request.review_interval_s)
            return await asyncio.to_thread(camera_comparison.compare, request.faults, config,
                                           request.review_limit, request.api_timeout_s, emit, cancel, request.seed)
        finally:
            comparison_active = False

    worker = asyncio.create_task(measure())

    async def stream():
        try:
            while True:
                with lock:
                    messages = list(latest.values())
                    latest.clear()
                for message in messages:
                    yield json.dumps(message, allow_nan=False) + "\n"
                if worker.done():
                    # Drain again: the worker can publish between the preceding drain and done().
                    with lock:
                        messages = list(latest.values())
                        latest.clear()
                    for message in messages:
                        yield json.dumps(message, allow_nan=False) + "\n"
                    yield json.dumps(await worker, allow_nan=False) + "\n"
                    break
                await asyncio.sleep(0.1)
        except Exception as error:
            logging.getLogger(__name__).exception("Three-camera replay failed")
            yield json.dumps({"type": "error", "error": f"Replay failed ({type(error).__name__}). Check local service logs."}) + "\n"
        finally:
            cancel.set()
            # Do not release the coordinator until the actual worker and outstanding reviews exit.
            # Retrieve failures even if the browser disconnected before the result.
            worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"X-Accel-Buffering": "no"})


@app.get("/api/active")
def active(workload: Literal["camera_health"] = "camera_health"):
    return store.active_configuration(workload)


@app.post("/api/experiments/{identifier}/apply")
def apply(identifier: int):
    try:
        return store.promote(identifier)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@app.post("/api/active/rollback")
def rollback(workload: Literal["camera_health"] = "camera_health"):
    try:
        return store.rollback(workload)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@app.post("/api/active/benchmark", status_code=201)
async def benchmark_active(workload: Literal["camera_health"] = "camera_health"):
    current = store.active_configuration(workload)
    if current is None:
        raise HTTPException(409, "Apply a validated configuration first.")
    original = store.get_run(current["experiment"]["run_id"])
    # Old camera evidence can contain now-retired top-level tracking parameters.
    values = {k: v for k, v in original["request"].items() if k in RunRequest.model_fields}
    values.update(name="Active configuration verification", strategy="baseline")
    values["camera"] = {**values["camera"], "baseline": current["experiment"]["config"]}
    request = RunRequest.model_validate(values)
    return await start_run(request)


STATIC = Path(__file__).resolve().parent.parent / "web" / "dist"
if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
