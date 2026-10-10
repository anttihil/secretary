import logging
import os
import time
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import cast

from faster_whisper import WhisperModel
from llama_cpp import ChatCompletionRequestMessage, Llama

logger = logging.getLogger("secretary.ai")


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

    def process_audio(self, audio_data: bytes) -> dict[str, str]:
        transcript = self.convert_speech_to_text(audio_data)
        return {"transcript": transcript, "result": transcript}


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

        logger.info(
            "Initializing LocalAIClient (model_path=%s, whisper_model=%s, "
            "device=%s, compute_type=%s, gpu_layers=%d)",
            model_path,
            whisper_model,
            self.whisper_device,
            self.whisper_compute_type,
            llm_gpu_layers,
        )
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
        logger.info(
            "Updating Whisper model to model=%s, device=%s, compute_type=%s",
            model,
            device,
            compute_type,
        )
        new_whisper = WhisperModel(model, device=device, compute_type=compute_type)
        self.whisper = new_whisper
        self.whisper_device = device
        self.whisper_compute_type = compute_type
        self.whisper_model = model

    def reload_glossary(self):
        self.glossary = _load_glossary(self.glossary_path)
        logger.info("Glossary reloaded (length=%d)", len(self.glossary))

    def convert_speech_to_text(self, audio_data: bytes) -> str:
        if not audio_data:
            raise ValueError("No audio data")
        t0 = time.perf_counter()
        # faster-whisper decodes through PyAV, which sniffs the container
        # itself, so any format ffmpeg understands works here.
        segments, _ = self.whisper.transcribe(BytesIO(audio_data), vad_filter=True)
        transcript = " ".join(segment.text.strip() for segment in segments)
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Speech to text completed in %.1fms (audio_bytes=%d, transcript=%r)",
            duration_ms,
            len(audio_data),
            transcript,
        )
        return transcript

    def text_prompt(self, prompt: str, system: str | None = None) -> str:
        messages: list[ChatCompletionRequestMessage] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        logger.debug("Local LLM text_prompt request: messages=%s", messages)
        t0 = time.perf_counter()
        response = self.llm.create_chat_completion(
            messages=messages,
            stream=False,
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        result = cast(str, response["choices"][0]["message"]["content"])  # type: ignore
        logger.debug("Local LLM text_prompt response (%.1fms): %r", duration_ms, result)
        return result

    def clean_note(self, note: str, context: str = "") -> str:
        logger.info(
            "Clean note requested (note_len=%d, has_context=%s)",
            len(note),
            bool(context.strip()),
        )
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

        t0 = time.perf_counter()
        cleaned = self.text_prompt(prompt, system=system)
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Clean note completed in %.1fms (output_len=%d):\n%s",
            duration_ms,
            len(cleaned),
            cleaned,
        )
        return cleaned
