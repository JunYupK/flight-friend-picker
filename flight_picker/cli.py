# flight_picker/cli.py
#
# 인터랙티브(questionary+rich) + argparse 논-인터랙티브 터미널 UI (AGENTS.md §2 CLI 레이어).
# 크롤은 crawl.py 경유, 스코어링은 score.py 경유 — crawl4ai/primitives 직접 사용 금지.

from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from datetime import date

import questionary
from rich.console import Console
from rich.table import Table

from .constants import _AIRLINE_IATA, JAPAN_AIRPORTS, ORIGIN
from .crawl import crawl_offers_sync
from .score import filter_offers, rank_offers

_TIME_RE = re.compile(r"^\d{1,2}(:\d{2})?$")

_PRIORITY_CHOICES = [
    ("💰 가격 최소", "price"),
    ("⏱️ 체류 최대", "stay"),
    ("⚖️ 균형 (가격·체류·이른 출발)", "balance"),
]

console = Console()


# ── 입력 검증 ────────────────────────────────────────────────────────────────

def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _validate_date(value: str) -> bool | str:
    return _parse_date(value) is not None or "YYYY-MM-DD 형식으로 입력하세요"


def _validate_time_or_empty(value: str) -> bool | str:
    if not value.strip():
        return True
    return bool(_TIME_RE.match(value.strip())) or "HH:MM 또는 HH 형식 (비우면 제한 없음)"


def _ask(question: questionary.Question) -> object:
    """질문 실행 — 취소(Ctrl-C)면 종료."""
    answer = question.ask()
    if answer is None:
        console.print("[yellow]취소했습니다.[/yellow]")
        sys.exit(1)
    return answer


# ── 인터랙티브 플로우 ────────────────────────────────────────────────────────

def _ask_conditions() -> dict:
    dest_choices = [
        questionary.Choice(f"{code} — {name}", value=code)
        for code, name in JAPAN_AIRPORTS.items()
    ] + [questionary.Choice("직접 입력 (IATA 코드)", value="__custom__")]
    dest = str(_ask(questionary.select("목적지를 선택하세요", choices=dest_choices)))
    if dest == "__custom__":
        dest = str(_ask(questionary.text(
            "IATA 공항 코드 (예: OKJ)",
            validate=lambda v: bool(re.fullmatch(r"[A-Za-z]{3}", v.strip())) or "IATA 3글자 코드",
        ))).strip().upper()

    dep = str(_ask(questionary.text("출발일 (YYYY-MM-DD)", validate=_validate_date))).strip()

    def validate_ret(value: str) -> bool | str:
        d = _parse_date(value)
        if d is None:
            return "YYYY-MM-DD 형식으로 입력하세요"
        return d >= _parse_date(dep) or "귀국일은 출발일 이후여야 합니다"

    ret = str(_ask(questionary.text("귀국일 (YYYY-MM-DD)", validate=validate_ret))).strip()

    priority = str(_ask(questionary.select(
        "우선순위를 선택하세요",
        choices=[questionary.Choice(label, value=value) for label, value in _PRIORITY_CHOICES],
        default="balance",
    )))
    out_before = str(_ask(questionary.text(
        "가는편 출발 이전 시각 (HH:MM, 비우면 제한 없음)", validate=_validate_time_or_empty))).strip()
    in_after = str(_ask(questionary.text(
        "오는편 출발 이후 시각 (HH:MM, 비우면 제한 없음)", validate=_validate_time_or_empty))).strip()
    direct_only = bool(_ask(questionary.confirm("직항만 볼까요?", default=False)))
    exclude = _ask(questionary.checkbox(
        "제외할 항공사 (스페이스로 선택, 없으면 엔터)",
        choices=sorted(set(_AIRLINE_IATA)),
    ))

    return {
        "dest": dest,
        "dep_date": dep,
        "ret_date": ret,
        "priority": priority,
        "out_dep_before": out_before or None,
        "in_dep_after": in_after or None,
        "direct_only": direct_only,
        "exclude_airlines": tuple(exclude),
    }


# ── 출력 ─────────────────────────────────────────────────────────────────────

