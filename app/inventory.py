"""Car search: hard filters in SQL, soft scoring + capped aging boost in Python.

The LLM never filters or ranks. It only passes criteria (validated by
`Requirements`) and relays whatever this module returns.

HARD filters (a car failing any of these is never returned):
    status == available, budget_min/budget_max, fuel_types, transmission, seats_min
SOFT preferences (only affect ranking):
    body_type, makes, max_km, min_year, plus "more car for the money" within budget
AGING boost:
    small, capped, applied only to cars that already passed every hard filter.
"""
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import STATUS_AVAILABLE, Car, get_session

log = logging.getLogger(__name__)

MAX_RESULTS = 3
_MAKE_RE = re.compile(r"^[a-z0-9 .&-]{1,30}$")  # makes are stored and shown to the LLM: keep them inert

# Soft-preference weights.
W_BODY = 3.0
W_MAKE = 2.0
W_KM = 1.5
W_YEAR = 1.0
W_BUDGET = 1.0  # nudges toward the better car within budget (price / budget_max)

# Aging boost: linear ramp from 0 to the cap over AGING_FULL_BOOST_DAYS.
# The cap is below the smallest soft weight, so aging can break near-ties
# but can never outrank a car that satisfies one more stated preference.
AGING_BOOST_MAX = 0.5
AGING_FULL_BOOST_DAYS = 180

FuelType = Literal["petrol", "diesel", "cng", "electric", "hybrid"]
Transmission = Literal["manual", "automatic"]
BodyType = Literal["hatchback", "sedan", "suv", "muv"]


