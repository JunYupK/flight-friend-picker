# CLAUDE.md

> **프로젝트 명세 / 아키텍처 / 인터페이스 / 금지사항은 [`AGENTS.md`](./AGENTS.md) 참고.**
> 본 파일은 LLM 행동 규범만 담는다. 충돌 시 AGENTS.md 우선.

---

## Behavioral guidelines

Behavioral guidelines to reduce common LLM coding mistakes. **Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project: flight-picker

ICN 출발 일본 왕복 항공권 온디맨드 비교 CLI. 터미널에서 조건을 고르면 구글 플라이트+네이버를
라이브 크롤해 조건 스코어링·랭킹하고, 선택 시 예약 딥링크로 연결한다.

상세 명세(레이어, 의존성 규칙, 역공학 코드 보호, 금지사항, 명령어)는 `AGENTS.md` 참고.
특히 **`gflights.py`/`naver.py`의 셀렉터·protobuf는 임의 수정 금지** (AGENTS.md §5).
