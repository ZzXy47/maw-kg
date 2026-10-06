#!/usr/bin/env python3
"""Bake-off 2026-10-06: MAW-KG vs GitNexus vs CodeGraph vs AOCI.
Shared question set across the 6-repo fixture matrix, run by harness_* scripts.
Ground truth established per-question in ground_truth.md (human-verified file:line).

Question set (12 questions, each answered by every tool where applicable):
Q1  route→handler: ekko POST /api/ekko/memory/:id maps to which controller fn?
Q2  client consumer: which client file:line calls GET /api/ekko/memory?
Q3  cross-package fan-out: server route file changed → which client API files affected?
Q4  symbol impact: RegistrationsView.post change → Android/iOS consumers (HA trio)
Q5  ArkTS HTTP: list all HTTP endpoints in homogram-arkts (.ets)
Q6  car/AAOS: in aaos-car-codelabs, find the class handling temperature display
Q7  freshness: change one symbol → reflected in query? (seconds)
Q8  false-positive probe: query a nonexistent symbol — fabricated hits?
Q9  worktree isolation: two worktrees, disjoint edits — cross-contamination?
Q10 exact-match discipline: search 'post' — does it return ONLY exact matches?
Q11 contract check: mobile-app-registration contract — all endpoints still bound?
Q12 daemon governance: kill daemon → next query behavior (stale-lock self-clean?)
"""
QUESTION_SET = {
    "Q1": "ekko: route POST /api/ekko/memory/:id → controller symbol",
    "Q2": "ekko: client consumer of GET /api/ekko/memory",
    "Q3": "ekko: server route change → client API files affected",
    "Q4": "HA: RegistrationsView.post impact → Android/iOS consumers",
    "Q5": "ArkTS: enumerate HTTP endpoints in homogram-arkts",
    "Q6": "AAOS: temperature display class",
    "Q7": "freshness: symbol edit → query reflects change (s)",
    "Q8": "FP probe: nonexistent symbol returns nothing (no fabrication)",
    "Q9": "worktree isolation: disjoint edits don't cross",
    "Q10": "exact-match discipline on common name 'post'",
    "Q11": "contract check: 3 contracts, 14 bindings all real",
    "Q12": "daemon governance: stale lock self-cleans, next query OK",
}