class Requirements(BaseModel):
    """Customer criteria. All fields optional; unknown keys are ignored.

    Prices are whole rupees (the LLM layer converts "8 lakh" / "10L" to 800000 / 1000000).
    """

    model_config = ConfigDict(extra="ignore")

    # Hard filters
    budget_max: int | None = Field(None, gt=0, le=100_000_000)
    budget_min: int | None = Field(None, ge=0)
    fuel_types: list[FuelType] | None = None  # any of these
    transmission: Transmission | None = None
    seats_min: int | None = Field(None, ge=1, le=12)  # at least this many seats

    # Soft preferences
    body_type: BodyType | None = None
    makes: list[str] | None = None
    models: list[str] | None = None
    max_km: int | None = Field(None, gt=0)
    min_year: int | None = Field(None, ge=1990, le=2100)

    @field_validator("fuel_types", "makes", "models", mode="before")
    @classmethod
    def _normalise_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = [v]
        if isinstance(v, list):
            return [x.strip().lower() if isinstance(x, str) else x for x in v]
        return v

    @field_validator("makes", "models", mode="after")
    @classmethod
    def _check_names(cls, v: list[str] | None, info: Any) -> list[str] | None:
        if v is not None and (
            len(v) > 5
            or not all(_MAKE_RE.match(name) for name in v)
        ):
            raise ValueError(f"{info.field_name} must be up to 5 short car names")
        return v

    @field_validator("transmission", "body_type", mode="before")
    @classmethod
    def _normalise_str(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check_budget_range(self) -> "Requirements":
        if self.budget_min and self.budget_max and self.budget_min > self.budget_max:
            raise ValueError("budget_min cannot exceed budget_max")
        return self


@dataclass
class _Match:
    car: Car
    fit: float
    boost: float
    reasons: list[str]

    @property
    def total(self) -> float:
        return self.fit + self.boost


def _lakh(rupees: int) -> str:
    return "Rs " + f"{rupees / 100_000:.2f}".rstrip("0").rstrip(".") + "L"


def _body_label(body: str) -> str:
    return body.upper() if body in {"suv", "muv"} else body


def _aging_boost(car: Car, today: date) -> float:
    days_in_stock = max((today - car.date_added).days, 0)
    return AGING_BOOST_MAX * min(days_in_stock / AGING_FULL_BOOST_DAYS, 1.0)


def _score(car: Car, req: Requirements, today: date) -> _Match:
    fit = 0.0
    reasons: list[str] = []

    if req.budget_max:
        fit += W_BUDGET * car.price / req.budget_max
        reasons.append(f"within your {_lakh(req.budget_max)} budget")
    if req.transmission:
        reasons.append(f"{car.transmission} as requested")
    if req.fuel_types:
        reasons.append(f"{car.fuel_type} as requested")
    if req.seats_min:
        reasons.append(f"{car.seats} seats")

    if req.body_type and car.body_type == req.body_type:
        fit += W_BODY
        reasons.append(f"{_body_label(car.body_type)} as preferred")
    if req.makes and any(m in car.make.lower() for m in req.makes):  # 'maruti' matches 'Maruti Suzuki'
        fit += W_MAKE
        reasons.append(f"{car.make} as preferred")
    if req.models and any(m in car.model.lower() for m in req.models):
        fit += W_MAKE
        reasons.append(f"{car.model} as requested")
    if req.max_km and car.km_driven <= req.max_km:
        fit += W_KM
        reasons.append(f"only {car.km_driven:,} km")
    if req.min_year and car.year >= req.min_year:
        fit += W_YEAR
        reasons.append(f"{car.year} model")

    if not reasons:
        reasons.append(f"{car.year} {car.fuel_type} {car.transmission} {_body_label(car.body_type)}")

    return _Match(car, fit, _aging_boost(car, today), reasons[:4])


def _to_dict(m: _Match) -> dict[str, Any]:
    """What the LLM may see. Deliberately excludes date_added / days in stock / score."""
    c = m.car
    reason = "; ".join(m.reasons)
    return {
        "id": c.id,
        "make": c.make,
        "model": c.model,
        "year": c.year,
        "price": c.price,
        "km_driven": c.km_driven,
        "fuel_type": c.fuel_type,
        "transmission": c.transmission,
        "body_type": c.body_type,
        "seats": c.seats,
        "promo_offer": c.promo_offer,
        "image_url": c.image_url,
        "reason": reason[0].upper() + reason[1:],
    }


def _search(req: Requirements, session: Session, today: date) -> list[dict[str, Any]]:
    # 1. Hard filters (parameterised SQL; values are already validated).
    stmt = select(Car).where(Car.status == STATUS_AVAILABLE)
    if req.budget_max:
        stmt = stmt.where(Car.price <= req.budget_max)
    if req.budget_min:
        stmt = stmt.where(Car.price >= req.budget_min)
    if req.fuel_types:
        stmt = stmt.where(Car.fuel_type.in_(req.fuel_types))
    if req.transmission:
        stmt = stmt.where(Car.transmission == req.transmission)
    if req.seats_min:
        stmt = stmt.where(Car.seats >= req.seats_min)
    if req.models:
        # Model names are an explicit request: only return matching inventory.
        model_filters = [Car.model.ilike(f"%{model}%") for model in req.models]
        from sqlalchemy import or_
        stmt = stmt.where(or_(*model_filters))
    candidates = session.scalars(stmt).all()

    # 2. Soft scoring + capped aging boost, only over cars that passed step 1.
    matches = [_score(car, req, today) for car in candidates]
    matches.sort(key=lambda m: (-m.total, m.car.id))  # id = deterministic tie-break
    top = matches[:MAX_RESULTS]

    log.info(
        "search %s -> %d candidates, returning %d",
        req.model_dump(exclude_none=True),
        len(candidates),
        len(top),
    )
    return [_to_dict(m) for m in top]


def search_cars(
    requirements: Requirements | dict[str, Any],
    session: Session | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return up to 3 best-matching available cars, each with a short `reason`.

    Raises pydantic.ValidationError on bad input; the LLM layer should catch it
    and return the error text to the model so it can correct its arguments.
    An empty list means nothing matched; hard filters are never relaxed here.
    """
    req = requirements if isinstance(requirements, Requirements) else Requirements.model_validate(requirements)
    today = today or date.today()
    if session is not None:
        return _search(req, session, today)
    with get_session() as s:
        return _search(req, s, today)
