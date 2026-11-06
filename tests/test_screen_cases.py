"""JSON 标注的真实截图案例：新增截图无需复制测试函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import cv2
import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lorwright.config import LayoutConfig
from lorwright.models import UIState
from lorwright.perceive.normalize import Normalizer
from lorwright.perceive.state import StateParser
from lorwright.perceive.ui_state import UIStateDetector

FIXTURES = Path(__file__).parent / "fixtures"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(StrictModel):
    device: str = Field(min_length=1)
    game_version: str = Field(min_length=1)
    capture_date: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    sequence: str = Field(min_length=1)


class Expected(StrictModel):
    ui_state: UIState | None = None
    mana: int | None = Field(default=None, ge=0)
    nexus_hp: int | None = Field(default=None, ge=0)
    enemy_nexus_hp: int | None = Field(default=None, ge=0)
    hand_costs: list[int] | None = None
    hand_expanded: bool | None = None
    my_unit_count: int | None = Field(default=None, ge=0)
    enemy_unit_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_assertion(self):
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("expected 至少标注一个非 null 字段；未核实的字段请省略")
        return self


class Profile(StrictModel):
    capture_size: tuple[int, int]
    design_size: tuple[int, int]
    layout: dict[str, tuple[int, int, int, int]]

    @model_validator(mode="after")
    def validate_coordinates(self):
        if any(n <= 0 for n in (*self.capture_size, *self.design_size)):
            raise ValueError("截图和设计尺寸必须为正")
        unknown = self.layout.keys() - LayoutConfig.model_fields.keys()
        if unknown:
            raise ValueError(f"未知 layout 字段：{sorted(unknown)}")
        for name, (x, y, w, h) in self.layout.items():
            if min(x, y) < 0 or min(w, h) <= 0:
                raise ValueError(f"无效矩形：{name}")
            if x + w > self.design_size[0] or y + h > self.design_size[1]:
                raise ValueError(f"矩形超出设计尺寸：{name}")
        return self


class Case(StrictModel):
    id: str = Field(min_length=1)
    image: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    expected: Expected


class CaseFile(StrictModel):
    schema_version: Literal[1]
    source: Source
    profiles: dict[str, Profile]
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("案例 id 必须唯一")
        screens = (FIXTURES / "screens").resolve()
        for case in self.cases:
            if case.profile not in self.profiles:
                raise ValueError(f"未知 profile：{case.profile}")
            image = (screens / case.image).resolve()
            if not image.is_relative_to(screens) or not image.is_file():
                raise ValueError(f"截图不存在或不在 screens 下：{case.image}")
        return self


def _cases():
    paths = sorted((FIXTURES / "cases").glob("*.json"))
    assert paths, "缺少截图案例 JSON"
    for path in paths:
        bundle = CaseFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for case in bundle.cases:
            yield pytest.param(bundle.profiles[case.profile], case, id=f"{path.stem}-{case.id}")


@pytest.mark.parametrize(("profile", "case"), list(_cases()))
def test_annotated_screen(profile: Profile, case: Case) -> None:
    image = cv2.imread(str(FIXTURES / "screens" / case.image))
    assert image is not None
    assert (image.shape[1], image.shape[0]) == profile.capture_size
    image, _ = Normalizer(profile.design_size).fit(image)
    layout = LayoutConfig(**{k: list(v) for k, v in profile.layout.items()}).to_layout()
    parser = StateParser(layout, UIStateDetector(action_button=layout.end_turn))
    parser.load()
    state = parser.parse(image)
    actual = {
        "ui_state": state.ui_state,
        "mana": state.mana,
        "nexus_hp": state.nexus_hp,
        "enemy_nexus_hp": state.enemy_nexus_hp,
        "hand_costs": [card.cost for card in state.hand],
        "hand_expanded": state.hand_expanded,
        "my_unit_count": len(state.my_units),
        "enemy_unit_count": len(state.enemy_units),
    }
    for field in case.expected.model_fields_set:
        assert actual[field] == getattr(case.expected, field), f"{case.image}: {field}"
