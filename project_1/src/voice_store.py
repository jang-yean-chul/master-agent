"""
가족 목소리 샘플 저장소 — 부모 음성 TTS(음성 클로닝) 준비 단계.

역할(엄마/아빠/할아버지/할머니)별로 직접 녹음한 mp3 샘플을 최대 2개 저장한다.
권장: 조용한 곳에서 또박또박 낭독한 약 2분짜리 녹음 2개
      (ElevenLabs Instant Voice Cloning 기준 1~3분이면 충분).

저장 위치: project_1/voices/<역할>/sample_N.mp3
※ 목소리는 개인정보이므로 voices/ 폴더는 git에서 제외한다.
"""
from __future__ import annotations

import io
from pathlib import Path

from mutagen.mp3 import MP3

VOICE_ROLES = ["엄마", "아빠", "할아버지", "할머니"]
MAX_SAMPLES_PER_ROLE = 2
MIN_SECONDS, MAX_SECONDS = 30, 300   # 허용 길이 (초)
TARGET_SECONDS = 120                 # 권장 길이 — 약 2분

VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"


def _role_dir(role: str) -> Path:
    if role not in VOICE_ROLES:
        raise ValueError(f"지원하지 않는 역할: {role} (가능: {', '.join(VOICE_ROLES)})")
    return VOICES_DIR / role


def _mp3_seconds(data: bytes) -> float | None:
    """mp3 길이(초)를 반환. 유효한 mp3가 아니면 None."""
    try:
        return float(MP3(io.BytesIO(data)).info.length)
    except Exception:
        return None


def list_samples(role: str) -> list[dict]:
    """역할별 저장된 샘플 목록: [{"path": Path, "seconds": float}]."""
    d = _role_dir(role)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("sample_*.mp3")):
        sec = _mp3_seconds(p.read_bytes())
        out.append({"path": p, "seconds": sec or 0.0})
    return out


def save_sample(role: str, data: bytes) -> tuple[bool, str]:
    """mp3 샘플 저장. (성공 여부, 사용자에게 보여줄 메시지)를 반환."""
    existing = list_samples(role)
    if len(existing) >= MAX_SAMPLES_PER_ROLE:
        return False, (
            f"{role} 목소리는 이미 {MAX_SAMPLES_PER_ROLE}개가 등록되어 있어요. "
            f"교체하려면 기존 샘플을 먼저 삭제해주세요."
        )

    seconds = _mp3_seconds(data)
    if seconds is None:
        return False, "유효한 mp3 파일이 아니에요. mp3 형식으로 다시 녹음/변환해주세요."
    if seconds < MIN_SECONDS:
        return False, (
            f"녹음이 너무 짧아요 ({seconds:.0f}초). "
            f"최소 {MIN_SECONDS}초, 약 {TARGET_SECONDS // 60}분을 권장해요."
        )
    if seconds > MAX_SECONDS:
        return False, (
            f"녹음이 너무 길어요 ({seconds / 60:.1f}분). "
            f"{MAX_SECONDS // 60}분 이내로 잘라서 올려주세요 (약 {TARGET_SECONDS // 60}분 권장)."
        )

    d = _role_dir(role)
    d.mkdir(parents=True, exist_ok=True)
    used = {p["path"].name for p in existing}
    slot = next(n for n in range(1, MAX_SAMPLES_PER_ROLE + 1) if f"sample_{n}.mp3" not in used)
    (d / f"sample_{slot}.mp3").write_bytes(data)
    return True, f"{role} 목소리 샘플 {slot}번 저장 완료! ({seconds / 60:.1f}분)"


def delete_sample(role: str, path: Path) -> None:
    """샘플 삭제 (voices/ 밖의 경로는 거부)."""
    path = Path(path).resolve()
    if _role_dir(role).resolve() not in path.parents:
        raise ValueError("voices 폴더 밖의 파일은 삭제할 수 없습니다.")
    path.unlink(missing_ok=True)


def roles_summary() -> dict[str, int]:
    """역할별 등록된 샘플 개수 (UI 표시용)."""
    return {role: len(list_samples(role)) for role in VOICE_ROLES}
