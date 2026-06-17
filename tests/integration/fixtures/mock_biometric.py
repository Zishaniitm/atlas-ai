"""
Synthetic biometric fixtures for integration tests.

Uses pre-computed fake embeddings — no real voice or face data
is ever committed to this repository.

SRS: SRS Section 11.3 (never commit real biometric data),
     SRS Section 11.4 (voice persona testing with mock TTS)
"""

from __future__ import annotations

import numpy as np


# ── Voice print fixtures ──────────────────────────────────────

def make_owner_voice_embedding() -> np.ndarray:
    """
    Return a deterministic synthetic 256-d voice embedding for 'the owner'.

    Same seed = same vector every test run → reproducible thresholds.

    SRS: FR-081 (Resemblyzer 256-d embedding), SRS 11.3
    """
    rng = np.random.default_rng(seed=42)
    vec = rng.standard_normal(256).astype(np.float32)
    return vec / np.linalg.norm(vec)   # unit vector (cosine similarity ready)


def make_similar_voice_embedding(noise: float = 0.05) -> np.ndarray:
    """
    Return a voice embedding close to the owner's (same speaker, different take).

    Args:
        noise: Magnitude of perturbation. 0.05 → high similarity (should pass auth).
    """
    base = make_owner_voice_embedding()
    rng = np.random.default_rng(seed=99)
    perturbed = base + rng.standard_normal(256).astype(np.float32) * noise
    return perturbed / np.linalg.norm(perturbed)


def make_stranger_voice_embedding() -> np.ndarray:
    """
    Return a voice embedding for a completely different speaker (should fail auth).

    SRS: FR-083 (liveness + threshold enforcement)
    """
    rng = np.random.default_rng(seed=777)
    vec = rng.standard_normal(256).astype(np.float32)
    return vec / np.linalg.norm(vec)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two unit vectors. Range: [-1, 1]."""
    return float(np.dot(a, b))


# ── Face embedding fixtures ───────────────────────────────────

def make_owner_face_embedding() -> np.ndarray:
    """
    Return a deterministic synthetic 512-d face embedding (InsightFace ArcFace).

    SRS: FR-084 (InsightFace 512-d embedding), SRS 11.3
    """
    rng = np.random.default_rng(seed=123)
    vec = rng.standard_normal(512).astype(np.float32)
    return vec / np.linalg.norm(vec)


def make_similar_face_embedding(noise: float = 0.1) -> np.ndarray:
    """
    Return a face embedding close to the owner's (same person, different angle).

    Args:
        noise: Perturbation magnitude. 0.1 → euclidean distance ~0.2 (should pass).
    """
    base = make_owner_face_embedding()
    rng = np.random.default_rng(seed=456)
    perturbed = base + rng.standard_normal(512).astype(np.float32) * noise
    return perturbed / np.linalg.norm(perturbed)


def make_stranger_face_embedding() -> np.ndarray:
    """
    Return a face embedding for a different person (should fail auth).

    Distance from owner will be >> 0.45 threshold.

    SRS: FR-085 (face distance threshold 0.45)
    """
    rng = np.random.default_rng(seed=999)
    vec = rng.standard_normal(512).astype(np.float32)
    return vec / np.linalg.norm(vec)


def euclidean_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Euclidean distance between two vectors."""
    return float(np.linalg.norm(a - b))


# ── Audio fixture ─────────────────────────────────────────────

def make_silent_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    """
    Return a silent audio array for testing STT pipeline.

    SRS: SRS 11.4 (mock audio for voice pipeline tests)

    Args:
        duration_sec: Length of audio in seconds.
        sample_rate: Sample rate in Hz. Whisper expects 16000.

    Returns:
        Float32 numpy array of zeros.
    """
    samples = int(duration_sec * sample_rate)
    return np.zeros(samples, dtype=np.float32)


def make_noise_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    """
    Return low-amplitude random noise audio for testing silence detection.

    Args:
        duration_sec: Length in seconds.
        sample_rate: Sample rate. Whisper expects 16000.

    Returns:
        Float32 numpy array with values in [-0.005, 0.005].
    """
    samples = int(duration_sec * sample_rate)
    rng = np.random.default_rng(seed=0)
    return (rng.standard_normal(samples) * 0.005).astype(np.float32)
