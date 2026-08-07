import os
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import cast

from faster_whisper import WhisperModel
from llama_cpp import ChatCompletionRequestMessage, Llama


def get_whisper_capabilities() -> dict:
    import ctranslate2

    return {"cuda_available": ctranslate2.get_cuda_device_count() > 0}


class AIClient(ABC):
    @abstractmethod
    def reload_glossary(self):
        pass

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


def _load_glossary(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text().strip()


class LocalAIClient(AIClient):
    def __init__(
        self,
        model_path: str,
        whisper_model: str = "base.en",
        glossary_path: Path | None = None,
    ):
        self.whisper_device = os.environ.get("WHISPER_DEVICE", "cpu")
        self.whisper_compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "auto")
        self.whisper_model = whisper_model
        llm_gpu_layers = int(os.environ.get("LLM_GPU_LAYERS", "0"))

        self.whisper = WhisperModel(
            whisper_model,
            device=self.whisper_device,
            compute_type=self.whisper_compute_type,
        )
        self.llm = Llama(model_path=model_path, n_gpu_layers=llm_gpu_layers, n_ctx=2048)
        self.glossary_path = glossary_path or Path("glossary.txt")
        self.glossary = _load_glossary(self.glossary_path)

    def get_current_whisper_settings(self) -> dict[str, str]:
        return {
            "whisper_device": self.whisper_device,
            "whisper_compute_type": self.whisper_compute_type,
            "whisper_model": self.whisper_model,
        }

    def update_whisper(self, device: str, compute_type: str, model: str) -> None:
        new_whisper = WhisperModel(model, device=device, compute_type=compute_type)
        self.whisper = new_whisper
        self.whisper_device = device
        self.whisper_compute_type = compute_type
        self.whisper_model = model

    def reload_glossary(self):
        self.glossary = _load_glossary(self.glossary_path)

    def convert_speech_to_text(self, audio_data: bytes) -> str:
        if not audio_data:
            raise ValueError("No audio data")
        # faster-whisper decodes through PyAV, which sniffs the container
        # itself, so any format ffmpeg understands works here.
        segments, _ = self.whisper.transcribe(BytesIO(audio_data), vad_filter=True)
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
            prompt = f"Existing note:\n{context}\n\nNew transcript to clean up:\n{note}"
        else:
            prompt = f"Fix grammar, spelling, and missing words:\n{note}"
        return self.text_prompt(prompt, system=system)

    def process_audio(
        self, audio_data: bytes, mode: str, note_context: str = ""
    ) -> dict[str, str]:
        match mode:
            case "note":
                transcript = self.convert_speech_to_text(audio_data)
                return {"transcript": transcript, "result": transcript}
            case _:
                raise ValueError(f"Unknown mode: {mode}")
