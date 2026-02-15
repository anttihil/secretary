import json
import tempfile
import time
import uuid
from abc import ABC, abstractmethod

from faster_whisper import WhisperModel
from llama_cpp import Llama


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
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
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
        
        response = self.llm.create_chat_completion(messages=[{"role":"user", "content":prompt}])
        return response["choices"][0]["message"]["content"]

    def clean_note(self, note: str) -> str:
        # TODO(human): Write a prompt string that asks the LLM to clean up
        # a raw audio transcript — fix grammar, spelling, and missing words.
        # Tell it to return only the cleaned text, nothing else.
        # Then call self.text_prompt() with your prompt and return the result.
        # Hint: use an f-string to embed `note` in your prompt.
        prompt = f'Clean up this raw audio transcript: fix grammar, spelling, and missing words: <transcript>{note}</transcript>'
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

class AWSAIClient(AIClient):
    def __init__(
        self,
        local_path: str,
        s3_bucket: str,
        model_id: str = "anthropic.claude-3-haiku-20240307-v1:0",
    ):
        import boto3
        from botocore.config import Config

        self.bedrock_runtime = boto3.client(
            service_name="bedrock-runtime",
            region_name="us-east-1",
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )
        self.transcribe = boto3.client("transcribe", region_name="us-east-1")
        self.s3 = boto3.client("s3", region_name="us-east-1")
        self.s3_bucket = s3_bucket
        self.model_id = model_id
        self.local_path = local_path

    def convert_speech_to_text(self, audio_data: bytes) -> str:
        job_name = f"transcribe-{uuid.uuid4()}"
        s3_key = f"audio/{job_name}.wav"

        local_path = f"{self.local_path}/{job_name}.wav"
        with open(local_path, "wb") as f:
            f.write(audio_data)

        # Upload audio to S3
        self.s3.put_object(Bucket=self.s3_bucket, Key=s3_key, Body=audio_data)
        s3_uri = f"s3://{self.s3_bucket}/{s3_key}"

        # Start transcription job
        self.transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": s3_uri},
            MediaFormat="wav",
            LanguageCode="en-US",
        )

        # Poll for completion
        while True:
            response = self.transcribe.get_transcription_job(
                TranscriptionJobName=job_name
            )
            status = response["TranscriptionJob"]["TranscriptionJobStatus"]
            if status == "COMPLETED":
                break
            elif status == "FAILED":
                raise Exception("Transcription job failed")
            time.sleep(1)

        # Get transcript from result URL
        transcript_uri = response["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]

        # Fetch transcript JSON from the URI
        import urllib.request

        with urllib.request.urlopen(transcript_uri) as resp:
            transcript_data = json.loads(resp.read().decode())

        # Clean up S3
        self.s3.delete_object(Bucket=self.s3_bucket, Key=s3_key)

        return transcript_data["results"]["transcripts"][0]["transcript"]

    def text_prompt(self, prompt: str) -> str:
        response = self.bedrock_runtime.converse(
            modelId=self.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
        )
        return response["output"]["message"]["content"][0]["text"]

    def clean_note(self, note: str) -> str:
        cleaned_note = self.text_prompt(
            f"Clean this audio transcript for any grammatical errors, "
            f"spelling mistakes, and missing words. "
            f"Return only the cleaned text: {note}"
        )
        return cleaned_note

    def process_audio(self, audio_data: bytes, mode: str) -> str:
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
