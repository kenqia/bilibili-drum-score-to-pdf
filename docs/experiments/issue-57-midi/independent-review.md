# Independent complete-score musical review

Root viewed only `/tmp/issue57-demo/full-score.png`, freshly rendered from the whole PDF, before seeing the implementer transcription or MusicXML. This is a controlled complete three-measure percussion score with an explicit legend, not a real Bilibili song acceptance.

The visible legend maps bottom-space oval to bass drum GM36, C5 oval to snare GM38, G5 x with open-circle to open hi-hat GM46, A5 x to crash GM49. Velocity conventions are printed: unmarked96, f112, p64, grace48. Grace is printed as 1/16 quarter beat before its main note. The slash small note before the dotted eighth is a snare grace note.

Measure1 is4/4, quarter120. Upper voice: three snare eighth-triplets on beats0,1/3,2/3, each duration1/3; a snare dotted-eighth at1 duration3/4, followed by snare sixteenth at7/4 duration1/4; open hi-hat eighths at2 and5/2 duration1/2 each; crash quarter at3 duration1. Grace snare at15/16 duration1/16, before the main at1. Lower voice: bass-drum quarters at0 and2, duration1 each, with printed quarter rests at1 and3. Main notes use printed default96, grace48.

Measure2 is3/4, quarter160 and f. Two snare quarters at0 and1, duration1 each and velocity112, then a quarter rest at2. The start-repeat sign before measure1 and end-repeat sign after measure2 repeat measures1–2 twice in total.

Measure3 is4/4, quarter100 and p, with a full-measure rest and final double barline. It adds four beats of silence and no hits.

Playback sequence is1,2,1,2,3. Total18 quarter beats. Eleven hits in each pass of measure1 including the grace and bass voice; two in each pass of measure2; zero in measure3. Total26 hits. Tempo changes at unfolded beats0:120,4:160,7:120,11:160,14:100. Time signatures at the same boundaries are4/4,3/4,4/4,3/4,4/4. At480PPQ the complete end is8640ticks. The legend supplies default96 for the unmarked measure1 on each repeat; no recording dynamics or arbitrary swing inferred.

No unresolved mapping in this controlled score because its legend is explicit. This does not resolve KiLLKiSS author mapping.

Root then independently viewed the revised whole-score render again. Two added visible legend rules are explicit: repeat playback resets measure1 velocity to96; grace cuts the preceding same-drum release at grace onset while notation stays unchanged. Musical content/order remains the same. Therefore the final snare triplet at2/3 keeps notated duration1/3, but actual MIDI gate is15/16−2/3=13/48. All other gates above stay unchanged. Grace starts15/16 and ends1; there is no same-note playback overlap. Current full PDF SHA256 is 1d6413b4176dc274c409a288728f0d1258bfd1191a70ad9384aa081df6c4af3d.

Text-only correction after the independent event transcription: the snare legend says C5 oval, not G5 oval. Whole-PDF text extraction confirmed the letter; this corrects my glyph reading and does not change the GM38 event mapping, which I had read from the explicit legend.
