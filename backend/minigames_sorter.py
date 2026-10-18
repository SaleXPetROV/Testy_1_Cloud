"""«Сортировщик» ENDLESS solo mode — IDENTICAL to frontend/src/minigames/sorterCore.js (tests check it).
3 lives; a wrong bin, a sorted hazard or a missed item costs one; the game lasts while lives remain.
The server never trusts the client's score: it replays the taps of the session."""
import math
from typing import Dict, List

MAX_ITEMS = 400
LIVES = 3
GAP_MS = 250
MIN_REACTION_MS = 150
BINS = 4
M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & M32


def mulberry32(seed: int):
    state = [seed & M32]

    def r() -> float:
        state[0] = (state[0] + 0x6D2B79F5) & M32
        t = state[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t = (t ^ ((t + _imul(t ^ (t >> 7), t | 61)) & M32)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296
    return r


def _js_round(x: float) -> int:          # JS Math.round: .5 goes up
    return math.floor(x + 0.5)


def make_items(seed: int, n: int = MAX_ITEMS) -> List[Dict]:
    r = mulberry32(seed)
    items = []
    for i in range(n):
        typ = int(r() * BINS)
        hazard = r() < 0.08 + 0.22 * min(1, i / 150)
        window = max(450, _js_round(1600 - 1150 * min(1, i / 120)))
        items.append({"i": i, "type": typ, "hazard": hazard, "window": window})
    return items


def mult(combo: int) -> int:
    return min(3, 1 + combo // 5)


def score(seed: int, actions: List[Dict]) -> Dict:
    items = make_items(seed)
    by_item: Dict[int, Dict] = {}
    for a in actions or []:
        try:
            i = int(a.get("i")); b = int(a.get("b")); t = float(a.get("t"))
        except (TypeError, ValueError, AttributeError):
            continue
        by_item.setdefault(i, {"i": i, "b": b, "t": t})
    at, pts, combo, cleared, best, lives, last = 0.0, 0, 0, 0, 0, LIVES, -1
    for it in items:
        if lives <= 0:
            break
        a = by_item.get(it["i"])
        end = at + it["window"]
        resolved = end
        if a and at + MIN_REACTION_MS <= a["t"] <= end:
            resolved = a["t"]
            ok = (a["b"] == -1) if it["hazard"] else (a["b"] == it["type"])
        else:
            ok = it["hazard"]
        if ok:
            combo += 1; cleared += 1; pts += 10 * mult(combo)
        else:
            lives -= 1; combo = 0
        best = max(best, combo)
        last = it["i"]
        at = resolved + GAP_MS
    return {"points": pts, "cleared": cleared, "best_combo": best, "lives_left": lives, "last_item": last, "duration_ms": at}


def stars(points: int, th=(300, 1000, 2000)) -> int:
    return 3 if points >= th[2] else 2 if points >= th[1] else 1 if points >= th[0] else 0
