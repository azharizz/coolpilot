"""Development-only image edits, shared by fixture generation and interactive replay.

Without a recipe every function reproduces the original fixed fixture exactly (4-10 s, fixed strength
and position). A recipe randomizes one clip's fault: {"start_s", "end_s", "scale", "centre_xy"}.
"""
import cv2
import numpy as np

VERSION = 2
SEED = 42
START, END = 4.0, 10.0
KINDS = ("reference", "blur", "underexposure", "glare", "obstruction", "blackout", "freeze")
PARAMETERS = {
    "reference": {},
    "blur": {"sigma_px": 6.5, "ramp_in_s": 0.8, "ramp_out_s": 0.8},
    "underexposure": {"exposure_ev": -4.0, "gamma": 2.2, "ramp_in_s": 0.35, "ramp_out_s": 1.8},
    "glare": {"centre_xy": [0.72, 0.27], "sigma_xy": [0.17, 0.14], "cutoff": 0.02, "peak_addition": 1.4, "ramp_in_s": 0.45, "ramp_out_s": 1.0},
    "obstruction": {"centre_xy": [0.52, 0.52], "radius_xy": [0.21, 0.25], "max_opacity": 0.9, "local_blur_sigma_px": 11, "tint_bgr": [58, 70, 82], "ramp_in_s": 0.25, "ramp_out_s": 0.5},
    "blackout": {},
    "freeze": {},
}
# which parameter a recipe "scale" multiplies, per fault
SCALED = {"blur": "sigma_px", "underexposure": "exposure_ev", "glare": "peak_addition", "obstruction": "max_opacity"}


def window(recipe=None):
    return (recipe["start_s"], recipe["end_s"]) if recipe else (START, END)


def params(kind, recipe=None):
    p = dict(PARAMETERS[kind])
    if recipe:
        if kind in SCALED and "scale" in recipe:
            p[SCALED[kind]] = p[SCALED[kind]] * recipe["scale"]
            if kind == "obstruction":
                p["max_opacity"] = min(0.97, p["max_opacity"])
        if "centre_xy" in recipe and "centre_xy" in p:
            p["centre_xy"] = list(recipe["centre_xy"])
    return p


def strength(kind, seconds, recipe=None):
    start, end = window(recipe)
    if kind == "reference" or not start <= seconds < end:
        return 0.0
    p = params(kind, recipe)
    return max(0.0, min(1.0, (seconds - start) / p.get("ramp_in_s", 1e-9), (end - seconds) / p.get("ramp_out_s", 1e-9)))


def fields(height, width, recipe=None, kind=None):
    y, x = np.mgrid[:height, :width].astype(np.float32)
    x /= width
    y /= height
    p = params("glare", recipe if kind == "glare" else None)
    glare = np.exp(-0.5 * (((x-p["centre_xy"][0])/p["sigma_xy"][0])**2 + ((y-p["centre_xy"][1])/p["sigma_xy"][1])**2))
    glare[glare < p["cutoff"]] = 0
    p = params("obstruction", recipe if kind == "obstruction" else None)
    radius = ((x-p["centre_xy"][0])/p["radius_xy"][0])**2 + ((y-p["centre_xy"][1])/p["radius_xy"][1])**2
    noise = np.random.default_rng(SEED).uniform(0.75, 1.0, (12, 16)).astype(np.float32)
    texture = cv2.resize(noise, (width, height), interpolation=cv2.INTER_CUBIC)
    obstruction = np.maximum(0, 1-radius)**2 * np.clip(texture, 0.75, 1.0)
    return {"glare": glare[..., None], "obstruction": obstruction[..., None]}


def random_recipe(kind, duration_s, rng):
    """One randomized fault for a clip of duration_s: onset, length 2-6 s, strength x0.7-1.3, position.

    Clips shorter than 10 s (e.g. DRIVE-C's 4.3 s) get a 1.0-2.0 s fault after a 1.3 s warm-up and at
    least 0.8 s of recovery. Longer clips keep the original draw, so existing seeds reproduce exactly.
    """
    if duration_s < 10:
        if duration_s < 4.0:
            raise ValueError("Clips shorter than 4 s leave no room for warm-up, fault and recovery.")
        length = float(rng.uniform(1.0, min(2.0, duration_s - 2.6)))
        start = float(rng.uniform(1.3, duration_s - 0.8 - length))
    else:
        length = float(rng.uniform(2.0, min(6.0, duration_s - 4.0)))
        start = float(rng.uniform(1.5, duration_s - 1.5 - length))
    recipe = {"start_s": round(start, 3), "end_s": round(start + length, 3), "scale": round(float(rng.uniform(0.7, 1.3)), 3)}
    if kind in ("glare", "obstruction"):
        cx, cy = PARAMETERS[kind]["centre_xy"]
        recipe["centre_xy"] = [round(float(np.clip(cx + rng.uniform(-0.15, 0.15), 0.2, 0.8)), 3),
                               round(float(np.clip(cy + rng.uniform(-0.12, 0.12), 0.2, 0.8)), 3)]
    return recipe


def effect(image, kind, seconds, frozen, masks, recipe=None):
    amount = strength(kind, seconds, recipe)
    if amount == 0:
        return image
    p = params(kind, recipe)
    if kind == "freeze":
        return frozen
    if kind == "blackout":
        return np.zeros_like(image)
    if kind == "blur":
        return cv2.GaussianBlur(image, (0, 0), p["sigma_px"] * amount)
    value = image.astype(np.float32)
    if kind == "underexposure":
        value = np.power(np.power(value / 255, p["gamma"]) * 2**(p["exposure_ev"] * amount), 1/p["gamma"]) * 255
    elif kind == "glare":
        value += 255 * p["peak_addition"] * amount * masks[kind]
    elif kind == "obstruction":
        alpha = amount * p["max_opacity"] * masks[kind]
        blurred = cv2.GaussianBlur(image, (0, 0), p["local_blur_sigma_px"]).astype(np.float32)
        obscured = blurred * 0.25 + np.array(p["tint_bgr"], dtype=np.float32) * 0.75
        value = value * (1-alpha) + obscured * alpha
    else:
        raise ValueError(kind)
    return np.rint(np.clip(value, 0, 255)).astype(np.uint8)
