# flight_picker/score.py
#
# 순수 필터링/스코어링/랭킹 — 크롤·네트워크·UI 의존 0 (AGENTS.md §2).
# 입력은 combine.combine_roundtrips 가 만든 offer dict 리스트.

from __future__ import annotations

import re
from datetime import datetime

_HHMM_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?$")

# balance 모드 가중치: 체류시간 / 가격(낮을수록 가점) / 가는편 이른 출발(이를수록 가점)
_W_STAY = 0.4
_W_PRICE = 0.4
_W_EARLY = 0.2


def _hhmm_to_min(value: str | None) -> int | None:
    """'HH:MM'(또는 'HH') → 자정 기준 분. None/'??:??'/파싱 불가 → None."""
    if not value:
        return None
    m = _HHMM_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


def stay_minutes(offer: dict) -> int | None:
    """현지 체류 시간(분) = (귀국일 @ 오는편 출발) − (출발일 @ 가는편 도착).

    가는편 도착·오는편 출발 시각 중 하나라도 없거나 '??:??'면 None.
    """
    arr_min = _hhmm_to_min(offer.get("out_arr_time"))
    dep_min = _hhmm_to_min(offer.get("in_dep_time"))
    if arr_min is None or dep_min is None:
        return None
    dep_date = datetime.strptime(offer["departure_date"], "%Y-%m-%d")
    ret_date = datetime.strptime(offer["return_date"], "%Y-%m-%d")
    day_min = int((ret_date - dep_date).total_seconds()) // 60
    return day_min + dep_min - arr_min


def filter_offers(
    offers: list[dict],
    *,
    out_dep_before: str | None = None,
    in_dep_after: str | None = None,
    direct_only: bool = False,
    exclude_airlines: tuple[str, ...] = (),
) -> list[dict]:
    """조건에 맞는 offer만 남긴다.

    - out_dep_before: 가는편 출발 시각 <= 기준('HH:MM' 또는 'HH'). 시각 미상 offer는 제외.
    - in_dep_after:   오는편 출발 시각 >= 기준. 시각 미상 offer는 제외.
    - direct_only:    가는편·오는편 모두 직항(stops==0)만.
    - exclude_airlines: 가는편/오는편 어느 쪽이든 해당 항공사면 제외.
    """
    before_min = _hhmm_to_min(out_dep_before)
    after_min = _hhmm_to_min(in_dep_after)
    excluded = set(exclude_airlines)

    result: list[dict] = []
    for offer in offers:
        if before_min is not None:
            dep = _hhmm_to_min(offer.get("out_dep_time"))
            if dep is None or dep > before_min:
                continue
        if after_min is not None:
            dep = _hhmm_to_min(offer.get("in_dep_time"))
            if dep is None or dep < after_min:
                continue
        if direct_only and not (offer.get("out_stops") == 0 and offer.get("in_stops") == 0):
            continue
        if excluded and (offer.get("out_airline") in excluded or offer.get("in_airline") in excluded):
            continue
        result.append(offer)
    return result


def _norm(value: float, lo: float, hi: float) -> float:
    """min-max 정규화. 범위가 0이면 0.5."""
    if hi <= lo:
        return 0.5
    return (value - lo) / (hi - lo)


def rank_offers(offers: list[dict], *, priority: str) -> list[dict]:
    """priority 기준으로 정렬하고 각 offer에 stay_minutes·score·rank를 부여해 반환.

    - 'price':   가격 오름차순. score = -price.
    - 'stay':    체류시간 내림차순(미상은 최하위), 동점 시 가격 오름차순. score = 체류분(미상 0).
    - 'balance': 후보 내 min-max 정규화 가중합 — 체류 길수록↑, 가격 낮을수록↑, 가는편 출발 이를수록↑.
    """
    if priority not in ("price", "stay", "balance"):
        raise ValueError(f"알 수 없는 priority: {priority!r} (price/stay/balance)")

    for offer in offers:
        offer["stay_minutes"] = stay_minutes(offer)

    if priority == "price":
        for offer in offers:
            offer["score"] = -float(offer["price"])
        ranked = sorted(offers, key=lambda o: o["price"])
    elif priority == "stay":
        for offer in offers:
            offer["score"] = float(offer["stay_minutes"] or 0)
        ranked = sorted(offers, key=lambda o: (-(o["stay_minutes"] or -1), o["price"]))
    else:  # balance
        stays = [o["stay_minutes"] for o in offers if o["stay_minutes"] is not None]
        prices = [o["price"] for o in offers]
        deps = [m for o in offers if (m := _hhmm_to_min(o.get("out_dep_time"))) is not None]
        stay_lo, stay_hi = (min(stays), max(stays)) if stays else (0, 0)
        price_lo, price_hi = (min(prices), max(prices)) if prices else (0, 0)
        dep_lo, dep_hi = (min(deps), max(deps)) if deps else (0, 0)
        for offer in offers:
            stay = offer["stay_minutes"]
            n_stay = _norm(stay, stay_lo, stay_hi) if stay is not None else 0.0
            n_price = _norm(offer["price"], price_lo, price_hi)
            dep = _hhmm_to_min(offer.get("out_dep_time"))
            n_dep = _norm(dep, dep_lo, dep_hi) if dep is not None else 1.0
            offer["score"] = (
                _W_STAY * n_stay + _W_PRICE * (1.0 - n_price) + _W_EARLY * (1.0 - n_dep)
            )
        ranked = sorted(offers, key=lambda o: (-o["score"], o["price"]))

    for i, offer in enumerate(ranked, start=1):
        offer["rank"] = i
    return ranked
