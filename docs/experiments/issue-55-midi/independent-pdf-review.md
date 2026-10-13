# Independent PDF transcription candidate, 2026-10-13

I rendered `experiments/2026-10-13-BV15crrYUEPA/KiLLKiSS-vector-compact.pdf` freshly at 220 DPI with pdftoppm and actually viewed all three pages, then these whole-system PNGs: `row-1`, `row-6`, `row-20`, `row-24`, `row-32`, `row-64`, `row-72`, `row-110`, `row-134`. I additionally viewed `m75.png`, which contains the true beginning barline and first open-hi-hat. All evidence is under `/tmp/issue54-context/pdf-midi-review/`.

PDF SHA256 is `a4185c8c8d82a8ad54d4a3748c6d129c7480683370ee90d5b1f8ced28ee1e16c`. The source is this delivered vector facsimile, not the video or original crops. I have not read the MIDI implementer's original-source benchmark. This is an independent candidate for comparison, not a claim of reliable whole-song MIDI.

The title is KiLLKiSS, artist Ave Mujica, quarter note = 200, initial time signature 4/4. No changes of tempo or meter occur in the inspected snippets.

## Notation used below

Beat positions are zero-based quarter-note units in each measure. Thus beat 0 is the written first beat. `symbol@position/duration` gives the exact notated duration; fractions are exact. Durations follow flags, beams, dots, tuplet numbers and rests. I do not derive time from pixel spacing.

- `K` is the solid bottom-space head with down stem, conventionally bass drum.
- `S` is the solid second-space-from-top head, conventionally snare.
- `H` is the open-hi-hat cross immediately above the top line with printed `o`.
- `C` is the higher crossed oval on its ledger line, conventionally crash.
- `R` is the lower crossed oval above the staff without that upper ledger, conventionally ride.
- `T_hi` is the solid top-space head, `T_mid` the solid second-line head, and `T_low` the solid second-space-from-bottom head. Preserve these distinct written positions; exact GM tom numbers need an explicit mapping convention.
- `rest` means a printed rest. I distinguish unprinted remaining silence from an actually printed rest.

The PDF has no visible drum legend. K/S/H identifications are standard visual interpretations; C/R and tom GM allocation remain mapping decisions rather than provenance-proven facts. The two cymbal oval levels are visibly different and should not silently collapse to one event type.

## Fifteen measures

### Measure 1

Single main voice: `rest@0/1, rest@1/1, rest@2/1, rest@3/1/2, K@7/2/1/4, K@15/4/1/4`. The final pair has two beams. Total measure is four beats. No cymbal or snare hit occurs in the opening three beats.

### Measure 2

Upper voice: `C+S@0/1, rest@1/1/2, R+S@3/2/1/2, rest@2/1, C+S@3/1`.

Lower voice: `rest@0/1/2, K@1/2/1/2, K@1/1, K@2/1/2, K@5/2/1/2, rest@3/1/2, K@7/2/1/2`.

The flagged lower oval at 3/2 is R, while the first and fourth-beat oval heads are C. The lower-voice quarter at 1 overlaps the upper hit at 3/2.

### Measures 10 and 11

A heavy multi-measure-rest bar labeled `2` follows measure 9. Both measures contain no musical hits, lasting four quarter beats each. This is two measures of silence, not a two-beat rest or a single measure.

### Measure 23

Upper voice: `H@0/1, H+S@1/1, T_low@2/1/4, T_low@9/4/3/4, H+S@3/1`.

Lower voice: `rest@0/1/2, K@1/2/1/2, rest@1/1/2, K@3/2/1/4, K@7/4/1/4, rest@2/1/2, K@5/2/1/4, K@11/4/1/4, rest@3/1`.

The fill is a sixteenth followed by a dotted eighth at the same low-tom position. It is not an eighth plus dotted eighth, and the first fill head is not higher than the second.

### Measure 27

Upper voice: `rest@0/1, C+S@1/1/2, S@3/2/1/4, S@7/4/1/4, S@2/1/2, T_hi@5/2/1/2, T_low@3/1/2, T_low@7/2/1/2`.

Lower voice: `K@0/1/2, K@1/2/1/2`; no further bass-drum attacks appear. Remaining lower-voice silence is not an extra sequence of printed rests.

The first beamed group contains an eighth at 1 and two sixteenths at 3/2 and 7/4. The added partial lower beam connects only the latter pair. The last four hits are eighths.

### Measure 32

Upper voice: `C@0/1, C@1/1, C+S@2/1, C@3/1`.

Lower voice: `K@0/1/4, K@1/4/1/4, K@1/2/1/4, K@3/4/1/4, K@1/1/4, K@5/4/1/4, K@3/2/1/4, K@7/4/1/4, rest@2/1, K@3/1`.

