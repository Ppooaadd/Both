"""Left-hand accompaniment patterns.

Every pattern turns a chord span into bar-aligned events. Within one hand the
output is a chord stream (no overlaps), which the playability pass relies on.

| pattern  | texture                                   | step          |
|----------|-------------------------------------------|---------------|
| root     | bass note per bar (+ fifth when dense)    | bar           |
| block    | voiced chord on strong beats              | half bar/beat |
| alberti  | low-high-mid-high broken triad            | eighth        |
| arpeggio | 1-5-8-10(-12) open rising figure         | eighth / 16th |
| stride   | bass on strong beats, chord on off beats  | beat          |
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pianoforge.arrangement.events import Ev
from pianoforge.arrangement.harmony import Span
from pianoforge.arrangement.profiles import Profile
from pianoforge.arrangement.score_ir import TPQ, PedalSpan
from pianoforge.arrangement.voicing import VoiceLeader, place
from pianoforge.db.enums import Difficulty

PATTERNS = ("root", "block", "alberti", "arpeggio", "stride")
SUSTAINED = ("alberti", "arpeggio", "stride")

BassAt = Callable[[int], int | None]


@dataclass(frozen=True)
class PatternContext:
    profile: Profile
    beats_per_bar: int
    grid: int
    tempo_bpm: float
    density: float
    bass_at: BassAt  # transcribed bass pitch class at a tick (advanced), or None

    @property
    def bar(self) -> int:
        return self.beats_per_bar * TPQ


def resolve_pattern(requested: str, ctx: PatternContext) -> str:
    p = ctx.profile
    if requested != "auto":
        # Patterns that need finer rhythm than the level allows fall back gracefully.
        if requested in ("alberti", "arpeggio") and p.grid > TPQ // 2:
            return "block"
        return requested
    if p.difficulty == Difficulty.beginner:
        return "block" if ctx.density >= 0.5 else "root"
    if p.difficulty == Difficulty.intermediate:
        if ctx.tempo_bpm > 125 or ctx.density < 0.3:
            return "block"
        return "arpeggio" if ctx.density >= 0.6 else "alberti"
    if ctx.tempo_bpm > 140:
        return "stride"
    return "arpeggio"


class LeftHand:
    def __init__(self, ctx: PatternContext) -> None:
        self.ctx = ctx
        p = ctx.profile
        self.chords = VoiceLeader(p.lh_chord_range[0], p.lh_chord_range[1], min(p.max_span, 12))
        self.prev_bass: int | None = None

    # ------------------------------------------------------------------ helpers
    def bass_pitch(self, span: Span, tick: int) -> int:
        lo, hi = self.ctx.profile.lh_bass_range
        pc = span.bass_pc
        if self.ctx.profile.follow_bass_line:
            heard = self.ctx.bass_at(tick)
            if heard is not None and heard in span.pcs:
                pc = heard
        pitch = place(
            pc, lo, hi, near=self.prev_bass if self.prev_bass is not None else (lo + hi) // 2
        )
        assert pitch is not None  # bass range always spans >= an octave
        self.prev_bass = pitch
        return pitch

    def _ev(self, pitch: int, s: int, e: int, vel: int, role: str = "accomp") -> Ev:
        return Ev("lh", pitch, s, e, vel, role)  # type: ignore[arg-type]

    def _hits(self, span: Span, positions: list[int]) -> list[int]:
        """Absolute ticks inside the span at the given bar-relative positions (+ span start)."""
        bar = self.ctx.bar
        ticks = {span.start}
        first_bar = span.start - span.start % bar
        for b in range(first_bar, span.end, bar):
            ticks.update(b + p for p in positions if span.start <= b + p < span.end)
        return sorted(ticks)

    @staticmethod
    def _until_next(ticks: list[int], end: int) -> list[tuple[int, int]]:
        return [(t, ticks[i + 1] if i + 1 < len(ticks) else end) for i, t in enumerate(ticks)]

    # ----------------------------------------------------------------- patterns
    def root(self, span: Span) -> list[Ev]:
        out: list[Ev] = []
        for s, e in self._until_next(self._hits(span, [0]), span.end):
            b = self.bass_pitch(span, s)
            out.append(self._ev(b, s, e, 70, "bass"))
            if self.ctx.density >= 0.5 and self.ctx.profile.max_poly >= 2:
                fifth = (span.root + 7) % 12 if span.quality != "dim" else (span.root + 6) % 12
                f = b + ((fifth - b) % 12 or 12)
                if f - b <= self.ctx.profile.max_span:
                    out.append(self._ev(f, s, e, 60))
        return out

    def block(self, span: Span) -> list[Ev]:
        num = self.ctx.beats_per_bar
        dense = self.ctx.density >= 0.7 and self.ctx.profile.difficulty != Difficulty.beginner
        positions = (
            [i * TPQ for i in range(num)] if dense else [0] if num % 2 else [0, (num // 2) * TPQ]
        )
        size = min(3, self.ctx.profile.max_poly)
        if self.ctx.profile.difficulty == Difficulty.beginner:
            # Beginner: two-note shapes in the bass register instead of full triads.
            return self.root(span) if size < 2 else self._beginner_dyads(span, positions)
        out: list[Ev] = []
        for s, e in self._until_next(self._hits(span, positions), span.end):
            for p in self.chords.next(span.pcs, size):
                out.append(self._ev(p, s, e, 62))
        return out

    def _beginner_dyads(self, span: Span, positions: list[int]) -> list[Ev]:
        out: list[Ev] = []
        for s, e in self._until_next(self._hits(span, positions), span.end):
            b = self.bass_pitch(span, s)
            out.append(self._ev(b, s, e, 68, "bass"))
            third = span.pcs[1]
            t = b + ((third - b) % 12 or 12)
            fifth = span.pcs[2] if len(span.pcs) > 2 else third
            f = b + ((fifth - b) % 12 or 12)
            upper = f if f - b <= self.ctx.profile.max_span else t
            out.append(self._ev(upper, s, e, 58))
        return out

    def _broken(
        self, span: Span, figure: list[int], step: int, open_voicing: bool = False
    ) -> list[Ev]:
        """Emit ``figure`` (indices into chord tones) every ``step`` ticks; restart on each hit."""
        out: list[Ev] = []
        num = self.ctx.beats_per_bar
        restart = [0] if num % 2 else [0, (num // 2) * TPQ]
        for s, e in self._until_next(self._hits(span, restart), span.end):
            tones = self._open_tones(span, s) if open_voicing else self._figure_tones(span, s)
            t, i = s, 0
            while t < e:
                idx = figure[i % len(figure)]
                pitch = tones[min(idx, len(tones) - 1)]
                role = "bass" if i == 0 else "accomp"
                out.append(self._ev(pitch, t, min(t + step, e), 66 if i == 0 else 56, role))
                t += step
                i += 1
        return out

    def _figure_tones(self, span: Span, tick: int) -> list[int]:
        """Bass + chord tones stacked upward, within the level's hand span."""
        b = self.bass_pitch(span, tick)
        tones = [b]
        for pc in [*span.pcs[1:], span.root]:
            nxt = tones[-1] + ((pc - tones[-1]) % 12 or 12)
            if nxt - b <= self.ctx.profile.max_span:
                tones.append(nxt)
        if self.ctx.profile.max_span >= 15:
            # Tenth: third above the octave.
            tenth = b + 12 + ((span.pcs[1] - b) % 12)
            if tenth - b <= self.ctx.profile.max_span and tenth not in tones:
                tones.append(tenth)
        return sorted(set(tones))

    def _open_tones(self, span: Span, tick: int) -> list[int]:
        """Open spacing 1-5-8-10(-12): clear low end, fits an octave-plus hand span."""
        b = self.bass_pitch(span, tick)
        fifth = span.pcs[2] if len(span.pcs) > 2 else span.root
        third = span.pcs[1]
        tones = [
            b,
            b + ((fifth - b) % 12 or 12),
            b + 12,
            b + 12 + ((third - b) % 12),
            b + 12 + ((fifth - b) % 12),
        ]
        return [t for t in tones if t - b <= self.ctx.profile.max_span]

    def alberti(self, span: Span) -> list[Ev]:
        # low - high - mid - high over (bass, third, fifth)
        return self._broken(span, [0, 2, 1, 2], max(self.ctx.grid, TPQ // 2))

    def arpeggio(self, span: Span) -> list[Ev]:
        fast = (
            self.ctx.profile.difficulty == Difficulty.advanced
            and self.ctx.density >= 0.6
            and self.ctx.tempo_bpm <= 110
            and self.ctx.grid <= TPQ // 4
        )
        step = TPQ // 4 if fast else max(self.ctx.grid, TPQ // 2)
        figure = [0, 1, 2, 3, 4, 3, 2, 1] if fast else [0, 1, 2, 3]
        return self._broken(span, figure, step, open_voicing=True)

    def stride(self, span: Span) -> list[Ev]:
        num = self.ctx.beats_per_bar
        strong = {0} if num % 2 else {0, num // 2}
        out: list[Ev] = []
        beats = self._hits(span, [i * TPQ for i in range(num)])
        size = min(3, self.ctx.profile.max_poly)
        for s, e in self._until_next(beats, span.end):
            if (s % self.ctx.bar) // TPQ in strong or s == span.start:
                b = self.bass_pitch(span, s)
                out.append(self._ev(b, s, e, 72, "bass"))
                low = b - 12
                if (
                    self.ctx.profile.difficulty == Difficulty.advanced
                    and low >= self.ctx.profile.lh_bass_range[0] - 5
                    and low >= 21
                ):
                    out.append(self._ev(low, s, e, 66, "bass"))
            else:
                for p in self.chords.next(span.pcs, size):
                    out.append(self._ev(p, s, e, 58))
        return out


def generate_left_hand(
    spans: list[Span], pattern: str, ctx: PatternContext
) -> tuple[list[Ev], list[PedalSpan]]:
    lh = LeftHand(ctx)
    fn = getattr(lh, pattern)
    events: list[Ev] = []
    for span in spans:
        events.extend(fn(span))
    pedal: list[PedalSpan] = []
    if ctx.profile.use_pedal and pattern in SUSTAINED:
        # Change pedal on every chord change; lift slightly early to avoid blur.
        for sp in spans:
            end = sp.end - min(ctx.grid, TPQ // 4)
            if end > sp.start:
                pedal.append(PedalSpan(start=sp.start, end=end))
    return events, pedal
