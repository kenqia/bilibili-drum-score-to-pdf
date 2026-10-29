# ruff: noqa: E701, E702
# Vendored algorithm; see ORIGIN.json for the original identity.
"""Global sequence-consistency filter for noisy local bar OCR.

No numerical interpolation is emitted as a confirmed reading. We only choose
an ordered subset of actually observed digits, document excluded observations
and their reasons, and never alter the source notation.
"""
from __future__ import annotations
from math import log
from statistics import median


def coherent_subset(anchors):
    """Choose maximum-support monotone subsequence with realistic measure step.

    Args: {row_index: {'value': int, 'confidence': 0..1, ...}}
    Returns: (accepted, rejected, expected_step). Links may cross missing OCR
    labels but must have a plausible positive number of bars per staff row.
    """
    if len(anchors)<3:return dict(anchors),[],None
    nodes=sorted((int(i),int(v['value']),v) for i,v in anchors.items())
    ratios=[]
    for (i,a,_),(j,b,_) in zip(nodes,nodes[1:]):
        slope=(b-a)/(j-i)
        if .9<=slope<=9:ratios.append(slope)
    # No near-neighbor consensus? Use a broad range but no invented bar numbers.
    typical=float(median(ratios)) if ratios else 4.
    expected=max(1.,min(9.,typical))
    best=[]
    for n,(i,a,evidence) in enumerate(nodes):
        trust=float(evidence.get('confidence',.7))
        # A 1-row path is discouraged; candidates get rewards for being linked.
        local=2.0+trust*.6
        score=local;path=[n]
        for k,(j,b,_) in enumerate(nodes[:n]):
            slope=(a-b)/(i-j)
            if not 0.95<=slope<=16:continue
            # Prefer stable progression, allow true variations (e.g. 4 -> 5 bars).
            deviation=abs(log(slope/expected))
            penalty=min(2.5,0.65*deviation)
            # Less penalty for a big OCR gap: fewer constraints can be asserted.
            if i-j>8:penalty+=.18
            candidate=best[k][0]+local-penalty
            if candidate>score:
                score=candidate;path=best[k][1]+[n]
        best.append((score,path))
    path=max(best,key=lambda pair:pair[0])[1]
    chosen={nodes[p][0] for p in path}
    accepted={k:v for k,v in anchors.items() if int(k) in chosen}
    rejected=[{'row':i+1,'read':a,'reason':'inconsistent_with_best_global_monotonic_path'}
              for i,a,_ in nodes if i not in chosen]
    return accepted,rejected,round(expected,2)
