from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .poses import JOINTS


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    clear_mode: Literal["latched", "simultaneous"] = "latched"
    score_threshold: float = Field(default=65, ge=20, le=100)
    confidence_threshold: float = Field(default=.5, ge=.1, le=.95)
    hold_seconds: float = Field(default=1, ge=0, le=10)
    hidden_policy: Literal["require", "ignore"] = "require"
    min_visible: int = Field(default=8, ge=4, le=12)
    joints: list[int] = Field(default_factory=lambda: JOINTS.copy(), min_length=4, max_length=12)
    azimuth_min: float = Field(default=-180, ge=-180, le=180)
    azimuth_max: float = Field(default=180, ge=-180, le=180)
    elevation_min: float = Field(default=-30, ge=-30, le=30)
    elevation_max: float = Field(default=30, ge=-30, le=30)
    min_limb_ratio: float = Field(default=.07, ge=0, le=.3)
    min_side_separation: float = Field(default=.04, ge=0, le=.3)
    min_keypoint_separation: float = Field(default=.08, ge=0, le=.3)
    round_seconds: int = Field(default=180, ge=15, le=1800)
    rounds: int = Field(default=5, ge=1, le=100)

    @model_validator(mode="after")
    def coherent(self):
        if self.azimuth_min > self.azimuth_max or self.elevation_min > self.elevation_max:
            raise ValueError("角度の最小値は最大値以下にしてください。")
        if len(set(self.joints)) != len(self.joints) or not set(self.joints) <= set(JOINTS):
            raise ValueError("判定関節の指定が不正です。")
        if self.min_visible > len(self.joints):
            raise ValueError("必要な関節数は選択した関節数以下にしてください。")
        return self


class KeypointFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: Literal["pose"]
    round_id: str
    keypoints: list[tuple[float, float, float]] = Field(min_length=33, max_length=33)

    @model_validator(mode="after")
    def finite_frame(self):
        if any(not (-2 <= x <= 3 and -2 <= y <= 3 and 0 <= c <= 1) for x, y, c in self.keypoints):
            raise ValueError("Invalid keypoint range")
        return self
