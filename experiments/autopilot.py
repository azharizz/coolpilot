"""Diagnostic autopilot: an LLM agent tunes the detector with OpenCV-measured diagnostic tools (section 6c).

    python -m experiments.autopilot --cache ~/cache_d640_r4.pkl --arm tools --budget 16 --out results/autopilot-tools.json
    python -m experiments.autopilot --cache ~/cache_d640_r4.pkl --arm random --budget 16 --seed 7 --out results/autopilot-random.json
    python -m experiments.autopilot --approve results/autopilot-tools.json      # a human applies the proposal

Data: the joint-tuning cache only (Oxford centre tuning clips + DRIVE-C dev scenes). Validation data is never loaded.
Arms, same evaluation budget: "tools" (evaluate, explain_failure, paired_compare, ablate, propose), "evaluate"
(evaluate and propose only) and "random" (seeded random settings, no model). A proposal is written as pending and
is used for validation only after --approve. Every tool call and result summary goes into the trace.
"""
import argparse
import asyncio
import collections
import getpass
import json
import pickle
import random
import sys
import time
from pathlib import Path

import numpy as np

from coolpilot.agent import ProviderError, provider
from coolpilot.camera_health import Monitor
from coolpilot.models import CameraThresholds
from experiments import joint_calibrate as jc
from experiments.calibrate import evaluate as oxford_evaluate

# Bounded search space: (low, high) or the allowed values. Gates, data and splits are not in it.
SPACE = {"adaptive_k": (0, 8), "adaptive_floor_dark": (0.05, 0.6), "adaptive_floor_blur": (0.1, 1.5), "adaptive_window_s": (3, 30),
         "dark_ratio": (0.4, 0.85), "blur_ratio": (0.2, 0.6), "obstruction_s": (0.5, 2.0), "obstruction_ratio": (0.25, 0.5),
         "glare_rise": (0.15, 0.4), "glare_tiles": [1, 2, 3, 4], "hysteresis": (0.2, 1.0)}
MEANING = {"adaptive_k": "0 = fixed ratios; >0 = self-calibrating: a brightness/detail drop must exceed k x this camera's own learned swing",
           "adaptive_floor_dark": "with adaptive_k > 0: minimum log brightness drop that can alarm (0.2 ~ 18% darker)",
           "adaptive_floor_blur": "with adaptive_k > 0: minimum log detail drop that can alarm (0.4 ~ 33% less detail)",
           "adaptive_window_s": "seconds over which the swing is learned while healthy",
           "dark_ratio": "fixed rule (adaptive_k = 0): underexposure when brightness < ratio x normal",
           "blur_ratio": "fixed rule (adaptive_k = 0): blur when median tile detail < ratio x normal",
           "obstruction_s": "seconds the same tiles must stay low before obstruction",
           "obstruction_ratio": "a tile is 'low' below this ratio of its normal detail",
           "glare_rise": "rise in a tile's clipped fraction that counts as glare", "glare_tiles": "tiles that must rise for glare",
           "hysteresis": "how far back inside normal an active alarm must come before it clears (smaller = stickier)"}
IGNORE = {"centre_obstruction"}   # the Oxford sky coincidence, excluded from the guard since section 6b
SYSTEM = """You tune a camera-health detector (OpenCV 5 tile statistics) for ADAS cameras. Data: Oxford tuning clips and
DRIVE-C dev scenes (daytime). Goal: most DRIVE-C fault clips caught at onset, zero false alarms, and no failed Oxford
check. Settings must stay inside the published bounds; anything you do not set keeps its current value.
Diagnose before changing: evaluate shows which clips fail; explain_failure shows, frame by frame around the fault
onset, which rule fired or was blocked and the measured signals; paired_compare shows what each fault type does to
the measurements against the same clean frames; ablate measures one setting at a time. Each evaluated setting costs
one unit of the budget. Prefer few, general changes backed by a measured mechanism: five dev scenes are easy to
overfit. Changes that only fit one scene will fail validation. Finish by calling propose with the settings and the
evidence; a human approves before anything is applied. Do not claim safety, physical causes or results you did not
measure."""


def bounded(settings: dict) -> dict:
    out = {}
    for name, value in settings.items():
        if name not in SPACE:
            raise ValueError(f"{name} is not tunable here")
        rule = SPACE[name]
        if isinstance(rule, list) and value not in rule or isinstance(rule, tuple) and not rule[0] <= float(value) <= rule[1]:
            raise ValueError(f"{name}={value} is outside {rule}")
        out[name] = value
    return out


