"""Vector đại diện (Centroids) cho từng miền kiến thức (Domain/Phòng ban).

Hỗ trợ nạp từ file JSON (data/centroids.json) hoặc tính toán động từ embeddings.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np


def _unit(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.where(n == 0, 1, n)


def kmeans(x: np.ndarray, k: int, seed: int = 0, iters: int = 20) -> np.ndarray:
    x = _unit(x.astype(np.float64))
    k = max(1, min(k, len(x)))
    rng = np.random.default_rng(seed)
    cent = x[rng.choice(len(x), size=k, replace=False)]
    for _ in range(iters):
        assign = np.argmax(x @ cent.T, axis=1)
        new = np.stack([x[assign == i].mean(axis=0) if np.any(assign == i) else cent[i] for i in range(k)])
        new = _unit(new)
        if np.allclose(new, cent, atol=1e-6):
            break
        cent = new
    return cent


class CentroidStore:
    def __init__(self, path: str = "data/centroids.json", check_every: float = 30.0):
        self.path = path
        self.check_every = check_every
        self._mtime = None
        self._checked = 0.0
        self._data: dict[str, np.ndarray] = {}
        self.error = ""

    def get(self) -> dict[str, np.ndarray]:
        now = time.monotonic()
        if now - self._checked >= self.check_every or not self._data:
            self._checked = now
            if not os.path.exists(self.path):
                return self._data
            try:
                m = os.path.getmtime(self.path)
                if m != self._mtime:
                    with open(self.path, encoding="utf-8") as f:
                        raw = json.load(f)
                    domains = raw.get("domains", {})
                    self._data = {d: _unit(np.array(v, dtype=np.float64)) for d, v in domains.items()}
                    self._mtime = m
                    self.error = ""
            except Exception as e:
                self.error = f"Không nạp được centroid: {type(e).__name__}"
        return self._data

    def set_centroids(self, domain_vectors: dict[str, list[list[float]]]):
        """Cập nhật trực tiếp centroids và ghi file."""
        self._data = {d: _unit(np.array(v, dtype=np.float64)) for d, v in domain_vectors.items()}
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"built_at": int(time.time()), "domains": domain_vectors}, f, ensure_ascii=False, indent=2)
            self._mtime = os.path.getmtime(self.path)
        except Exception:
            pass
