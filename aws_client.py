import json
import logging
import time
import uuid
from typing import Any

from ai_client import AIClient

logger = logging.getLogger("secretary.aws")


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

        logger.info(
            "Initializing AWSAIClient (s3_bucket=%s, model_id=%s)",
            s3_bucket,
            model_id,
        )
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

        logger.info(
            "Starting AWS Transcribe job %s (audio_bytes=%d, format=%s)",
            job_name,
            len(audio_data),
            ext,
        )
        t0 = time.perf_counter()

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

        transcript = transcript_data["results"]["transcripts"][0]["transcript"]
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "AWS Transcribe job %s completed in %.1fms: transcript=%r",
            job_name,
            duration_ms,
            transcript,
        )
        return transcript

    def text_prompt(self, prompt: str) -> str:
        logger.debug("AWS Bedrock prompt request (model=%s): %s", self.model_id, prompt)
        t0 = time.perf_counter()
        response = self.bedrock_runtime.converse(
            modelId=self.model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        result = response["output"]["message"]["content"][0]["text"]
        logger.debug("AWS Bedrock response received in %.1fms: %r", duration_ms, result)
        return result

    def clean_note(self, note: str, context: str = "") -> str:
        logger.info(
            "Clean note requested on AWS (note_len=%d, has_context=%s)",
            len(note),
            bool(context.strip()),
        )
        t0 = time.perf_counter()
        cleaned_note = self.text_prompt(
            f"Clean this audio transcript for any grammatical errors, "
            f"spelling mistakes, and missing words. "
            f"Return only the cleaned text: {note}"
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Clean note on AWS completed in %.1fms (output_len=%d):\n%s",
            duration_ms,
            len(cleaned_note),
            cleaned_note,
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
        logger.info(
            "Recognize command requested on AWS (transcript=%r, "
            "note_context_len=%d, titles_count=%d)",
            transcript,
            len(note_context),
            len(titles),
        )
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
        t0 = time.perf_counter()
        resp = self.text_prompt(prompt).strip()
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "Recognize command AWS LLM raw response (%.1fms):\n%s",
            duration_ms,
            resp,
        )

        clean_json_str = resp
        if "```" in resp:
            logger.debug(
                "Markdown code block detected in AWS LLM response. Stripping fences."
            )
            lines = resp.splitlines()
            code_lines = []
            in_code = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    code_lines.append(line)
            clean_json_str = "\n".join(code_lines).strip()

        try:
            parsed = json.loads(clean_json_str)
            if isinstance(parsed, dict) and "action" in parsed:
                logger.info(
                    "Recognize command successfully parsed JSON action=%r: %s",
                    parsed.get("action"),
                    parsed,
                )
                return parsed
            else:
                logger.warning(
                    "AWS LLM response parsed as JSON but missing 'action': %r",
                    parsed,
                )
        except Exception as e:
            logger.warning(
                "Failed to parse AWS LLM response as JSON: %s. Raw response was: %r",
                e,
                clean_json_str,
            )

        logger.info(
            "Falling back to action='append_text' with transcript=%r", transcript
        )
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
