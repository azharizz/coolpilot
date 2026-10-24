"""Road-user detection on OpenCV 5's new DNN graph engine (CPU), used only to verify a suspicion.

Model: NanoDet-Plus-m-1.5x 416 from the OpenCV model zoo (huggingface.co/opencv/object_detection_nanodet,
Apache-2.0; licence copied next to the weights). Pre/post-processing adapted from the zoo's nanodet.py.
Outputs are paired by shape, not order: the new engine lists all class maps before all box maps.
"""
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .dataset import DATA

MODEL = Path(os.environ.get("COOLPILOT_DETECTOR", DATA / "models" / "object_detection_nanodet_2022nov.onnx"))
SIZE, REG_MAX = 416, 7
MEAN = np.array([103.53, 116.28, 123.675], dtype=np.float32)
STD = np.array([57.375, 57.12, 58.395], dtype=np.float32)
# COCO ids of things that move through a road scene and can cover part of the view.
_LOCK = threading.Lock()   # one Net is shared; setInput/forward from several replay threads would interleave
ROAD_USERS = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 6: "train", 7: "truck"}


def available() -> bool:
    return MODEL.is_file()


@lru_cache(maxsize=1)
def _net():
    try:
        net, engine = cv2.dnn.readNetFromONNX(str(MODEL), engine=cv2.dnn.ENGINE_NEW), "new"
    except (cv2.error, AttributeError):   # OpenCV 4.x has no engine choice
        net, engine = cv2.dnn.readNetFromONNX(str(MODEL)), "classic"
    return net, engine


def detect(image_bgr, threshold: float = 0.35) -> dict:
    """Road users as normalized [x1, y1, x2, y2] boxes, plus the engine and inference time."""
    net, engine = _net()
    h, w = image_bgr.shape[:2]
    scale = min(SIZE / h, SIZE / w)
    nh, nw = int(h * scale), int(w * scale)
    top, left = (SIZE - nh) // 2, (SIZE - nw) // 2
    rgb = cv2.cvtColor(cv2.resize(image_bgr, (nw, nh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    canvas = cv2.copyMakeBorder(rgb, top, SIZE - nh - top, left, SIZE - nw - left, cv2.BORDER_CONSTANT, value=0)
    blob = cv2.dnn.blobFromImage((canvas.astype(np.float32) - MEAN) / STD)
    with _LOCK:
        net.setInput(blob)
        start = time.perf_counter()
        outs = [o.reshape(o.shape[-2], o.shape[-1]).copy() for o in net.forward(net.getUnconnectedOutLayersNames())]
        elapsed_ms = (time.perf_counter() - start) * 1000
    classes = sorted((o for o in outs if o.shape[1] != 4 * (REG_MAX + 1)), key=len, reverse=True)
    boxes = sorted((o for o in outs if o.shape[1] == 4 * (REG_MAX + 1)), key=len, reverse=True)
    all_boxes, all_scores = [], []
    for cls, reg in zip(classes, boxes):
        side = int(round(len(cls) ** 0.5))
        stride = SIZE // side
        yy, xx = np.mgrid[:side, :side]
        cx, cy = (xx.ravel() * stride + 0.5 * (stride - 1)), (yy.ravel() * stride + 0.5 * (stride - 1))
        e = np.exp(reg.reshape(-1, REG_MAX + 1))
        dist = ((e / e.sum(axis=1, keepdims=True)) @ np.arange(REG_MAX + 1)).reshape(-1, 4) * stride
        all_boxes.append(np.clip(np.column_stack([cx - dist[:, 0], cy - dist[:, 1], cx + dist[:, 2], cy + dist[:, 3]]), 0, SIZE))
        all_scores.append(cls)
    xyxy, scores = np.concatenate(all_boxes), np.concatenate(all_scores)
    ids, conf = scores.argmax(axis=1), scores.max(axis=1)
    wh = xyxy.copy(); wh[:, 2:] -= wh[:, :2]
    found = []
    for i in np.array(cv2.dnn.NMSBoxes(wh.tolist(), conf.tolist(), threshold, 0.6)).reshape(-1):
        if int(ids[i]) in ROAD_USERS:
            x1, y1, x2, y2 = xyxy[i]
            found.append({"label": ROAD_USERS[int(ids[i])], "score": round(float(conf[i]), 3),
                          "box": [round(float(np.clip((x1 - left) / scale / w, 0, 1)), 3), round(float(np.clip((y1 - top) / scale / h, 0, 1)), 3),
                                  round(float(np.clip((x2 - left) / scale / w, 0, 1)), 3), round(float(np.clip((y2 - top) / scale / h, 0, 1)), 3)]})
    return {"objects": found, "engine": engine, "opencv": cv2.__version__, "inference_ms": round(elapsed_ms, 1)}


def coverage(objects: list[dict], tile_box: list[float]) -> float:
    """Fraction of a tile [x, y, w, h] (normalized) covered by the union of detected boxes, on a 20x20 grid."""
    x, y, tw, th = tile_box
    gx, gy = np.meshgrid(x + (np.arange(20) + 0.5) * tw / 20, y + (np.arange(20) + 0.5) * th / 20)
    covered = np.zeros_like(gx, dtype=bool)
    for o in objects:
        x1, y1, x2, y2 = o["box"]
        covered |= (gx >= x1) & (gx <= x2) & (gy >= y1) & (gy <= y2)
    return float(covered.mean())
