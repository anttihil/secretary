import base64
import gzip
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ai_client import LocalAIClient
from aws_client import AWSAIClient


class DictationTests(unittest.TestCase):
    def test_local_transcription_consumes_later_windows_and_logs_audio_coverage(self):
        client = LocalAIClient.__new__(LocalAIClient)
        client.whisper = Mock()

        def segments():
            yield SimpleNamespace(text=" Beginning of recording. ", end=4.0)
            yield SimpleNamespace(text=" Middle after a pause. ", end=65.0)
            yield SimpleNamespace(text=" Final sentence. ", end=94.5)

        client.whisper.transcribe.return_value = (
            segments(),
            SimpleNamespace(duration=100.0, duration_after_vad=42.0),
        )
        with self.assertLogs("secretary.ai", level="INFO") as logs:
            result = client.process_audio(b"full recording")
        self.assertEqual(
            result["transcript"],
            "Beginning of recording. Middle after a pause. Final sentence.",
        )
        self.assertEqual(result["result"], result["transcript"])
        self.assertEqual(
            client.whisper.transcribe.call_args.args[0].getvalue(), b"full recording"
        )
        self.assertIn("audio_duration_s=100.000", logs.output[-1])
        self.assertIn("speech_duration_s=42.000", logs.output[-1])
        self.assertIn("segment_count=3", logs.output[-1])
        self.assertIn("last_segment_end_s=94.500", logs.output[-1])

    def test_local_dictation_preserves_instruction_like_text_without_llm(self):
        client = LocalAIClient.__new__(LocalAIClient)
        client.convert_speech_to_text = Mock(
            return_value="Create a note called Groceries and add tags shopping"
        )
        client.text_prompt = Mock()
        result = client.process_audio(b"audio")
        self.assertEqual(result["result"], client.convert_speech_to_text.return_value)
        self.assertEqual(result["transcript"], result["result"])
        client.text_prompt.assert_not_called()

    def test_aws_dictation_uses_transcript_and_ignores_intent(self):
        client = AWSAIClient.__new__(AWSAIClient)
        client.bot_id = "bot"
        client.bot_alias_id = "alias"
        client.locale_id = "en_US"
        text = "Create a note called Groceries"
        client.lex_runtime = Mock()
        client.lex_runtime.recognize_utterance.return_value = {
            "inputTranscript": base64.b64encode(gzip.compress(text.encode())).decode(),
            "sessionState": {"intent": {"name": "CreateNote"}},
        }
        with patch("aws_client._convert_to_pcm16_16k", return_value=b"pcm"):
            result = client.process_audio(b"audio")
        self.assertEqual(result, {"transcript": text, "result": text})
        client.lex_runtime.recognize_utterance.assert_called_once()


if __name__ == "__main__":
    unittest.main()
