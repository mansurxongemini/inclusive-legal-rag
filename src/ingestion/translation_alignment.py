"""
Checks that the Russian text of a unit is the translation of its own Uzbek text (see scripts/audit_translations.py).
"""
import re

import numpy as np


def closer_matches(scores: dict, uz: dict, ru: dict, margin: float) -> dict:
    """{unit id: (other unit id, similarity)} for Russian texts closer by more than `margin` to the Uzbek text of another
    unit of the same act than to their own."""
    acts: dict = {}
    for cid in scores:
        acts.setdefault(re.sub(r"_(?:a\d+_)?(?:p|art)_[\d_]+$|_preamble$", "", cid), []).append(cid)
    closer = {}
    for members in acts.values():
        matrix = np.stack([uz[c] / (np.linalg.norm(uz[c]) or 1.0) for c in members])
        for i, cid in enumerate(members):
            sims = matrix @ (ru[cid] / (np.linalg.norm(ru[cid]) or 1.0))
            j = int(np.argmax(sims))
            if j != i and sims[j] - sims[i] > margin:
                closer[cid] = (members[j], round(float(sims[j]), 4))
    return closer


_POINT_ID = re.compile(r"^(.*_p_)(\d+)$")
_POINT_LINE = re.compile(r"(?m)^\s*(\d+)\.\s")


def split_russian_overflow(units: dict) -> dict:
    """
    {canonical_id: (uz_text, ru_text)} of one act -> {canonical_id: new_ru_text} for the units whose Russian text changes.

    The Russian edition of Lex.uz carries no amendment notes, so a point that follows a repealed point stays glued to the
    previous one in Russian while the Uzbek edition splits it off (VMQ-62 annex 9: Russian point 44 held 46-48, the
    criteria of disability groups I-III, and units 46-48 had no Russian text). A Russian line "46. ..." inside unit 44 is
    moved to unit 46 when unit 46 exists and has no Russian text of its own.
    """
    by_base: dict = {}
    for cid in units:
        m = _POINT_ID.match(cid)
        if m:
            by_base.setdefault(m.group(1), {})[int(m.group(2))] = cid
    changes: dict = {}
    for points in by_base.values():
        for n, cid in points.items():
            ru = changes.get(cid, units[cid][1]) or ""
            cuts = [(m.start(), int(m.group(1))) for m in _POINT_LINE.finditer(ru)
                    if int(m.group(1)) > n and int(m.group(1)) in points
                    and not (units[points[int(m.group(1))]][1] or "").strip()]
            if not cuts:
                continue
            bounds = cuts + [(len(ru), None)]
            changes[cid] = ru[: cuts[0][0]].rstrip()
            for (start, number), (end, _) in zip(bounds, bounds[1:]):
                changes[points[number]] = ru[start:end].strip()
    return changes
