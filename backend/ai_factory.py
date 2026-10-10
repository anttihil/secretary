"""Construct the configured local or AWS AI client."""

import os

from ai_client import AIClient, LocalAIClient
from backend import paths
from config import get_settings


def create_ai_client() -> AIClient:
    client = os.environ.get("AI_CLIENT", "local")
    settings = get_settings()
    match client:
        case "local":
            model_path = os.environ["LLM_MODEL_PATH"]
            os.environ["WHISPER_DEVICE"] = settings["whisper_device"]
            os.environ["WHISPER_COMPUTE_TYPE"] = settings["whisper_compute_type"]
            return LocalAIClient(
                model_path, settings["whisper_model"], paths.GLOSSARY_PATH
            )
        case "aws":
            from aws_client import AWSAIClient

            local_path = os.environ.get("LOCAL_AUDIO_PATH", str(paths.NOTES_DIR))
            return AWSAIClient(
                local_path=local_path,
                bot_id=os.environ.get("LEX_BOT_ID"),
                bot_alias_id=os.environ.get("LEX_BOT_ALIAS_ID"),
                bot_name=os.environ.get("LEX_BOT_NAME", "SecretaryBot"),
                bot_version=os.environ.get("LEX_BOT_VERSION", "DRAFT"),
                locale_id=os.environ.get("LEX_LOCALE_ID", "en_US"),
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
                role_arn=os.environ.get("LEX_ROLE_ARN"),
                glossary_path=paths.GLOSSARY_PATH,
            )
        case _:
            raise ValueError("Unknown client type")
