import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Utterance:
    speaker: str
    content: str
    timestamp: str


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
