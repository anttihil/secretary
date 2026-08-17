import json
import time
import uuid
from typing import Any

from ai_client import AIClient


def _detect_audio_format(audio_data: bytes) -> str:
    """Detect audio format from magic bytes.

    Returns a file extension like '.webm' or '.wav'. AWS Transcribe requires an
    explicit MediaFormat, so unlike the local path we cannot defer to a decoder.
    """
    match audio_data[:4]:
        case b"\x1a\x45\xdf\xa3":
            return ".webm"
        case b"RIFF":
            return ".wav"
        case _:
            raise ValueError("Unknown audio format")


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

    def reload_glossary(self):
        pass

    def convert_speech_to_text(self, audio_data: bytes) -> str:
        job_name = f"transcribe-{uuid.uuid4()}"
        fmt = _detect_audio_format(audio_data)
        ext = fmt.lstrip(".")
        s3_key = f"audio/{job_name}{fmt}"

        local_path = f"{self.local_path}/{job_name}{fmt}"
        with open(local_path, "wb") as f:
            f.write(audio_data)

        # Upload audio to S3
        self.s3.put_object(Bucket=self.s3_bucket, Key=s3_key, Body=audio_data)
        s3_uri = f"s3://{self.s3_bucket}/{s3_key}"

        # Start transcription job
        self.transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": s3_uri},
            MediaFormat=ext,
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

    def clean_note(self, note: str, context: str = "") -> str:
        cleaned_note = self.text_prompt(
            f"Clean this audio transcript for any grammatical errors, "
            f"spelling mistakes, and missing words. "
            f"Return only the cleaned text: {note}"
        )
        return cleaned_note

    def recognize_command(
        self,
        transcript: str,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        titles = existing_titles or []
        titles_str = ", ".join(f'"{t}"' for t in titles) if titles else "None"
        prompt = (
            "Parse the voice transcript into a JSON object matching an action:\n"
            '1. "add_tags": {"action": "add_tags", "tags": ["tag1", "tag2"]}\n'
            '2. "add_links": {"action": "add_links", "links": ["Matched Title"]}\n'
            '3. "create_note": {"action": "create_note", "title": "Title"}\n'
            '4. "append_text": {"action": "append_text", "text": "text"}\n\n'
            f"Available note titles: [{titles_str}]\n"
            f"Transcript: {transcript}\n"
            "Return ONLY raw JSON."
        )
        resp = self.text_prompt(prompt).strip()
        try:
            parsed = json.loads(resp)
            if isinstance(parsed, dict) and "action" in parsed:
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
