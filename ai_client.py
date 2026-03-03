import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import cast

from faster_whisper import WhisperModel
from llama_cpp import ChatCompletionRequestMessage, Llama


def _detect_audio_format(audio_data: bytes) -> str:
    """Detect audio format from magic bytes.

    Returns file extension like '.webm' or '.wav'.
    """
    start = audio_data[:4]
    match start:
        case b"\x1a\x45\xdf\xa3":
            return ".webm"
        case b"RIFF":
            return ".wav"
        case _:
            raise ValueError("Unknown audio format")


class AIClient(ABC):
    @abstractmethod
    def convert_speech_to_text(self, audio_data: bytes) -> str:
        pass

    @abstractmethod
    def clean_note(self, note: str, context: str = "") -> str:
        pass

    @abstractmethod
    def process_audio(
        self, audio_data: bytes, mode: str, note_context: str = ""
    ) -> dict[str, str]:
        pass


def _load_glossary() -> str:
    glossary_path = os.environ.get("GLOSSARY_PATH")
    if not glossary_path:
        return ""
    path = Path(glossary_path)
    if not path.exists():
        return ""
    return path.read_text().strip()


class LocalAIClient(AIClient):
    def __init__(
        self,
        model_path: str,
        whisper_model: str = "base.en",
    ):
        self.whisper = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        self.llm = Llama(model_path=model_path, n_ctx=2048)
        self.glossary = _load_glossary()

    def convert_speech_to_text(self, audio_data: bytes) -> str:
        suffix = _detect_audio_format(audio_data)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_data)
            f.flush()
            segments, _ = self.whisper.transcribe(f.name)
            return " ".join(segment.text.strip() for segment in segments)

    def text_prompt(self, prompt: str, system: str | None = None) -> str:
        messages: list[ChatCompletionRequestMessage] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self.llm.create_chat_completion(
            messages=messages,
            stream=False,
        )
        return cast(str, response["choices"][0]["message"]["content"])  # type: ignore

    def clean_note(self, note: str, context: str = "") -> str:
        system = (
            "You are a transcript editor. The user is dictating into an existing note. "
            "Use the note's context to correctly spell names, terms, and references. "
            "Output only the corrected new paragraph. "
            "Do not add explanations, quotes, or commentary."
        )
        if self.glossary:
            system += f"\n\nKnown vocabulary:\n{self.glossary}"
        if context.strip():
            prompt = (
                f"Existing note:\n{context}\n\n"
                f"New transcript to clean up:\n{note}"
            )
        else:
            prompt = f"Fix grammar, spelling, and missing words:\n{note}"
        return self.text_prompt(prompt, system=system)

    def process_audio(
        self, audio_data: bytes, mode: str, note_context: str = ""
    ) -> dict[str, str]:
        match mode:
            case "note":
                transcript = self.convert_speech_to_text(audio_data)
                result = self.clean_note(transcript, context=note_context)
                return {"transcript": transcript, "result": result}
            case _:
                raise ValueError(f"Unknown mode: {mode}")