def _fmt_stay(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _fmt_leg(dep_time: str | None, arr_time: str | None, stops: int | None) -> str:
    leg = f"{dep_time or '??:??'}→{arr_time or '??:??'}"
    if stops == 0:
        return f"{leg} 직항"
    if stops:
        return f"{leg} 경유{stops}"
    return leg


def _fmt_airlines(offer: dict) -> str:
    out_al, in_al = offer.get("out_airline") or "?", offer.get("in_airline") or "?"
    return out_al if out_al == in_al else f"{out_al} / {in_al}"


def _print_table(ranked: list[dict], dest: str, dest_name: str, dep: str, ret: str) -> None:
    table = Table(title=f"{ORIGIN} ⇄ {dest} {dest_name} | 출발 {dep} → 귀국 {ret}")
    table.add_column("순위", justify="right")
    table.add_column("가는편")
    table.add_column("오는편")
    table.add_column("항공사")
    table.add_column("체류", justify="right")
    table.add_column("가격", justify="right")
    table.add_column("소스")
    for offer in ranked:
        table.add_row(
            str(offer["rank"]),
            _fmt_leg(offer.get("out_dep_time"), offer.get("out_arr_time"), offer.get("out_stops")),
            _fmt_leg(offer.get("in_dep_time"), offer.get("in_arr_time"), offer.get("in_stops")),
            _fmt_airlines(offer),
            _fmt_stay(offer.get("stay_minutes")),
            f"{offer['price']:,}원",
            offer["source"],
        )
    console.print(table)


def _pick_and_open(ranked: list[dict]) -> None:
    if not sys.stdin.isatty():
        return
    choices = [
        questionary.Choice(
            f"{o['rank']}위 | {_fmt_leg(o.get('out_dep_time'), o.get('out_arr_time'), o.get('out_stops'))}"
            f" | {_fmt_airlines(o)} | {o['price']:,}원 | {o['source']}",
            value=str(i),
        )
        for i, o in enumerate(ranked)
    ] + [questionary.Choice("종료", value="__quit__")]
    picked = str(_ask(questionary.select("예약 페이지를 열 항공권을 선택하세요", choices=choices)))
    if picked == "__quit__":
        return
    offer = ranked[int(picked)]
    console.print(f"[green]브라우저에서 여는 중:[/green] {offer['out_url']}")
    webbrowser.open(offer["out_url"])


# ── 진입점 ───────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight_picker",
        description="ICN 출발 일본 왕복 항공권 온디맨드 비교 CLI (옵션 없이 실행하면 인터랙티브)",
    )
    parser.add_argument("--dest", help="목적지 IATA 코드 (예: FUK)")
    parser.add_argument("--out", dest="out_date", help="출발일 YYYY-MM-DD")
    parser.add_argument("--in", dest="in_date", help="귀국일 YYYY-MM-DD")
    parser.add_argument("--priority", choices=["price", "stay", "balance"], default="balance",
                        help="정렬 우선순위 (기본: balance)")
    parser.add_argument("--out-before", help="가는편 출발 이전 시각 (HH:MM 또는 HH)")
    parser.add_argument("--in-after", help="오는편 출발 이후 시각 (HH:MM 또는 HH)")
    parser.add_argument("--direct", action="store_true", help="직항만")
    return parser


def _conditions_from_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict:
    if not (args.dest and args.out_date and args.in_date):
        parser.error("논-인터랙티브 모드는 --dest --out --in 을 모두 지정해야 합니다")
    dep, ret = _parse_date(args.out_date), _parse_date(args.in_date)
    if dep is None or ret is None:
        parser.error("--out/--in 은 YYYY-MM-DD 형식이어야 합니다")
    if ret < dep:
        parser.error("귀국일(--in)은 출발일(--out) 이후여야 합니다")
    for flag, value in (("--out-before", args.out_before), ("--in-after", args.in_after)):
        if value and not _TIME_RE.match(value.strip()):
            parser.error(f"{flag} 는 HH:MM 또는 HH 형식이어야 합니다")
    return {
        "dest": args.dest.strip().upper(),
        "dep_date": args.out_date,
        "ret_date": args.in_date,
        "priority": args.priority,
        "out_dep_before": args.out_before,
        "in_dep_after": args.in_after,
        "direct_only": args.direct,
        "exclude_airlines": (),
    }


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.dest or args.out_date or args.in_date:
        cond = _conditions_from_args(args, parser)
    else:
        cond = _ask_conditions()

    dest = cond["dest"]
    dest_name = JAPAN_AIRPORTS.get(dest, dest)

    with console.status(f"[bold green]{dest_name}({dest}) 항공권 라이브 크롤 중... (수십 초 소요)[/bold green]"):
        offers = crawl_offers_sync(dest, dest_name, cond["dep_date"], cond["ret_date"])

    if not offers:
        console.print("[red]크롤 결과가 없습니다. 네트워크/안티봇 상태를 확인하고 다시 시도하세요.[/red]")
        sys.exit(1)

    filtered = filter_offers(
        offers,
        out_dep_before=cond["out_dep_before"],
        in_dep_after=cond["in_dep_after"],
        direct_only=cond["direct_only"],
        exclude_airlines=cond["exclude_airlines"],
    )
    if not filtered:
        console.print(f"[yellow]조건에 맞는 결과가 없습니다 (크롤 {len(offers)}건). 필터를 완화해 보세요.[/yellow]")
        sys.exit(1)

    ranked = rank_offers(filtered, priority=cond["priority"])
    _print_table(ranked, dest, dest_name, cond["dep_date"], cond["ret_date"])
    _pick_and_open(ranked)
