"""The label schema for guidance in an earnings press release. The hand labels
(the gold set) and the extraction prompt's replies both take this shape, so they
are scored field by field. Labeling rules: `docs/fundamentals/guidance_probe.md`.

One `ReleaseLabel` per release; one `GuidanceItem` per (metric, period) the
company gives an outlook for. A range for adjusted EPS and one for GAAP EPS in the
same year are two items.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal["revenue", "eps", "margin", "other"]
Period = Literal["quarter", "year", "other"]
Shape = Literal["range", "point", "floor", "ceiling", "qualitative"]
Basis = Literal["gaap", "adjusted", "unstated"]
# raised / maintained / lowered: the release itself compares the outlook with the
# company's previous one. initiated: the release says it is the first outlook for
# that period. not_stated: no comparison either way (the release doesn't say, even
# if an earlier release would show one). withdrawn: the company pulls its outlook
# (an item with shape 'qualitative').
Revision = Literal["raised", "maintained", "lowered", "initiated", "withdrawn", "not_stated"]
READABLE_REVISIONS = ("raised", "maintained", "lowered")


class GuidanceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Metric
    metric_text: str = Field(description="the metric as the release names it, e.g. 'adjusted diluted EPS', "
                                         "'capital expenditures'")
    period: Period
    period_text: str = Field(description="the period as the release names it, e.g. 'fiscal 2019', "
                                         "'third quarter', 'full year 2015'")
    shape: Shape
    low: float | None = Field(description="lower end; for a point, the value; for a ceiling or qualitative, null")
    high: float | None = Field(description="upper end; for a point, the value; for a floor or qualitative, null")
    unit: str = Field(description="e.g. 'USD per share', 'USD millions', 'USD billions', 'percent', "
                                  "'percent growth'")
    basis: Basis
    revision: Revision
    evidence: str = Field(description="the sentence the item comes from, verbatim, at most ~300 characters")

    @model_validator(mode="after")
    def _bounds_match_shape(self) -> "GuidanceItem":
        need = {"range": (True, True), "point": (True, True), "floor": (True, False),
                "ceiling": (False, True), "qualitative": (False, False)}[self.shape]
        if (self.low is not None, self.high is not None) != need:
            raise ValueError(f"shape {self.shape!r} needs low/high present = {need}")
        if self.shape == "point" and self.low != self.high:
            raise ValueError("a point has low == high")
        if self.shape == "range" and self.low > self.high:
            raise ValueError("a range has low <= high")
        return self


class ReleaseLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guidance_present: bool
    items: list[GuidanceItem]
    notes: str = Field(default="", description="anything a reviewer should know, e.g. 'outlook only in the "
                                               "attached slides', 'guidance withdrawn'")

    @model_validator(mode="after")
    def _items_match_presence(self) -> "ReleaseLabel":
        if self.guidance_present != bool(self.items):
            raise ValueError("guidance_present must be true exactly when there are items")
        return self
