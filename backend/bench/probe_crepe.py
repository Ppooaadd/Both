"""Prototype: CREPE f0 + segmentation vs Basic Pitch on real singing."""
from __future__ import annotations
import sys, time
import numpy as np, librosa, mir_eval, torch, torchcrepe, scipy.ndimage as ndi
from bench.run import separated
from bench.songs import REAL_VOCAL_TRACKS, real_vocal_song
from pianoforge.analysis.interfaces import TranscriptionRequest
from pianoforge.analysis.merge import _clean, melody_line
from pianoforge.analysis.registry import AdapterRegistry
from pianoforge.analysis.service import annotate_attacks
from pianoforge.config import Settings

def hz(p): return 440.0 * 2 ** ((np.asarray(p, float) - 69) / 12)

def score(song, notes, tol):
    ref_iv = np.array([[n.t0, n.t1] for n in song.melody]); ref_p = hz([n.pitch for n in song.melody])
    if not notes: return 0.0
    est_iv = np.array([[s, max(e, s + .01)] for s, e, _ in notes]); est_p = hz([p for *_, p in notes])
    return mir_eval.transcription.precision_recall_f1_overlap(ref_iv, ref_p, est_iv, est_p, onset_tolerance=tol, offset_ratio=None)[2]

_F0 = {}
def crepe_f0(y, sr, model, key):
    if (key, model) not in _F0:
        y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)
        f0, per = torchcrepe.predict(torch.tensor(y16)[None], 16000, hop_length=160, fmin=65, fmax=1000, model=model,
                                     decoder=torchcrepe.decode.viterbi, return_periodicity=True, batch_size=1024, device="cpu")
        _F0[(key, model)] = (y16, f0[0].numpy(), per[0].numpy())
    return _F0[(key, model)]

def crepe_notes(y, sr, model, per_thr, dev_st, min_dev, onset_split, key=None):
    y16, f0, per = crepe_f0(y, sr, model, key)
    per = ndi.median_filter(per, 3)
    rms = librosa.feature.rms(y=y16, frame_length=640, hop_length=160)[0][: len(f0)]
    rms = np.pad(rms, (0, len(f0) - len(rms)))
    gate = 10 ** (-35 / 20) * np.percentile(rms, 95)
    voiced = (per > per_thr) & (rms > gate)
    midi = 69 + 12 * np.log2(np.maximum(f0, 1) / 440)
    midi = ndi.median_filter(midi, 5)
    env = librosa.onset.onset_strength(y=y16, sr=16000, hop_length=160)
    env = np.pad(env, (0, max(0, len(f0) - len(env))))[: len(f0)]
    rel = env / (ndi.percentile_filter(env, 90, size=300) + 1e-6)
    notes = []
    i, n = 0, len(f0)
    fps = 100.0
    def close(a, b):
        if b - a < 6: return
        seg = midi[a + (b - a) // 5 : b]
        notes.append((a / fps, b / fps, int(round(float(np.median(seg))))))
    while i < n:
        if not voiced[i]: i += 1; continue
        start = i; cur = midi[i]; hist = [midi[i]]; dev = 0; j = i + 1
        while j < n and voiced[j]:
            ref = np.median(hist[-15:])
            if abs(midi[j] - ref) > dev_st: dev += 1
            else: dev = 0
            if dev >= min_dev:
                cut = j - min_dev + 1
                close(start, cut); start = cut; hist = list(midi[cut : j + 1]); dev = 0
            elif onset_split and rel[j] > onset_split and j - start > 12 and abs(midi[j] - ref) < 0.5 and rel[j] == rel[max(start,j-3):j+4].max():
                close(start, j); start = j; hist = [midi[j]]
            else:
                hist.append(midi[j])
            j += 1
        close(start, j); i = j
    return notes

def main():
    reg = AdapterRegistry(Settings())
    bp = reg.transcriber.primary()
    torch.set_num_threads(4)
    cfgs = [("tiny",0.3,0.7,5,1.2),("tiny",0.4,0.7,5,1.2)]  #

    agg = {}
    tracks = REAL_VOCAL_TRACKS[: int(sys.argv[1])] if len(sys.argv) > 1 else REAL_VOCAL_TRACKS
    for t in tracks:
        song = real_vocal_song(t); _, stems, _ = separated(song, reg, False)
        buf = stems["vocals"]; y = buf.mono_at(22050)
        raw = bp.transcribe(TranscriptionRequest(audio=buf, role="melody", min_hz=70, max_hz=1500))
        line = melody_line(_clean(annotate_attacks(raw, buf), "melody"))
        bpn = [(x.start, x.end, x.pitch) for x in line]
        for tol in (0.05, 0.1): agg.setdefault(("basic_pitch", tol), []).append(score(song, bpn, tol))
        for cfg in cfgs:
            t0 = time.time(); nn = crepe_notes(y, 22050, *cfg, key=t); el = time.time() - t0
            for tol in (0.05, 0.1): agg.setdefault((cfg, tol), []).append(score(song, nn, tol))
            agg.setdefault((cfg, "sec_per_min"), []).append(el / (len(y)/22050) * 60)
        print(t, flush=True)
    for k, v in agg.items(): print(k, round(float(np.mean(v)), 3))

if __name__ == "__main__":
    main()
