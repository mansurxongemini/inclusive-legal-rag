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
