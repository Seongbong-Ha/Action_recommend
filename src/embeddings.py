"""
토픽 클러스터 기반 Mock 임베딩.
seed.py(저장)와 extract.py(검색 쿼리) 모두 이 모듈을 사용하여
동일한 벡터 공간을 공유 → mock 모드에서도 유사 검색이 동작.

토픽:
  _BASE_BUDGET   — 예산/성과/SA 관련 회의
  _BASE_CREATIVE — 소재/CTA/DA 관련 회의
  _BASE_ONBOARD  — 온보딩/일정/신규 광고주 관련 회의
"""

import hashlib

import numpy as np

_rng = np.random.default_rng(42)
_BASE_BUDGET   = _rng.standard_normal(768); _BASE_BUDGET   /= np.linalg.norm(_BASE_BUDGET)
_BASE_CREATIVE = _rng.standard_normal(768); _BASE_CREATIVE /= np.linalg.norm(_BASE_CREATIVE)
_BASE_ONBOARD  = _rng.standard_normal(768); _BASE_ONBOARD  /= np.linalg.norm(_BASE_ONBOARD)

_TOPIC_MAP = [
    ({"예산", "증액", "재배분", "ROAS", "roas", "성과", "SA", "sa", "비용", "구글", "입찰", "광고비"}, _BASE_BUDGET),
    ({"소재", "CTA", "cta", "크리에이티브", "검수", "DA", "da", "카카오", "A/B", "문구", "시안"}, _BASE_CREATIVE),
    ({"온보딩", "킥오프", "신규", "광고주", "자료", "계약", "브리프"}, _BASE_ONBOARD),
]


def topic_vec(base: np.ndarray, seed: int, noise: float = 0.12) -> list[float]:
    """base 벡터 근처에 결정론적 노이즈를 더한 768차원 벡터 반환."""
    v = base + np.random.default_rng(seed).standard_normal(768) * noise
    return (v / np.linalg.norm(v)).tolist()


def mock_embed(text: str) -> list[float]:
    """
    텍스트 키워드로 토픽을 판별해 해당 클러스터 근처 벡터 반환.
    동일 텍스트 → 동일 벡터 (결정론적).
    """
    words = set(text.split())
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
    for keywords, base in _TOPIC_MAP:
        if words & keywords:
            return topic_vec(base, seed=seed, noise=0.06)
    # 매칭 없으면 임의 방향 (세 토픽과 모두 멂)
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(768)
    return (v / np.linalg.norm(v)).tolist()
