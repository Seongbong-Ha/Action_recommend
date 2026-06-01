import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


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
