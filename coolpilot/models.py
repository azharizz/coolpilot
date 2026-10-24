"""The public experiment contract and its quality gate."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


FAULTS = ("blur", "underexposure", "glare", "obstruction", "blackout", "freeze", "interruption", "backlog")


class DetectorTuning(Contract):
    """Bounded detector calibration an experiment may try on TUNING clips. None keeps the run's value.

    Gates (CameraGoals) never change; the winning tuning is frozen before held-out validation.
    """
    glare_rise: Literal[0.2, 0.25, 0.3, 0.4] | None = None
    dark_ratio: Literal[0.45, 0.55, 0.65, 0.75] | None = None
    blur_ratio: Literal[0.25, 0.35, 0.5] | None = None
    obstruction_ratio: Literal[0.35, 0.45, 0.55, 0.65] | None = None
    obstruction_s: Literal[0.5, 0.8, 1.2] | None = None
    hysteresis: Literal[0.2, 0.3, 0.5, 0.7, 1.0] | None = None
    obstruction_hysteresis: Literal[0.5, 0.8, 1.0] | None = None
    persistence_s: Literal[0.2, 0.3, 0.5] | None = None
    recovery_s: Literal[0.2, 0.3, 0.5] | None = None


class CameraConfiguration(Contract):
    # The agent and random comparator use exactly this finite search space.
    width: Literal[320, 640, 960, 1280] = 640
    sample_every: Literal[1, 2, 4] = 1
    threads: Literal[1, 2, 4] = 1
    queue_size: Literal[1, 2, 4] = 2
    mode: Literal["local", "scheduled", "hybrid"] = "local"
    review_interval_s: Literal[1, 2, 5] = 2
    detector: DetectorTuning | None = None


class FaultLimit(Contract):
    min_recall: float = Field(ge=0, le=1)
    max_detection_s: float = Field(gt=0, le=60)
    max_recovery_s: float = Field(gt=0, le=60)
    min_events: int = Field(ge=1, le=10000)


class CameraGoals(Contract):
    faults: dict[str, FaultLimit]
    max_false_alarms_per_hour: float = Field(ge=0)
    min_normal_seconds: float = Field(gt=0)
    max_age_s: float = Field(gt=0, le=60)
    max_unknown_fraction: float = Field(ge=0, le=1)
    max_api_failure_fraction: float = Field(ge=0, le=1)
    max_cost_per_camera_hour: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def known_faults(self):
        if not self.faults or not self.faults.keys() <= set(FAULTS):
            raise ValueError("Declare acceptance limits for known fault classes.")
        return self


class CameraThresholds(Contract):
    """Development calibration, frozen for a run; not validated safety limits."""
    blur_variance: float = Field(default=60, gt=0)
    dark_mean: float = Field(default=35, ge=0, le=255)
    black_fraction: float = Field(default=0.98, gt=0, le=1)
    glare_fraction: float = Field(default=0.35, gt=0, le=1)   # retired absolute rule; kept so old runs still load
    obstruction_ratio: float = Field(default=0.35, gt=0, lt=1)
    # Relative rules: each camera against its own references. Defaults come from
    # experiments/calibrate.py on the centre-camera tuning clips only (0/6 failed checks, 1 false alarm).
    warmup_s: float = Field(default=1.0, ge=0, le=30)
    reference_window_s: float = Field(default=3.0, gt=0, le=600)
    glare_rise: float = Field(default=0.25, gt=0, le=1)
    glare_tiles: int = Field(default=2, ge=1, le=16)
    dark_ratio: float = Field(default=0.55, gt=0, lt=1)
    blur_ratio: float = Field(default=0.35, gt=0, lt=1)
    scene_keep_ratio: float = Field(default=0.85, gt=0, le=2)
    obstruction_s: float = Field(default=0.5, ge=0, le=10)
    hysteresis: float = Field(default=0.3, gt=0, le=1)   # 1 = none; smaller = stickier active alarms
    obstruction_hysteresis: float = Field(default=0.8, gt=0, le=1)   # local loss: a light touch, or it never clears
    freeze_difference: float = Field(default=0.3, ge=0, le=255)
    # E-folding time: approximately the old 0.999 retention at 14 observations/s.
    reference_decay_s: float = Field(default=71.4, gt=0, le=3600)
    persistence_s: float = Field(default=0.3, gt=0, le=10)
    recovery_s: float = Field(default=0.5, gt=0, le=10)
    freeze_s: float = Field(default=1, gt=0, le=30)
    feed_timeout_s: float = Field(default=1, gt=0, le=30)
    backlog_s: float = Field(default=0.5, gt=0, le=30)


class ReplayInterval(Contract):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_s <= self.start_s:
            raise ValueError("Interval end must follow start.")
        return self


class ReplayScenario(Contract):
    clip: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    interruptions: list[ReplayInterval] = Field(default_factory=list, max_length=20)
    processing_delay_ms: float = Field(default=0, ge=0, le=5000)
    processing_delay_interval: ReplayInterval | None = None

    @model_validator(mode="after")
    def delay_window(self):
        if bool(self.processing_delay_ms) != bool(self.processing_delay_interval):
            raise ValueError("Processing load injection needs both a delay and an interval.")
        return self


class CameraSettings(Contract):
    dataset: str = Field(default="oxford-development", pattern=r"^[a-zA-Z0-9_-]+$", max_length=100)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseline: CameraConfiguration = Field(default_factory=CameraConfiguration)
    goals: CameraGoals
    thresholds: CameraThresholds = Field(default_factory=CameraThresholds)
    scenarios: list[ReplayScenario] = Field(default_factory=list, max_length=32)
    concurrent_streams: int = Field(default=1, ge=1, le=8)
    allow_image_requests: bool = False
    max_image_requests: int = Field(default=0, ge=0, le=100)
    api_timeout_s: float = Field(default=5, gt=0, le=30)
    cool_hourly_price: float | None = Field(default=None, ge=0)
    # Second-stage check of obstruction suspicions (coolpilot.verify). "agent" needs the Nebius keys,
    # which benchmark subprocesses never receive, so measured runs use "rule".
    verifier: Literal["off", "rule", "agent"] = "rule"


class CameraProposal(CameraConfiguration):
    rationale: str = Field(min_length=1, max_length=2000)


class RunRequest(Contract):
    workload: Literal["camera_health"] = "camera_health"
    camera: CameraSettings
    name: str = Field(default="Camera-health validation", min_length=1, max_length=100)
    strategy: Literal["agent", "random", "baseline"] = "baseline"
    budget: int = Field(default=6, ge=1, le=30)
    repetitions: int = Field(default=3, ge=1, le=10)
    hourly_price: float | None = Field(default=None, gt=0, le=10000)
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="after")
    def workload_contract(self):
        if self.camera.baseline.mode != "local" and not (
            self.camera.allow_image_requests and self.camera.max_image_requests
        ):
            raise ValueError("Image review requires explicit permission and a request budget.")
        return self

class FinishProposal(Contract):
    summary: str = Field(min_length=1, max_length=4000)


