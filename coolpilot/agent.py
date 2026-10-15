"""The real provider/tool loop and its serialized, recoverable run lifecycle."""

import asyncio
import json
import os
import random
import signal
import sys

import httpx
from pydantic import ValidationError

from . import store
from .runtime import environment
from .dataset import DATA
from .camera_dataset import checked, public
from .camera_health import gate as camera_gate
from .models import CameraConfiguration, CameraProposal, FinishProposal, RunRequest

CAMERA_SYSTEM = """You optimize a timestamped camera-health replay, not camera hardware.
Minimize measured CPU seconds per camera-second subject to EVERY declared gate.
Use only the finite run_experiment schema. Never change thresholds, labels, splits,
delivery schedules, stream count or acceptance limits. Image review requires explicit permission.
Tool results contain tuning evidence only. Do not infer physical dirt or safety from image symptoms.
Failures, unknown states and rejected candidates are evidence, not successful improvements.
Call finish with a brief evidence-based summary. Held-out validation follows without further search.
Never claim COOL acceleration, AWS execution or agent advantage without matched measurements."""


def tool(name: str, description: str, schema) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema.model_json_schema(),
        },
    }


TOOLS = [
    tool(
        "run_experiment",
        "Measure one bounded camera-health configuration on the fixed tuning recordings.",
        CameraProposal,
    ),
    tool(
        "finish",
        "Stop searching and summarize the observed results. Held-out validation follows.",
        FinishProposal,
    ),
]


class ProviderError(Exception):
    """A provider failure safe to persist and show in the UI."""


async def provider(
    messages: list[dict], available_tools: list[dict]
) -> tuple[dict, dict]:
    settings = {
        name: os.environ.get(name, "")
        for name in ("NEBIUS_BASE_URL", "NEBIUS_API_KEY", "NEBIUS_MODEL")
    }
    if not all(settings.values()):
        raise ProviderError(
            "Configure NEBIUS_MODEL, NEBIUS_API_KEY and NEBIUS_BASE_URL in .env, then restart."
        )
    # No elapsed-time cutoff: cancellation closes the request. Never log headers or provider bodies.
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            response = await client.post(
                settings["NEBIUS_BASE_URL"].rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + settings["NEBIUS_API_KEY"]},
                json={
                    "model": settings["NEBIUS_MODEL"],
                    "messages": messages,
                    "tools": available_tools,
                    "tool_choice": "auto",
                    "max_tokens": 8192,
                },
            )
        except httpx.RequestError as error:
            raise ProviderError(
                "Nebius connection failed. Check provider connectivity, then start a new run."
            ) from error
    if response.status_code != 200:
        raise ProviderError(
            f"Nebius returned HTTP {response.status_code}. Check credentials, model access or quota, then start a new run."
        )
    try:
        payload = response.json()
        choice = payload["choices"][0]
        message = choice["message"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ProviderError(
            "Nebius returned an invalid completion envelope. No substitute optimizer was used."
        ) from error
    if choice.get("finish_reason") == "length":
        raise ProviderError(
            "Nebius exhausted the per-response token budget. No partial tool call was executed."
        )
    # Persist public answers and tool calls only, never hidden reasoning fields.
    answer = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        answer["tool_calls"] = message["tool_calls"]
    return answer, payload.get("usage", {})


async def measure(
    run_id: str, request: RunRequest, config: CameraConfiguration, kind: str, rationale: str
) -> dict:
    identifier = store.start_experiment(run_id, kind, config.model_dump(), rationale)
    store.event(
        run_id,
        "experiment_started",
        {"experiment_id": identifier, "kind": kind, "rationale": rationale},
    )
    folder = DATA / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    config_path = folder / f"{identifier}-config.json"
    config_path.write_text(config.model_dump_json())
    request_path = folder / "request.json"
    request_path.write_text(request.model_dump_json())
    args = [sys.executable, "-m", "coolpilot.simulation.camera_benchmark", "--request", str(request_path),
            "--config", str(config_path), "--split", "validation" if kind.endswith("validation") else "tuning"]
    environment_variables = {
        k: v for k, v in os.environ.items()
        if not k.startswith("NEBIUS_") and (request.camera.allow_image_requests or not k.startswith("AGENT_PROVIDER_"))
    }
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        env=environment_variables,
    )
    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await process.wait()
        store.fail_experiment(
            identifier, "Cancelled before measurement completed.", "cancelled"
        )
        raise
    if process.returncode:
        (folder / f"{identifier}-error.log").write_bytes(stderr)
        store.fail_experiment(
            identifier,
            f"Benchmark process exited with code {process.returncode}. See its local error log.",
        )
        return store.experiment(identifier)
    try:
        result = json.loads(stdout)
        gate = camera_gate(result["metrics"], request.camera.goals)
    except (ValueError, KeyError, TypeError) as error:
        store.fail_experiment(
            identifier, "Benchmark output was not a valid measurement."
        )
        raise RuntimeError("Invalid benchmark output") from error
    (folder / f"{identifier}-result.json").write_bytes(stdout)
    store.finish_experiment(identifier, result, gate)
    store.event(
        run_id,
        "experiment_completed",
        {
            "experiment_id": identifier,
            "passed": gate["passed"],
            "metrics": result["metrics"],
        },
    )
    return store.experiment(identifier)


