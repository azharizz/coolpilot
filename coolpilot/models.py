"""The public experiment contract and its quality gate."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


FAULTS = ("blur", "underexposure", "glare", "obstruction", "blackout", "freeze", "interruption", "backlog")


class CameraConfiguration(Contract):
    # The agent and random comparator use exactly this finite search space.
    width: Literal[320, 640, 960, 1280] = 640
    sample_every: Literal[1, 2, 4] = 1
    threads: Literal[1, 2, 4] = 1
    queue_size: Literal[1, 2, 4] = 2
    mode: Literal["local", "scheduled", "hybrid"] = "local"
    review_interval_s: Literal[1, 2, 5] = 2


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
    glare_fraction: float = Field(default=0.35, gt=0, le=1)
    obstruction_ratio: float = Field(default=0.25, gt=0, lt=1)
    freeze_difference: float = Field(default=0.3, ge=0, le=255)
    # E-folding time: approximately the old 0.999 retention at 14 observations/s.
    reference_decay_s: float = Field(default=71.4, gt=0, le=3600)
    persistence_s: float = Field(default=0.3, gt=0, le=10)
    recovery_s: float = Field(default=0.3, gt=0, le=10)
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