class Session:
    def __init__(self, budget: int):
        self.budget, self.used, self.base = budget, 0, {}
        self.history = []   # (settings, score) for every evaluated setting

    def thresholds(self, settings):
        return CameraThresholds(**{**self.base, **bounded(settings)})

    def score(self, settings) -> dict:
        if self.used >= self.budget:
            raise ValueError("Evaluation budget exhausted. Call propose.")
        self.used += 1
        t = self.thresholds(settings)
        oxford, drivec = oxford_evaluate(jc.CACHE["oxford"], t), jc.drivec_evaluate(t)
        failed_oxford = [f"{r['clip']}:{c['type']}" for r in oxford["clips"] if r["clip"] not in IGNORE for c in r["checks"] if not c["passed"]]
        per_class, per_scene, failing = collections.Counter(), collections.Counter(), []
        for c in drivec["clips"]:
            if c.get("passed"):
                per_class[c["clip"].split("_", 1)[1].rsplit("_", 1)[0]] += 1
                per_scene[c["clip"][:3]] += 1
            elif "expected" in c:
                failing.append(c["clip"])
        result = {"settings": settings, "oxford_failed_checks": failed_oxford, "oxford_false_alarms": oxford["false_alarms"],
                  "drivec_dev_passed": drivec["passed"], "of": drivec["passed"] + drivec["failed"],
                  "summary": f"{drivec['passed']} of {drivec['passed'] + drivec['failed']} DRIVE-C dev fault clips caught",
                  "drivec_false_alarms": drivec["false_alarms"], "passed_by_class_of_25": dict(per_class),
                  "passed_by_scene_of_30": dict(per_scene), "failing_clips_sample": failing[:24], "budget_left": self.budget - self.used}
        self.history.append((settings, result))
        return result


def rank(result):
    return (len(result["oxford_failed_checks"]), -result["drivec_dev_passed"], result["drivec_false_alarms"] + result["oxford_false_alarms"])


def explain_failure(session, clip, settings):
    entry = next((e for e in jc.CACHE["drivec"] if e[0] == clip), None)
    if entry is None:
        raise ValueError("Unknown DRIVE-C dev clip (use a name from failing_clips_sample)")
    name, frames, join, want = entry
    m, rows = Monitor(session.thresholds(settings)), []
    for i, f in enumerate(frames):
        t = i / 30
        conditions, _ = m.appearance(f, t)
        m.update(conditions, t, {})
        if (join or 0) - 0.5 <= t <= (join or 0) + 2.0 and i % 6 == 0:
            ratio = np.array([r["detail"] for r in f["regions"]]) / np.maximum(m.recent_detail, 1e-6)
            rows.append({"t_from_onset": round(t - (join or 0), 2), "conditions": sorted(conditions), "active": sorted(m.active),
                         "log_brightness_ratio": round(m.signals["dark"], 3) if m.signals else None,
                         "log_detail_ratio": round(m.signals["blur"], 3) if m.signals else None,
                         "learned_swing": {k: round(v, 3) for k, v in m.spread.items()},
                         "lowest_tile_detail_ratios": np.round(np.sort(ratio)[:4], 2).tolist()})
    return {"clip": name, "expected": want, "onset_s": join, "alarms": [(e["type"], round(e["start_s"] - (join or 0), 2)) for e in m.episodes],
            "pass_rule": "an alarm of the expected class within 2 s after onset and none before it", "timeline": rows}


def paired_compare(fault):
    clean = {e[0][:3]: e[1] for e in jc.CACHE["drivec"] if e[3] is None}
    by_severity = collections.defaultdict(list)
    for name, frames, join, want in jc.CACHE["drivec"]:
        if want is None or f"_{fault}_" not in name:
            continue
        base = clean[name[:3]]
        for a, b in zip(base[::8], frames[len(base)::8]):
            da, db = np.array([r["detail"] for r in a["regions"]]), np.array([r["detail"] for r in b["regions"]])
            d = db / np.maximum(da, 1e-6)
            by_severity[name.rsplit("_", 1)[1]].append((np.median(d), np.sort(d)[3], np.mean([r["mean"] for r in b["regions"]]) / max(np.mean([r["mean"] for r in a["regions"]]), 1e-6)))
    if not by_severity:
        raise ValueError("fault must be one of defocus_blur, motion_blur, underexposure, low_light, glare_flare, lens_occlusion")
    keys = ("median_tile_detail", "fourth_lowest_tile_detail", "brightness")
    return {"fault": fault, "note": "corrupted / clean at the same frame, medians over DRIVE-C dev; 1.0 = unchanged",
            "by_severity": {s: dict(zip(keys, np.round(np.median(np.array(v), axis=0), 3).tolist())) for s, v in sorted(by_severity.items())}}