def evidence(experiment: dict) -> dict:
    return {
        k: experiment[k]
        for k in ("id", "config", "metrics", "gate", "status", "error")
        if k in experiment
    }


async def optimize(run_id: str, request: RunRequest, baseline: dict) -> str:
    dataset = public(checked(request.camera, verify=False))
    dataset["clips"] = [c for c in dataset["clips"] if c["split"] != "validation"]
    tools = TOOLS
    prompt_request = request.model_dump()
    prompt_request["camera"]["scenarios"] = [
        s for s in prompt_request["camera"]["scenarios"] if s["clip"] in {c["id"] for c in dataset["clips"]}
    ]
    messages = [
        {"role": "system", "content": CAMERA_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "request": prompt_request,
                    "dataset": dataset,
                    "environment": {
                        k: v for k, v in environment().items() if k != "opencv_build"
                    },
                    "baseline": evidence(baseline),
                    "candidate_budget": request.budget,
                }
            ),
        },
    ]
    used = 0
    for turn in range(request.budget * 2 + 4):
        store.event(
            run_id,
            "model_requested",
            {
                "turn": turn + 1,
                "model": os.environ.get("NEBIUS_MODEL"),
                "candidates_remaining": request.budget - used,
            },
        )
        answer, usage = await provider(
            messages, tools if used < request.budget else tools[1:]
        )
        messages.append(answer)
        store.event(
            run_id, "model_response", {"usage": usage, "content": answer.get("content")}
        )
        calls = answer.get("tool_calls", [])
        if not calls:
            if answer.get("content"):
                return answer["content"]
            raise ProviderError("The model returned neither a tool call nor a summary.")
        finish_summary = None
        for call in calls:
            name = call["function"]["name"]
            try:
                arguments = json.loads(call["function"]["arguments"])
                if name == "finish":
                    finish_summary = FinishProposal.model_validate(arguments).summary
                    output = {"search_finished": True}
                elif (
                    name == "run_experiment"
                    and used < request.budget
                    and finish_summary is None
                ):
                    proposal = CameraProposal.model_validate(arguments)
                    config = CameraConfiguration.model_validate(proposal.model_dump(exclude={"rationale"}))
                    if config.mode != "local" and not (
                        request.camera.allow_image_requests and request.camera.max_image_requests
                    ):
                        raise ValueError("Remote review was not authorized.")
                    used += 1
                    store.event(
                        run_id,
                        "tool_call",
                        {"tool": name, "arguments": proposal.model_dump()},
                    )
                    output = evidence(
                        await measure(
                            run_id, request, config, "candidate", proposal.rationale
                        )
                    )
                else:
                    output = {
                        "error": "Tool unavailable or experiment budget exhausted. Finish using the observed results."
                    }
            except (ValueError, ValidationError) as error:
                output = {
                    "error": "Tool arguments violate the published schema.",
                    "type": type(error).__name__,
                }
                if isinstance(error, ValidationError):
                    output["fields"] = [
                        {"field": item["loc"], "message": item["msg"]}
                        for item in error.errors(include_input=False)
                    ]
                store.event(run_id, "tool_error", output)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(output),
                }
            )
        if finish_summary is not None:
            return finish_summary
    raise ProviderError(
        "The model-turn budget was reached without finishing. Completed evidence is preserved; start a new run after reviewing tool errors."
    )


