import json
import os
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from typing import Any, cast

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
    def recognize_command(
        self,
        transcript: str,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    def process_audio(
        self,
        audio_data: bytes,
        mode: str,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
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

    def recognize_command(
        self,
        transcript: str,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        titles = existing_titles or []
        titles_str = ", ".join(f'"{t}"' for t in titles) if titles else "None"

        system = (
            "You are an AI assistant for a note-taking app. "
            "Parse the user's spoken voice command into a JSON object.\n"
            "Respond ONLY with valid JSON, with no markdown code blocks "
            "or commentary.\n"
            "Supported actions:\n"
            '1. "add_tags": User wants to add tags. '
            'JSON: {"action": "add_tags", "tags": ["python", "coding"]}\n'
            '2. "add_links": User wants to add links to existing notes. '
            'JSON: {"action": "add_links", "links": ["Matched Note Title"]}\n'
            '3. "create_note": User wants to create/make a note. '
            'JSON: {"action": "create_note", "title": "Grocery List"}\n'
            '4. "append_text": General dictation/text. '
            'JSON: {"action": "append_text", "text": "cleaned content"}\n\n'
            f"Available note titles in workspace: [{titles_str}]\n"
        )
        if note_context.strip():
            system += f"Current note content:\n{note_context.strip()}\n"

        prompt = f"User voice transcript: {transcript}"
        raw_response = self.text_prompt(prompt, system=system).strip()

        if "```" in raw_response:
            lines = raw_response.splitlines()
            code_lines = []
            in_code = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    code_lines.append(line)
            raw_response = "\n".join(code_lines).strip()

        try:
            parsed = json.loads(raw_response)
            if isinstance(parsed, dict) and "action" in parsed:
                if parsed["action"] == "add_links" and "links" in parsed and titles:
                    matched_links = []
                    for link in parsed["links"]:
                        link_clean = str(link).strip().lower()
                        best = next(
                            (t for t in titles if t.lower() == link_clean), None
                        )
                        if not best:
                            best = next(
                                (
                                    t
                                    for t in titles
                                    if link_clean in t.lower()
                                    or t.lower() in link_clean
                                ),
                                str(link),
                            )
                        matched_links.append(best)
                    parsed["links"] = matched_links
                return parsed
        except Exception:
            pass

        return {"action": "append_text", "text": transcript}

    def process_audio(
        self,
        audio_data: bytes,
        mode: str,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        match mode:
            case "note":
                transcript = self.convert_speech_to_text(audio_data)
                return {"transcript": transcript, "result": transcript}
            case "command":
                transcript = self.convert_speech_to_text(audio_data)
                cmd = self.recognize_command(
                    transcript,
                    note_context=note_context,
                    existing_titles=existing_titles,
                )
                return {
                    "transcript": transcript,
                    "action": cmd.get("action", "append_text"),
                    "command": cmd,
                    "result": cmd.get("text") or transcript,
                }
            case _:
                raise ValueError(f"Unknown mode: {mode}")