def tools(arm):
    def spec(name, description, properties, required):
        return {"type": "function", "function": {"name": name, "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}}
    settings = {"type": "object", "description": "setting name -> value, within: " + json.dumps(SPACE) + ". Meaning: " + json.dumps(MEANING)}
    out = [spec("evaluate", "Score settings on the tuning data (costs 1 budget unit).", {"settings": settings}, ["settings"]),
           spec("propose", "Finish: propose settings for human approval, with the evidence.", {"settings": settings, "rationale": {"type": "string"}}, ["settings", "rationale"])]
    if arm == "tools":
        out += [spec("explain_failure", "Frame-by-frame rule trace around the onset of one DRIVE-C dev clip (free).",
                     {"clip": {"type": "string"}, "settings": settings}, ["clip", "settings"]),
                spec("paired_compare", "What one DRIVE-C fault type does to tile detail and brightness, same frames as clean (free).",
                     {"fault": {"type": "string"}}, ["fault"]),
                spec("ablate", "Score each value of one setting, all else fixed (costs 1 unit per value).",
                     {"settings": settings, "name": {"type": "string"}, "values": {"type": "array", "items": {}}}, ["settings", "name", "values"])]
    return out


def call(session, name, args, offered):
    if name not in offered:
        raise ValueError(f"tool {name} is not available in this arm")
    if name == "evaluate":
        return session.score(args["settings"])
    if name == "explain_failure":
        return explain_failure(session, args["clip"], args.get("settings", {}))
    if name == "paired_compare":
        return paired_compare(args["fault"])
    if name == "ablate":
        rows = []
        for value in args["values"][:5]:
            r = session.score({**args["settings"], args["name"]: value})
            rows.append({"value": value, **{k: r[k] for k in ("oxford_failed_checks", "drivec_dev_passed", "drivec_false_alarms", "passed_by_class_of_25")}})
        return {"setting": args["name"], "results": rows, "budget_left": session.budget - session.used}
    raise ValueError(f"unknown tool {name}")


def run_agent(session, arm, trace):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps({"current_defaults": CameraThresholds().model_dump(), "bounds": SPACE, "meaning": MEANING,
                                                        "budget": session.budget, "baseline": session.score({})})}]
    trace.append({"step": "baseline", "result": session.history[-1][1]})
    for turn in range(40):
        try:
            answer, usage = asyncio.run(provider(messages, tools(arm), temperature=0))
        except ProviderError as error:
            trace.append({"step": "provider_error", "error": str(error)})
            return None
        messages.append(answer)
        calls = answer.get("tool_calls") or []
        if not calls:
            trace.append({"step": "no_tool_call", "content": answer.get("content")})
            messages.append({"role": "user", "content": "Call a tool, or propose to finish."})
            continue
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                if isinstance(args.get("settings"), str):
                    args["settings"] = json.loads(args["settings"])
                if name == "propose":
                    proposal = {"settings": bounded(args["settings"]), "rationale": str(args.get("rationale", ""))[:2000]}
                    trace.append({"step": turn, "tool": name, "args": proposal})
                    return proposal
                result = call(session, name, args, {t["function"]["name"] for t in tools(arm)})
            except (ValueError, KeyError, TypeError) as error:
                result = {"error": str(error)}
            trace.append({"step": turn, "tool": name, "args": args, "result": result, "content": answer.get("content")})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, default=float)})
    return None


def run_random(session, seed, trace):
    generator = random.Random(seed)
    session.score({})
    trace.append({"step": "baseline", "result": session.history[-1][1]})
    while session.used < session.budget:
        settings = {k: generator.choice(v) if isinstance(v, list) else round(generator.uniform(*v), 2)
                    for k, v in SPACE.items() if generator.random() < 0.5}
        trace.append({"step": session.used, "tool": "evaluate", "args": settings, "result": session.score(settings)})
    best = min(session.history, key=lambda h: rank(h[1]))
    return {"settings": best[0], "rationale": f"Best of {session.used} seeded random settings by the shared ranking."}


def approve(path: Path):
    report = json.loads(path.read_text())
    if not report.get("proposal"):
        sys.exit("No proposal in this report.")
    print(json.dumps(report["proposal"], indent=1))
    report["approval"] = {"approved": True, "by": getpass.getuser(), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    path.write_text(json.dumps(report, indent=1, default=float) + "\n")
    Path(str(path).replace(".json", ".approved-thresholds.json")).write_text(json.dumps({"thresholds": report["proposal"]["settings"]}, indent=1) + "\n")
    print("approved; thresholds written for validation")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--arm", choices=["tools", "evaluate", "random"], default="tools")
    ap.add_argument("--budget", type=int, default=16)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--approve", type=Path, help="mark a report's proposal as human-approved")
    args = ap.parse_args()
    if args.approve:
        return approve(args.approve)
    jc.CACHE.update(pickle.loads(args.cache.read_bytes()))
    session, trace, started = Session(args.budget), [], time.perf_counter()
    proposal = run_random(session, args.seed, trace) if args.arm == "random" else run_agent(session, args.arm, trace)
    final = None
    if proposal:   # score the proposal outside the budget so every arm is compared the same way
        session.budget += 1
        final = session.score(proposal["settings"])
    report = {"arm": args.arm, "budget": args.budget, "evaluations_used": session.used - (1 if final else 0), "wall_s": round(time.perf_counter() - started, 1),
              "baseline": session.history[0][1], "proposal": proposal, "proposal_score": final,
              "status": "pending_human_approval" if proposal else "no_proposal", "trace": trace}
    print(json.dumps({k: report[k] for k in ("arm", "evaluations_used", "wall_s", "status")} |
                     {"baseline": {k: report["baseline"][k] for k in ("oxford_failed_checks", "drivec_dev_passed", "drivec_false_alarms")},
                      "proposal": proposal and proposal["settings"],
                      "score": final and {k: final[k] for k in ("oxford_failed_checks", "drivec_dev_passed", "drivec_false_alarms", "passed_by_class_of_25")}}, indent=1, default=float))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, default=float) + "\n")


if __name__ == "__main__":
    main()
