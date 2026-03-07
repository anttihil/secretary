import json
import time
import uuid

from ai_client import AIClient, _detect_audio_format


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
