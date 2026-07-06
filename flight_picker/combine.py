# flight_picker/combine.py
#
# my-flight-friend/flight_monitor/offer_utils.py 에서 포팅 (KST import 경로만 수정).
# 편도 왕/복편 → 왕복 offer 조합. crawl4ai 의존 없음.

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .constants import KST


def combine_roundtrips(
    out_flights: list[dict], in_flights: list[dict], *,
    source: str, origin: str, destination: str, destination_name: str,
    stay_durations: list[int], topk: int,
    allow_mixed_airline: bool = True,
) -> list[dict]:
    """편도 왕/복편 조합으로 왕복 오퍼 생성.

    out_flights/in_flights: {"date": "YYYY-MM-DD", "price": int, ...} leg dict 리스트.
    반환: offer dict 리스트 (가격 오름차순).
    """
    out_idx: dict[str, list] = defaultdict(list)
    in_idx:  dict[str, list] = defaultdict(list)
    for f in out_flights:
        out_idx[f["date"]].append(f)
    for f in in_flights:
        in_idx[f["date"]].append(f)

    for d in out_idx:
        out_idx[d] = sorted(out_idx[d], key=lambda x: x["price"])[:topk]
    for d in in_idx:
        in_idx[d] = sorted(in_idx[d], key=lambda x: x["price"])[:topk]

    results = []
    for dep_date, outs in out_idx.items():
        dep_dt = datetime.strptime(dep_date, "%Y-%m-%d")
        for stay in stay_durations:
            ret_date = (dep_dt + timedelta(days=stay)).strftime("%Y-%m-%d")
            ins = in_idx.get(ret_date)
            if not ins:
                continue
            for out in outs:
                for ret in ins:
                    out_al = out.get("airline", "")
                    in_al  = ret.get("airline", "")
                    is_mixed = bool(out_al and in_al and out_al != in_al)
                    if is_mixed and not allow_mixed_airline:
                        continue
                    results.append({
                        "source":           source,
                        "trip_type":        "oneway_combo",
                        "origin":           origin,
                        "destination":      destination,
                        "destination_name": destination_name,
                        "departure_date":   dep_date,
                        "return_date":      ret_date,
                        "stay_nights":      stay,
                        "price":            out["price"] + ret["price"],
                        "currency":         "KRW",
                        "out_airline":      out_al,
                        "in_airline":       in_al,
                        "is_mixed_airline": is_mixed,
                        "out_dep_time":     out.get("dep_time"),
                        "out_arr_time":     out.get("arr_time"),
                        "out_duration_min": out.get("duration_min"),
                        "out_stops":        out.get("stops"),
                        "in_dep_time":      ret.get("dep_time"),
                        "in_arr_time":      ret.get("arr_time"),
                        "in_duration_min":  ret.get("duration_min"),
                        "in_stops":         ret.get("stops"),
                        "out_arr_airport":  out.get("arr_airport"),
                        "in_dep_airport":   ret.get("dep_airport"),
                        "out_url":          out.get("booking_url") or out.get("search_url"),
                        "in_url":           ret.get("booking_url") or ret.get("search_url"),
                        "out_price":        out["price"],
                        "in_price":         ret["price"],
                        "checked_at":       datetime.now(KST).isoformat(),
                    })

    results.sort(key=lambda x: x["price"])
    return results
