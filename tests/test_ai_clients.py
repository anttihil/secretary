import base64
import gzip
import unittest
from unittest.mock import Mock, patch

from ai_client import LocalAIClient
from aws_client import AWSAIClient


class DictationTests(unittest.TestCase):
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
