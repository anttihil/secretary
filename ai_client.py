import tempfile
from abc import ABC, abstractmethod
from typing import cast

from faster_whisper import WhisperModel
from llama_cpp import Llama


def _detect_audio_format(audio_data: bytes) -> str:
    """Detect audio format from magic bytes.

    Returns file extension like '.webm' or '.wav'.
    """
    # TODO(human): Check the first few bytes of audio_data to detect the format.
    # Magic bytes to look for:
    #   - WebM/Matroska: starts with b'\x1a\x45\xdf\xa3'  (EBML header)
    #   - WAV/RIFF:      starts with b'RIFF'
    # Use audio_data[:4] to get the first 4 bytes, then compare with
    # startswith() or == to determine the format.
    # Return ".webm" for WebM, ".wav" for WAV.
    # Raise ValueError("Unknown audio format") if neither matches.
    # Hint: Python match/case works with bytes too!
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
    def process_audio(self, audio_data: bytes, mode: str) -> str:
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

    def text_prompt(self, prompt: str) -> str:
        # TODO(human): Call self.llm.create_chat_completion() with a messages
        # list containing a single user message (role="user", content=prompt).
        # The method returns a dict with the chat completion response.
        # Extract the assistant's reply text from:
        #   response["choices"][0]["message"]["content"]
        # Return that text string.

        response = self.llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        return cast(str, response["choices"][0]["message"]["content"])  # type: ignore

    def clean_note(self, note: str) -> str:
        # TODO(human): Write a prompt string that asks the LLM to clean up
        # a raw audio transcript — fix grammar, spelling, and missing words.
        # Tell it to return only the cleaned text, nothing else.
        # Then call self.text_prompt() with your prompt and return the result.
        # Hint: use an f-string to embed `note` in your prompt.
        prompt = f"""
        Clean up this raw audio transcript: fix grammar, spelling, and missing words: 
        <transcript>{note}</transcript>
        """
        return self.text_prompt(prompt)

    def process_audio(self, audio_data: bytes, mode: str) -> str:
        # TODO(human): Use match/case to handle the mode parameter:
        #   "note"    -> transcribe with convert_speech_to_text(), then clean
        #               with clean_note(), return the cleaned text
        #   "command" -> transcribe with convert_speech_to_text(), then pass
        #               the text to text_prompt(), return the LLM response
        #   _         -> raise ValueError(f"Unknown mode: {mode}")
        # Look at AWSAIClient.process_audio() for a reference implementation.
        match mode:
            case "note":
                note = self.convert_speech_to_text(audio_data)
                cleaned_note = self.clean_note(note)
                return cleaned_note
            case "command":
                text = self.convert_speech_to_text(audio_data)
                return self.text_prompt(text)
            case _:
                raise ValueError(f"Unknown mode: {mode}")
