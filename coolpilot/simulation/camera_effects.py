"""Development-only image edits, shared by fixture generation and interactive replay."""
import cv2
import numpy as np

VERSION = 1
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


def strength(kind, seconds):
    if kind == "reference" or not START <= seconds < END:
        return 0.0
    params = PARAMETERS[kind]
    return max(0.0, min(1.0, (seconds - START) / params.get("ramp_in_s", 1e-9), (END - seconds) / params.get("ramp_out_s", 1e-9)))


def fields(height, width):
    y, x = np.mgrid[:height, :width].astype(np.float32)
    x /= width
    y /= height
    p = PARAMETERS["glare"]
    glare = np.exp(-0.5 * (((x-p["centre_xy"][0])/p["sigma_xy"][0])**2 + ((y-p["centre_xy"][1])/p["sigma_xy"][1])**2))
    glare[glare < p["cutoff"]] = 0
    p = PARAMETERS["obstruction"]
    radius = ((x-p["centre_xy"][0])/p["radius_xy"][0])**2 + ((y-p["centre_xy"][1])/p["radius_xy"][1])**2
    noise = np.random.default_rng(SEED).uniform(0.75, 1.0, (12, 16)).astype(np.float32)
    texture = cv2.resize(noise, (width, height), interpolation=cv2.INTER_CUBIC)
    obstruction = np.maximum(0, 1-radius)**2 * np.clip(texture, 0.75, 1.0)
    return {"glare": glare[..., None], "obstruction": obstruction[..., None]}


def effect(image, kind, seconds, frozen, masks):
    amount = strength(kind, seconds)
    if amount == 0:
        return image
    p = PARAMETERS[kind]
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
