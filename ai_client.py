import tempfile
from abc import ABC, abstractmethod
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
    def text_prompt(self, prompt: str) -> str:
        pass

    @abstractmethod
    def clean_note(self, note: str) -> str:
        pass

    @abstractmethod
    def process_audio(self, audio_data: bytes, mode: str) -> dict[str, str]:
        pass


class LocalAIClient(AIClient):
    def __init__(
        self,
        model_path: str,
        whisper_model: str = "base.en",
    ):
        self.whisper = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        self.llm = Llama(model_path=model_path, n_ctx=2048)

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

    def clean_note(self, note: str) -> str:
        system = (
            "You are a transcript editor. Output only the corrected text. "
            "Do not add explanations, quotes, or commentary."
        )
        prompt = f"Fix grammar, spelling, and missing words:\n{note}"
        return self.text_prompt(prompt, system=system)

    def process_audio(self, audio_data: bytes, mode: str) -> dict[str, str]:
        match mode:
            case "note":
                transcript = self.convert_speech_to_text(audio_data)
                result = self.clean_note(transcript)
                return {"transcript": transcript, "result": result}
            case "command":
                transcript = self.convert_speech_to_text(audio_data)
                result = self.text_prompt(transcript)
                return {"transcript": transcript, "result": result}
            case _:
                raise ValueError(f"Unknown mode: {mode}")
