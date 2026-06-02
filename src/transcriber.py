import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


def normalize_expected_speaker_count(value: Optional[int]) -> Optional[int]:
    if value is None or value == 0:
        return None
    if value < 0:
        raise ValueError("expected_speaker_count는 0 이상이어야 합니다.")
    return value


@dataclass
class Utterance:
    speaker: str
    content: str
    timestamp: Optional[str] = None


@dataclass
class Meeting:
    meeting_id: str
    title: str
    date: str
    participants: list[str]
    utterances: list[Utterance]


class BaseTranscriber(ABC):
    @abstractmethod
    def load(self, source: str) -> Meeting:
        pass


class FileTranscriber(BaseTranscriber):
    def load(self, source: str) -> Meeting:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"transcript 파일을 찾을 수 없습니다: {source}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if "utterances" in data:
            return self._load_legacy(data)
        elif "segments" in data:
            return self._load_new(data, path.stem)
        else:
            raise ValueError(f"지원하지 않는 transcript 형식입니다: {source}")

    def _load_legacy(self, data: dict) -> Meeting:
        utterances = [
            Utterance(
                speaker=u["speaker"],
                content=u["content"],
                timestamp=u["timestamp"],
            )
            for u in data["utterances"]
        ]
        return Meeting(
            meeting_id=data["meeting_id"],
            title=data["title"],
            date=data["date"],
            participants=data["participants"],
            utterances=utterances,
        )

    def _load_new(self, data: dict, stem: str) -> Meeting:
        meeting_id = "meet_" + hashlib.sha256(stem.encode()).hexdigest()[:12]
        utterances = [
            Utterance(
                speaker=s["speaker"],
                content=s["text"],
            )
            for s in data["segments"]
        ]
        return Meeting(
            meeting_id=meeting_id,
            title=stem,
            date=str(date.today()),
            participants=[sp["name"] for sp in data["speakers"]],
            utterances=utterances,
        )


class WhisperTranscriber(BaseTranscriber):
    """음성 파일(mp3/wav 등) → WhisperX STT + pyannote 화자 분리 → Meeting 객체."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        expected_speaker_count: Optional[int] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.model_size = model_size
        self.device = device
        self.progress_callback = progress_callback
        self.expected_speaker_count = normalize_expected_speaker_count(
            expected_speaker_count
        )

    def _notify(self, message: str) -> None:
        print(f"[WhisperTranscriber] {message}")
        if self.progress_callback:
            self.progress_callback(message)

    def load(self, source: str) -> Meeting:
        try:
            import whisperx
        except ImportError:
            raise ImportError(
                "whisperx가 설치되지 않았습니다. "
                "pip install -r requirements-whisperx.txt 를 실행하세요."
            )

        from src.config import HUGGINGFACE_TOKEN
        if not HUGGINGFACE_TOKEN:
            raise EnvironmentError(
                "HUGGINGFACE_TOKEN이 설정되지 않았습니다. .env 파일을 확인하세요."
            )

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"음성 파일을 찾을 수 없습니다: {source}")

        self._notify(f"모델 로드 중 ({self.model_size})")
        model = whisperx.load_model(self.model_size, self.device, compute_type="int8")
        self._notify("오디오 로드 중")
        audio = whisperx.load_audio(str(path))

        self._notify("음성 인식 중")
        result = model.transcribe(audio, batch_size=8)
        language = result.get("language", "ko")
        self._notify(f"음성 인식 완료: {len(result.get('segments', []))}개 구간")

        self._notify("단어 정렬 모델 로드 중")
        model_a, metadata = whisperx.load_align_model(
            language_code=language, device=self.device
        )
        self._notify("단어 정렬 중")
        result = whisperx.align(
            result["segments"], model_a, metadata, audio, self.device,
            return_char_alignments=False,
        )

        self._notify("화자 분리 모델 로드 중")
        from whisperx.diarize import DiarizationPipeline
        diarize_model = DiarizationPipeline(
            token=HUGGINGFACE_TOKEN, device=self.device
        )
        diarize_kwargs = {}
        if self.expected_speaker_count is not None:
            diarize_kwargs = {
                "min_speakers": self.expected_speaker_count,
                "max_speakers": self.expected_speaker_count,
            }
            self._notify(f"예상 화자 수 고정: {self.expected_speaker_count}명")
        self._notify("화자 분리 중")
        diarize_segments = diarize_model(audio, **diarize_kwargs)
        self._notify("단어별 화자 라벨 매핑 중")
        result = whisperx.assign_word_speakers(diarize_segments, result)

        # Meeting 객체로 변환
        stem = path.stem
        meeting_id = "meet_" + hashlib.sha256(stem.encode()).hexdigest()[:12]

        utterances = []
        for seg in result["segments"]:
            speaker = seg.get("speaker", "SPEAKER_00")
            content = seg.get("text", "").strip()
            if not content:
                continue
            utterances.append(Utterance(
                speaker=speaker,
                content=content,
                timestamp=str(round(seg.get("start", 0), 2)),
            ))

        participants = sorted(set(u.speaker for u in utterances))
        self._notify(f"완료: {len(utterances)}개 발화, 화자 {len(participants)}명")

        return Meeting(
            meeting_id=meeting_id,
            title=stem,
            date=str(date.today()),
            participants=participants,
            utterances=utterances,
        )
