# tests/test_architecture.py
#
# AGENTS.md §2 의존성 규칙·§7 금지사항을 ast 정적 분석으로 검증한다.
# 네트워크·crawl4ai·외부 의존 불필요 — 어디서든 항상 실행 가능.
#
# 아직 구현되지 않은 모듈(crawl.py/score.py/cli.py)은 skip — 킥오프 후 자동 활성화된다.

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent / "flight_picker"

PRIMITIVES = ["constants.py", "combine.py", "crawl_utils.py", "gflights.py", "naver.py"]

# 어떤 모듈에서도 금지 (AGENTS.md §2 — DB·웹서버 없는 프로젝트)
GLOBALLY_BANNED = {"psycopg2", "fastapi", "starlette", "flight_monitor"}


def _top_name(node: ast.Import | ast.ImportFrom) -> set[str]:
    """import 문이 가리키는 최상위 이름 집합. 상대 import는 모듈명 자체(e.g. 'crawl')."""
    names: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.name.split(".")[0])
    else:
        if node.level and node.module:            # from .crawl import ...
            names.add(node.module.split(".")[0])
        elif node.level and not node.module:      # from . import crawl
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif node.module:                          # from crawl4ai import ...
            names.add(node.module.split(".")[0])
    return names


def _collect(path: Path) -> tuple[set[str], set[str]]:
    """(모든 import, 런타임 import) 이름 집합.

    런타임 import = `if TYPE_CHECKING:` 블록과 `try:` 블록(ImportError 가드 패턴)
    바깥의 import. 가드된 import는 런타임 집합에서 제외한다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    all_imports: set[str] = set()
    runtime_imports: set[str] = set()

    def is_type_checking_guard(node: ast.If) -> bool:
        t = node.test
        return (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or (
            isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"
        )

    def visit(node: ast.AST, guarded: bool) -> None:
        for child in ast.iter_child_nodes(node):
            child_guarded = guarded
            if isinstance(child, ast.If) and is_type_checking_guard(child):
                child_guarded = True
            if isinstance(child, ast.Try):
                child_guarded = True
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                names = _top_name(child)
                all_imports.update(names)
                if not guarded:
                    runtime_imports.update(names)
            visit(child, child_guarded)

    visit(tree, False)
    return all_imports, runtime_imports


def _module(name: str) -> Path | None:
    p = PKG / name
    return p if p.exists() else None


class TestLayerRules:
    def test_primitives_no_upward_imports(self):
        """primitives → crawl/score/cli 역방향 import 금지 (§2)."""
        for name in PRIMITIVES:
            all_imports, _ = _collect(PKG / name)
            violations = all_imports & {"crawl", "score", "cli"}
            assert not violations, f"{name}: 상위 레이어 import 금지 — {violations}"

    def test_no_db_or_web_frameworks_anywhere(self):
        """psycopg2/fastapi/flight_monitor 등 전면 금지 (§2, §7)."""
        for path in sorted(PKG.glob("*.py")):
            all_imports, _ = _collect(path)
            violations = all_imports & GLOBALLY_BANNED
            assert not violations, f"{path.name}: 금지 의존성 — {violations}"

    def test_crawl4ai_runtime_import_only_in_crawl(self):
        """crawl4ai 런타임 import는 crawl.py 전용, 나머지는 TYPE_CHECKING/try 가드 (§2)."""
        for path in sorted(PKG.glob("*.py")):
            if path.name == "crawl.py":
                continue
            _, runtime = _collect(path)
            assert "crawl4ai" not in runtime, (
                f"{path.name}: crawl4ai 런타임 import는 crawl.py 전용 "
                f"(TYPE_CHECKING 가드를 사용할 것)"
            )

    def test_score_is_pure(self):
        """score.py는 크롤·네트워크·UI 의존 금지 (§2 순수성)."""
        p = _module("score.py")
        if p is None:
            pytest.skip("score.py 미구현 — 킥오프 후 자동 활성화")
        all_imports, _ = _collect(p)
        banned = {"crawl4ai", "crawl", "cli", "questionary", "rich",
                  "webbrowser", "requests", "httpx", "urllib"}
        violations = all_imports & banned
        assert not violations, f"score.py 순수성 위반 — {violations}"

    def test_cli_uses_crawl_layer_only(self):
        """cli.py는 crawl4ai·primitives 직접 사용 금지, crawl.py 경유 (§2)."""
        p = _module("cli.py")
        if p is None:
            pytest.skip("cli.py 미구현 — 킥오프 후 자동 활성화")
        all_imports, _ = _collect(p)
        banned = {"crawl4ai", "gflights", "naver", "crawl_utils"}
        violations = all_imports & banned
        assert not violations, f"cli.py: crawl.py 경유 필수 — {violations}"
