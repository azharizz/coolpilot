"""Runtime verification agent: the model investigates an obstruction suspicion with OpenCV tools, then acts.

Perception (monitor) -> decision (this agent, calling coolpilot.verify tools) -> action:
confirm (raise the alarm), dismiss (with a measured reason) or escalate (a human decides).
Fail-safe: any provider or tool error, a missing decision or an exhausted turn budget confirms, so a
broken verifier can never silence an alarm. The model sees tool measurements only, never labels or images.
"""
import json
from typing import Literal

from pydantic import Field

from . import verify
from .agent import ProviderError, provider, tool
from .models import Contract

SYSTEM = """You verify one camera-health suspicion: some image tiles lost detail while the rest of the view kept it.
That can be a lens obstruction, or the scene (open sky, a featureless surface, a vehicle passing close).
Call the measurement tools you need, then call decide exactly once.
- dismiss only when a tool measured a scene cause for EVERY suspected tile; cite the numbers.
- confirm when no measured scene cause explains the loss.
- escalate when the measurements conflict or are missing, so a human reviews it.
Never guess from tile positions alone. A dismissed real fault is a missed alarm, so prefer escalate over a weak dismiss.
Reading inspect_texture: relative_texture is the tile's NORMAL detail (history), sky_now is what it shows NOW.
unsuitable_tiles lists tiles with a measured scene cause (open sky now, or never detailed): a tile that was detailed
and now shows open sky lost its detail because the scene changed (for example a tree left the view), not the lens.
Reading detect_road_users: covered_fraction >= limit means road users explain the loss. measure_motion is context only."""


class NoArguments(Contract):
    pass


class Decision(Contract):
    verdict: Literal["confirm", "dismiss", "escalate"]
    reason: str = Field(min_length=1, max_length=600)


TOOLS = [
    tool("inspect_texture", "Normal detail of each suspected tile vs this camera's median, and whether it shows open sky now.", NoArguments),
    tool("detect_road_users", "Run the OpenCV 5 DNN detector (NanoDet) on the latest frame; coverage of the suspected tiles by road users.", NoArguments),
    tool("measure_motion", "Optical flow over the last second in the suspected tiles vs the other tiles.", NoArguments),
    tool("decide", "Final action for this suspicion.", Decision),
]


async def investigate(frames, boxes, suspected, reference, max_turns: int = 6) -> dict:
    tools = {"inspect_texture": lambda: verify.texture(frames[-1], boxes, reference, suspected),
             "detect_road_users": lambda: verify.road_users(frames[-1], boxes, suspected),
             "measure_motion": lambda: verify.motion(frames, boxes, suspected)}
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps({"suspected_tiles": suspected, "tile_boxes_xywh": {i: boxes[i] for i in suspected},
                                                        "grid": "4x4 tiles, row-major, normalized image coordinates"})}]
    calls, evidence = [], {}
    try:
        for _ in range(max_turns):
            answer, _usage = await provider(messages, TOOLS, temperature=0)
            messages.append(answer)
            for call in answer.get("tool_calls") or []:
                name = call["function"]["name"]
                if name == "decide" and not evidence:
                    # Guardrail: a verdict must rest on at least one measurement, not on the prompt.
                    calls.append("decide (refused: no measurement yet)")
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": json.dumps({"error": "Refused: call at least one measurement tool before decide."})})
                    continue
                if name == "decide":
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                    if isinstance(arguments.get("reason"), str):
                        arguments["reason"] = arguments["reason"][:600]   # a verbose verdict is still a verdict
                    decision = Decision.model_validate(arguments)
                    calls.append(name)
                    return {"verdict": decision.verdict, "reason": decision.reason, "tool_calls": calls, "evidence": evidence}
                result = tools[name]() if name in tools else {"error": f"Unknown tool {name}."}
                evidence[name] = result
                calls.append(name)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
            if not answer.get("tool_calls"):
                messages.append({"role": "user", "content": "Call decide now."})
    except (ProviderError, ValueError, KeyError) as error:
        return {"verdict": "confirm", "reason": f"Verifier unavailable ({type(error).__name__}: {str(error)[:160]}); alarm kept.", "tool_calls": calls,
                "evidence": evidence, "error": True}
    return {"verdict": "confirm", "reason": "No decision within the turn budget; alarm kept.", "tool_calls": calls, "evidence": evidence, "error": True}