Both four-hit groups have double beams. The eight first bass hits are sixteenths. The bass note on beat 3 is a quarter, not an eighth.

### Measure 67

Upper voice: `rest@0/1/2, H+S@1/2/1/2, H+S@1/1`, followed by two distinct eighth-note triplet groups. First group: `S@2/1/3, T_hi@7/3/1/3, T_hi@8/3/1/3`. Second group: `T_hi@3/1/3, T_low@10/3/1/3, T_low@11/3/1/3`.

Lower voice: `K@0/1, rest@1/1/2, K@3/2/1/4, K@7/4/1/4`, then no additional bass attacks. There are two printed `3` labels, each spanning one three-note eighth beam group. The quarter-beat sum of each group is 1, not 3/2.

### Measure 75

The first upper hit is `H@0/1`. It lies just after the beginning barline and must be retained. Then `rest@1/1/2`; lower-stem `K@3/2/1/4, K@7/4/1/4`; then `T_hi@2/3/4`, `S@11/4/1/4`, `rest@3/1/2`, `T_low@7/2/1/2`.

Each of the last three principal tom/snare hits has one small slashed grace head immediately before it at that same written pitch: grace T_hi before beat 2, grace S before 11/4, grace T_low before 7/2. Grace heads are not three extra measured eighths. The principal T_hi is a dotted eighth and principal S a sixteenth. A MIDI playback convention must specify stolen time and grace velocity; the printed score does not define numerical milliseconds. Do not silently remove these graces or give them arbitrary beat positions as if printed.

### Measure 110

Upper voice: `rest@0/1/2, S@1/2/1/2, H@1/1, H+S@2/1/2, S@5/2/1/2, R@3/1/2, C@7/2/1/2`.

Lower voice: silence before beat 1; `K@1/1/2, K@3/2/1/2, rest@2/1, K@3/1/2, K@7/2/1/2`.

### Measure 111

Upper voice: `rest@0/1/2, S@1/2/1/2, H@1/1, H+S@2/1, S@3/1/2, C@7/2/1/2`.

Lower voice: silence before beat 1; `K@1/1/2, K@3/2/1/4, K@7/4/1/4, rest@2/1/2, K@5/2/1/2, rest@3/1/2, K@7/2/1/2`.

### Measure 112

Upper voice is the same as measure 110.

Lower voice: silence before beat 1; `K@1/1/2, K@3/2/1/4, K@7/4/1/4, rest@2/1, K@3/1/2, K@7/2/1/2`.

Thus 112 differs from 110 in the lower beaming before beat 2: the ending eighth is split into two sixteenths. It is not safe to copy the whole measure 110 unchanged.

### Measure 113

Upper voice: `rest@0/1/2, S@1/2/1/2, H@1/1, T_hi@2/1/4, T_hi@9/4/3/4, C+S@3/1`.

Lower voice: silence before beat 1; `K@1/1/2, K@3/2/1/4, K@7/4/1/4, rest@2/1/2, K@5/2/1/4, K@11/4/1/4, rest@3/1/2, K@7/2/1/2`.

The upper same-pitch fill is a sixteenth and dotted eighth, this time at the higher tom level, not the low level of measure 23.

### Measure 134

Upper voice: `S+T_low@0/1/2, S+T_low@1/2/1/2, S+T_low@1/1/2, S+T_low@3/2/1/2, rest@2/1/2, R@5/2/1/2, rest@3/1/2, R@7/2/1/2`.

Lower voice: no early bass attacks; `K@5/2/1/2, K@7/2/1/2`. The two R notes carry explicit staccato dots. Their notated rhythmic value is still an eighth; MIDI sounding duration needs a declared staccato convention. Dots above the cymbals are articulation, not augmentation dots.

### Measure 135

Main upper voice: `rest@0/1/2, T_mid+T_low@1/2/1/2, T_mid+T_low@1/1/2, T_mid+T_low@3/2/1/2, T_mid+T_low@2/1/2, T_mid+T_low@5/2/1/2, C+S@3/1`.

No bass attacks are visible. The first three tom-pair eighths share one beam and the next two share a second beam. The terminal C+S is a quarter followed by the final barline. The total is four beats, and the short final system must not be interpreted as a shortened measure.

## Comparison limitations

This independent reading can detect event, pitch-level, rest, tuplet, grace, duration and articulation disagreement in fifteen measures. It cannot establish all 135 measures. It also cannot establish that the vector facsimile exactly preserves all source-video music. After comparison, any disputed event must be reviewed against original evidence rather than resolved by the candidate matching its own serialized MIDI. Exact drum mapping, unmarked dynamics, grace scheduling, staccato gate and cymbal MIDI duration require documented playback conventions before a reliable MIDI result can be claimed.
