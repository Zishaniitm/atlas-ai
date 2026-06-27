"""
Synthetic biometric fixtures — NO real voice or face data committed.
SRS: Section 11.3 (never commit real biometric data)
"""
from __future__ import annotations
import numpy as np


# ── Voice print fixtures (Resemblyzer 256-d) ──────────────────

def owner_voice() -> np.ndarray:
    """Deterministic 256-d voice embedding for 'the owner'. SRS: FR-081"""
    rng = np.random.default_rng(seed=42)
    v = rng.standard_normal(256).astype(np.float32)
    return v / np.linalg.norm(v)


def similar_voice(noise: float = 0.05) -> np.ndarray:
    """Same speaker, different recording — should PASS auth (threshold 0.92)."""
    base = owner_voice()
    rng  = np.random.default_rng(seed=99)
    v    = base + rng.standard_normal(256).astype(np.float32) * noise
    return v / np.linalg.norm(v)


def stranger_voice() -> np.ndarray:
    """Different speaker — should FAIL auth."""
    rng = np.random.default_rng(seed=777)
    v   = rng.standard_normal(256).astype(np.float32)
    return v / np.linalg.norm(v)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


# ── Face embedding fixtures (InsightFace ArcFace 512-d) ───────

def owner_face() -> np.ndarray:
    """Deterministic 512-d face embedding. SRS: FR-084"""
    rng = np.random.default_rng(seed=123)
    v   = rng.standard_normal(512).astype(np.float32)
    return v / np.linalg.norm(v)


def similar_face(noise: float = 0.1) -> np.ndarray:
    """Same person, different angle — should PASS (distance < 0.45)."""
    base = owner_face()
    rng  = np.random.default_rng(seed=456)
    v    = base + rng.standard_normal(512).astype(np.float32) * noise
    return v / np.linalg.norm(v)


def stranger_face() -> np.ndarray:
    """Different person — should FAIL (distance > 0.45)."""
    rng = np.random.default_rng(seed=999)
    v   = rng.standard_normal(512).astype(np.float32)
    return v / np.linalg.norm(v)


def euclidean_dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


# ── Audio fixtures ────────────────────────────────────────────

def silent_audio(duration_sec: float = 1.0, sr: int = 16000) -> np.ndarray:
    """Silent float32 audio for STT pipeline tests. SRS: Section 11.4"""
    return np.zeros(int(duration_sec * sr), dtype=np.float32)


def noise_audio(duration_sec: float = 1.0, sr: int = 16000) -> np.ndarray:
    """Low-amplitude noise for silence-detection tests."""
    rng = np.random.default_rng(seed=0)
    return (rng.standard_normal(int(duration_sec * sr)) * 0.005).astype(np.float32)


# ── Sanity checks (run with pytest -v) ───────────────────────

def test_owner_voice_is_unit_vector() -> None:
    v = owner_voice()
    assert abs(np.linalg.norm(v) - 1.0) < 1e-5


def test_similar_voice_passes_threshold() -> None:
    """Similar voice should exceed the 0.92 cosine threshold."""
    sim = cosine_sim(owner_voice(), similar_voice(noise=0.02))
    assert sim > 0.92, f"Expected >0.92 but got {sim:.4f}"


def test_stranger_voice_fails_threshold() -> None:
    """Stranger voice should be well below the 0.92 threshold."""
    sim = cosine_sim(owner_voice(), stranger_voice())
    assert sim < 0.92, f"Expected <0.92 but got {sim:.4f}"


def test_similar_face_passes_threshold() -> None:
    """Similar face should be within the 0.45 distance threshold."""
    dist = euclidean_dist(owner_face(), similar_face(noise=0.05))
    assert dist < 0.45, f"Expected <0.45 but got {dist:.4f}"
