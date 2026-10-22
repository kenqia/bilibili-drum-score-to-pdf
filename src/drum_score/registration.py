"""Column-band registration adapted from the user-provided video2pdf.py.

Original attachment SHA-256:
2ea5ddd758665efd48320d15e3be5c39706dd6dc290eb4e6dd738a75b87ee239.
Permission was reported by the user; no separate upstream license is inferred.
Only adjacent forward positions are searched by the product caller.
"""
import cv2
import numpy as np

NB = 64
LOCAL_GOOD = 0.7

def profile_of(g, invalid):
    """Column-band row profile of the ink, plus how much of each cell was valid.

    Invalid pixels (playhead color, overlays) are *unknown*, not blank, so a
    highlighted note never looks like a missing note during matching.
    """
    ink = (255.0 - g.astype(np.float32)) / 255.0
    ink = np.clip((ink - 0.2) / 0.8, 0, 1)          # drop paper tint / blocking noise
    valid = (~invalid).astype(np.float32)
    size = (NB, g.shape[0])
    s_ink = cv2.resize(ink * valid, size, interpolation=cv2.INTER_AREA)
    s_val = cv2.resize(valid, size, interpolation=cv2.INTER_AREA)
    # vertical blur: thin staff lines must not make sub-pixel shifts look like mismatches
    s_ink = cv2.GaussianBlur(s_ink, (1, 0), sigmaX=0.1, sigmaY=1.5)
    s_val = cv2.GaussianBlur(s_val, (1, 0), sigmaX=0.1, sigmaY=1.5)
    P = np.where(s_val > 0.05, s_ink / np.maximum(s_val, 1e-6), 0).astype(np.float32)
    return P, s_val.astype(np.float32)

def _overlap(A, B, dy):
    nA, nB = len(A[0]), len(B[0])
    a0, a1 = max(0, dy), min(nA, dy + nB)
    return a0, a1, a0 - dy, a1 - dy

def costs_over(A, B, dys, min_ov):
    """Global cost of placing profile B so that B[y] ~ A[y + dy] (A may be longer).

    Weighted, normalised L1 distance: 0 = identical, 1 = no common ink.
    """
    (PA, WA), (PB, WB) = A, B
    out = np.full(len(dys), np.inf, np.float32)
    for i, dy in enumerate(dys):
        a0, a1, b0, b1 = _overlap(A, B, dy)
        if a1 - a0 < min_ov:
            continue
        w = WA[a0:a1] * WB[b0:b1]
        if (w.mean(1) > 0.3).sum() < min_ov:
            continue
        a, b = PA[a0:a1], PB[b0:b1]
        den = (w * (a + b)).sum()
        if den < 1e-3 * a.size:              # nearly blank overlap: uninformative
            continue
        out[i] = (w * np.abs(a - b)).sum() / den
    return out

def local_cost(A, B, dy, blk=24):
    """Worst cell (blk rows x 1 band) of the overlap. Repeated systems that only
    differ by their measure number match globally but fail here."""
    (PA, WA), (PB, WB) = A, B
    a0, a1, b0, b1 = _overlap(A, B, dy)
    n = (a1 - a0) // blk * blk
    if n == 0:
        return np.inf
    w = (WA[a0:a0 + n] * WB[b0:b0 + n])
    a, b = PA[a0:a0 + n], PB[b0:b0 + n]
    shp = (-1, blk, a.shape[1])
    D = (w * np.abs(a - b)).reshape(shp).sum(1)
    S = (w * (a + b)).reshape(shp).sum(1)
    Wm = w.reshape(shp).mean(1)
    ok = (S > 1.5) & (Wm > 0.6)
    if not ok.any():
        return np.inf
    return float((D[ok] / S[ok]).max())

def down4(X):
    P, W = X
    n = len(P) // 4 * 4
    return (P[:n].reshape(-1, 4, P.shape[1]).mean(1), W[:n].reshape(-1, 4, W.shape[1]).mean(1))

def _subpixel(c, k):
    if 0 < k < len(c) - 1 and np.isfinite(c[k - 1]) and np.isfinite(c[k + 1]):
        den = c[k - 1] - 2 * c[k] + c[k + 1]
        if den > 1e-9:
            return float(np.clip(0.5 * (c[k - 1] - c[k + 1]) / den, -0.5, 0.5))
    return 0.0

def fine_shift(A, B, lo, hi, min_ov):
    """Exhaustive full-resolution search in [lo, hi]. Returns (dy_float, cost)."""
    d = np.arange(lo, hi + 1)
    c = costs_over(A, B, d, min_ov)
    k = int(np.argmin(c))
    if not np.isfinite(c[k]):
        return None, np.inf
    return int(d[k]) + _subpixel(c, k), float(c[k])

def shift_candidates(A, B, lo, hi, min_ov, top=6):
    """Coarse-to-fine search in [lo, hi]; returns [(cost, dy_float, local)] best first."""
    if hi < lo:
        return []
    A4, B4 = down4(A), down4(B)
    d4 = np.arange(lo // 4, hi // 4 + 1)
    c4 = costs_over(A4, B4, d4, max(2, min_ov // 4))
    # local minima of the coarse curve, best first
    mins = [j for j in range(len(c4)) if np.isfinite(c4[j])
            and (j == 0 or c4[j] <= c4[j - 1]) and (j == len(c4) - 1 or c4[j] <= c4[j + 1])]
    mins.sort(key=lambda j: c4[j])
    out = []
    for j in mins[:top]:
        d = np.arange(max(lo, d4[j] * 4 - 5), min(hi, d4[j] * 4 + 5) + 1)
        c = costs_over(A, B, d, min_ov)
        k = int(np.argmin(c))
        if np.isfinite(c[k]):
            out.append((float(c[k]), int(d[k]) + _subpixel(c, k), local_cost(A, B, int(d[k]))))
    out.sort()
    return out

def pick(cands, global_thr, prefer=None, strict=False, reject_ambiguity=False):
    """Choose among (global, dy, local) candidates passing the global test.

    Near-ties (repeated identical systems) are broken by the local test (measure
    numbers differ), then by closeness to `prefer`. With strict=True the local
    test is also a hard requirement (used before accepting jumps). With
    reject_ambiguity=True, equivalent positions separated by more than two
    pixels have no chosen result; temporal evidence must resolve them."""
    ok = [c for c in cands if c[0] <= global_thr and (not strict or c[2] <= LOCAL_GOOD)]
    if not ok:
        return None, (cands[0][0] if cands else np.inf)
    cmin = ok[0][0]
    ok = [c for c in ok if c[0] <= cmin * 1.15 + 0.005]
    ok.sort(key=lambda c: (round(c[2] / 0.15), abs(c[1] - prefer) if prefer is not None else c[0]))
    if reject_ambiguity and any(abs(candidate[1] - ok[0][1]) > 2
            and round(candidate[2] / 0.15) == round(ok[0][2] / 0.15) for candidate in ok[1:]):
        return None, ok[0][0]
    return ok[0][1], ok[0][0]