async def execute(run_id: str):
    request = RunRequest.model_validate(store.get_run(run_id)["request"])
    store.update_run(run_id, status="running")
    try:
        baseline = await measure(
            run_id,
            request,
            request.camera.baseline,
            "baseline",
            "Measure the reference configuration before search.",
        )
        if baseline["status"] != "completed":
            raise RuntimeError("Baseline benchmark failed")
        if request.strategy == "agent":
            summary = await optimize(run_id, request, baseline)
        elif request.strategy == "random":
            generator = random.Random(request.seed)
            for _ in range(request.budget):
                config = CameraConfiguration(
                    width=generator.choice([320, 640, 960, 1280]),
                    sample_every=generator.choice([1, 2, 4]), threads=generator.choice([1, 2, 4]),
                    queue_size=generator.choice([1, 2, 4]),
                    mode=generator.choice(["local", "scheduled", "hybrid"] if request.camera.allow_image_requests and request.camera.max_image_requests else ["local"]),
                    review_interval_s=generator.choice([1, 2, 5]),
                )
                await measure(
                    run_id,
                    request,
                    config,
                    "candidate",
                    f"Random-search comparison, seed {request.seed}.",
                )
            summary = (
                "Seeded random search completed. This comparator does not use an agent."
            )
        else:
            summary = "Reference configuration measured without optimization."
        candidates = [
            e
            for e in store.get_run(run_id)["experiments"]
            if e.get("gate") and e["gate"]["passed"]
        ]
        store.update_run(run_id, summary=summary)
        if checked(request.camera, verify=False)["development_only"]:
            candidates = []
            store.update_run(run_id, summary=summary + " Development-only recordings: no held-out recommendation or apply.")
        if candidates:
            cost_available = all(e["metrics"].get("cost_per_camera_hour") is not None for e in candidates)
            objective = "cost_per_camera_hour" if cost_available else "cpu_seconds_per_camera_second"
            winner = min(candidates, key=lambda e: e["metrics"][objective])
            store.event(
                run_id,
                "search_frozen",
                {
                    "selected_experiment": winner["id"],
                    "reason": f"Lowest {objective} satisfying every tuning gate.",
                },
            )
            if winner["id"] != baseline["id"] and baseline["gate"]["passed"]:
                reference = await measure(
                    run_id,
                    request,
                    request.camera.baseline,
                    "reference_validation",
                    "Held-out reference check. Preserve a validated fallback if the candidate regresses.",
                )
                if reference.get("gate") and reference["gate"]["passed"]:
                    store.update_run(run_id, recommendation=reference["id"])
            validation = await measure(
                run_id,
                request,
                CameraConfiguration.model_validate(winner["config"]),
                "validation",
                f"Held-out evaluation of experiment {winner['id']}. Search is frozen.",
            )
            if validation.get("gate") and validation["gate"]["passed"]:
                store.update_run(run_id, recommendation=validation["id"])
        store.update_run(run_id, status="completed")
        store.event(
            run_id,
            "run_completed",
            {"recommendation": store.get_run(run_id)["recommendation"]},
        )
    except asyncio.CancelledError:
        store.update_run(
            run_id,
            status="cancelled",
            error="Run cancelled. Completed measurements were preserved.",
        )
        store.event(run_id, "run_cancelled", {})
        raise
    except Exception as error:  # noqa: BLE001 - job boundary must release the persisted run slot
        # Job boundary: preserve evidence and release the single-run slot after any failure.
        for experiment in store.get_run(run_id)["experiments"]:
            if experiment["status"] == "running":
                store.fail_experiment(
                    experiment["id"], "Run failed before this measurement completed."
                )
        message = (
            str(error)
            if isinstance(error, ProviderError)
            else f"Run failed ({type(error).__name__}). Completed evidence was preserved."
        )
        store.update_run(run_id, status="failed", error=message)
        store.event(run_id, "run_failed", {"error": message})
