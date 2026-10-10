import base64
import gzip
import io
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, cast

import av
import av.audio.resampler
import av.container

from ai_client import AIClient

logger = logging.getLogger("secretary.aws")


def _convert_to_pcm16_16k(audio_data: bytes) -> bytes:
    """Resample/convert arbitrary audio (WebM, WAV, etc.) to 16kHz mono 16-bit PCM."""
    input_container = cast(av.container.InputContainer, av.open(io.BytesIO(audio_data)))
    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=16000,
    )
    output_pcm = io.BytesIO()
    for frame in input_container.decode(audio=0):
        for resampled_frame in resampler.resample(frame):
            output_pcm.write(resampled_frame.to_ndarray().tobytes())
    for resampled_frame in resampler.resample(None):
        output_pcm.write(resampled_frame.to_ndarray().tobytes())
    return output_pcm.getvalue()


def _decode_transcript(value: str | bytes | None) -> str:
    """Decode the base64/gzip transcript returned by recognize_utterance."""
    if not value:
        return ""
    try:
        raw_bytes = base64.b64decode(value) if isinstance(value, str) else value
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except (OSError, EOFError):
            pass
        return raw_bytes.decode("utf-8")
    except Exception as e:
        logger.debug("Transcript decode failed, returning raw value: %s", e)
        return value if isinstance(value, str) else value.decode("utf-8")


class AWSAIClient(AIClient):
    def __init__(
        self,
        local_path: str = "/tmp",
        bot_id: str | None = None,
        bot_alias_id: str | None = None,
        bot_name: str = "SecretaryBot",
        bot_version: str = "DRAFT",
        locale_id: str = "en_US",
        region_name: str = "us-east-1",
        role_arn: str | None = None,
        glossary_path: Path | None = None,
        auto_create_bot: bool = True,
    ):
        import boto3

        self.region_name = region_name or os.environ.get(
            "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )
        self.bot_name = bot_name or os.environ.get("LEX_BOT_NAME", "SecretaryBot")
        self.bot_id = bot_id or os.environ.get("LEX_BOT_ID")
        self.bot_alias_id = bot_alias_id or os.environ.get("LEX_BOT_ALIAS_ID")
        self.bot_version = bot_version or os.environ.get("LEX_BOT_VERSION", "DRAFT")
        self.locale_id = locale_id or os.environ.get("LEX_LOCALE_ID", "en_US")
        self.role_arn = role_arn or os.environ.get("LEX_ROLE_ARN")
        self.local_path = local_path
        self.glossary_path = glossary_path

        self.lex_runtime = boto3.client("lexv2-runtime", region_name=self.region_name)
        self.lex_models = boto3.client("lexv2-models", region_name=self.region_name)
        self.iam = boto3.client("iam", region_name=self.region_name)
        self.sts = boto3.client("sts", region_name=self.region_name)

        if auto_create_bot:
            try:
                self._ensure_bot_exists()
            except Exception as e:
                logger.warning(
                    "Auto bot provisioning check encountered an error: %s", e
                )

        logger.info(
            "Initialized AWSAIClient (bot_id=%s, bot_alias_id=%s, "
            "locale_id=%s, region=%s)",
            self.bot_id,
            self.bot_alias_id,
            self.locale_id,
            self.region_name,
        )

    def _get_or_create_lex_role_arn(self) -> str:
        if self.role_arn:
            return self.role_arn

        try:
            account_id = self.sts.get_caller_identity()["Account"]
            service_role_name = "AWSServiceRoleForLexV2Bots"
            service_role_arn = (
                f"arn:aws:iam::{account_id}:role/aws-service-role/"
                f"lexv2.amazonaws.com/{service_role_name}"
            )
            try:
                self.iam.get_role(RoleName=service_role_name)
                self.role_arn = service_role_arn
                return service_role_arn
            except self.iam.exceptions.NoSuchEntityException:
                pass

            try:
                logger.info(
                    "Creating Lex V2 service-linked role AWSServiceRoleForLexV2Bots..."
                )
                resp = self.iam.create_service_linked_role(
                    AWSServiceName="lexv2.amazonaws.com"
                )
                created_arn = resp["Role"]["Arn"]
                self.role_arn = created_arn
                return created_arn
            except Exception as slr_err:
                logger.debug(
                    "Could not create service-linked role directly (%s), "
                    "using default service role ARN",
                    slr_err,
                )
                self.role_arn = service_role_arn
                return service_role_arn
        except Exception as e:
            logger.warning("Could not determine IAM role ARN for Lex: %s", e)
            raise

    def _ensure_bot_exists(self) -> None:
        if self.bot_id:
            try:
                self.lex_models.describe_bot(botId=self.bot_id)
                if not self.bot_alias_id:
                    self.bot_alias_id = "TSTALIASID"
                logger.info(
                    "Found existing configured Lex bot (bot_id=%s)", self.bot_id
                )
                return
            except Exception:
                logger.info(
                    "Configured bot_id=%s not found; searching by name...",
                    self.bot_id,
                )

        try:
            paginator = self.lex_models.get_paginator("list_bots")
            for page in paginator.paginate():
                for bot in page.get("botSummaries", []):
                    if bot.get("botName") == self.bot_name:
                        self.bot_id = bot["botId"]
                        if not self.bot_alias_id:
                            self.bot_alias_id = "TSTALIASID"
                        logger.info(
                            "Found existing Lex bot by name %r (bot_id=%s)",
                            self.bot_name,
                            self.bot_id,
                        )
                        return
        except Exception as e:
            logger.warning("Failed to list existing bots: %s", e)

        logger.info("No Lex bot found named %r. Creating bot...", self.bot_name)
        role_arn = self._get_or_create_lex_role_arn()

        resp = self.lex_models.create_bot(
            botName=self.bot_name,
            description="Secretary Dictation Bot",
            roleArn=role_arn,
            dataPrivacy={"childDirected": False},
            idleSessionTTLInSeconds=300,
        )
        bot_id = resp["botId"]
        self.bot_id = bot_id
        self.bot_alias_id = "TSTALIASID"

        logger.info("Waiting for bot %s to become Available...", bot_id)
        while True:
            status = self.lex_models.describe_bot(botId=bot_id)["botStatus"]
            if status == "Available":
                break
            elif status == "Failed":
                raise RuntimeError(f"Lex bot creation failed for bot_id={bot_id}")
            time.sleep(2)

        logger.info("Creating bot locale %s for bot %s...", self.locale_id, bot_id)
        self.lex_models.create_bot_locale(
            botId=bot_id,
            botVersion="DRAFT",
            localeId=self.locale_id,
            nluIntentConfidenceThreshold=0.40,
        )

        while True:
            loc_status = self.lex_models.describe_bot_locale(
                botId=bot_id, botVersion="DRAFT", localeId=self.locale_id
            )["botLocaleStatus"]
            if loc_status in ("NotBuilt", "Built"):
                break
            elif loc_status in ("Failed", "Deleting"):
                raise RuntimeError(f"Bot locale creation failed: {loc_status}")
            time.sleep(1)

        # Lex needs a built locale for speech recognition; only provision dictation.
        utterances = [{"utterance": "dictate {Text}"}, {"utterance": "write {Text}"}]
        intent = self.lex_models.create_intent(
            botId=bot_id,
            botVersion="DRAFT",
            localeId=self.locale_id,
            intentName="Dictation",
            description="Transcribe dictated text",
            sampleUtterances=utterances,
        )
        intent_id = intent["intentId"]
        slot = self.lex_models.create_slot(
            botId=bot_id,
            botVersion="DRAFT",
            localeId=self.locale_id,
            intentId=intent_id,
            slotName="Text",
            slotTypeName="AMAZON.FreeFormInput",
            valueElicitationSetting={
                "slotConstraint": "Optional",
                "promptSpecification": {
                    "messageGroupsList": [
                        {
                            "message": {
                                "plainTextMessage": {
                                    "value": "What text would you like to dictate?"
                                }
                            }
                        }
                    ],
                    "maxRetries": 2,
                },
            },
        )
        self.lex_models.update_intent(
            botId=bot_id,
            botVersion="DRAFT",
            localeId=self.locale_id,
            intentId=intent_id,
            intentName="Dictation",
            description="Transcribe dictated text",
            sampleUtterances=utterances,
            slotPriorities=[{"priority": 1, "slotId": slot["slotId"]}],
        )

        logger.info("Building bot locale %s for bot %s...", self.locale_id, bot_id)
        self.lex_models.build_bot_locale(
            botId=bot_id, botVersion="DRAFT", localeId=self.locale_id
        )
        while True:
            status = self.lex_models.describe_bot_locale(
                botId=bot_id, botVersion="DRAFT", localeId=self.locale_id
            )["botLocaleStatus"]
            if status == "Built":
                logger.info(
                    "Bot locale %s built successfully for bot %s!",
                    self.locale_id,
                    bot_id,
                )
                break
            elif status == "Failed":
                raise RuntimeError(f"Bot locale build failed for bot_id={bot_id}")
            time.sleep(2)

    def reload_glossary(self):
        if not self.glossary_path or not self.glossary_path.exists():
            logger.debug("No glossary file found at %s", self.glossary_path)
            return

        content = self.glossary_path.read_text().strip()
        if not content:
            return

        entries: list[dict[str, Any]] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if " → " in line:
                phrase, display_as = line.split(" → ", 1)
                entries.append(
                    {
                        "phrase": phrase.strip(),
                        "displayAs": display_as.strip(),
                        "weight": 3,
                    }
                )
            else:
                entries.append({"phrase": line, "weight": 3})

        if self.bot_id and entries:
            try:
                logger.info(
                    "Updating Lex custom vocabulary with %d items "
                    "(bot_id=%s, locale=%s)",
                    len(entries),
                    self.bot_id,
                    self.locale_id,
                )
                self.lex_models.batch_create_custom_vocabulary_item(
                    botId=self.bot_id,
                    botVersion=self.bot_version,
                    localeId=self.locale_id,
                    customVocabularyItemList=entries,
                )
                logger.info("Successfully updated Lex custom vocabulary")
            except Exception as e:
                logger.warning(
                    "Failed to update Lex custom vocabulary via lexv2-models: %s",
                    e,
                )

    def convert_speech_to_text(self, audio_data: bytes) -> str:
        if not audio_data:
            return ""

        pcm_bytes = _convert_to_pcm16_16k(audio_data)
        session_id = str(uuid.uuid4())

        logger.info(
            "Transcribing audio with Amazon Lex recognize_utterance "
            "(audio_bytes=%d, pcm_bytes=%d)",
            len(audio_data),
            len(pcm_bytes),
        )
        t0 = time.perf_counter()

        response = self.lex_runtime.recognize_utterance(
            botId=self.bot_id,
            botAliasId=self.bot_alias_id,
            localeId=self.locale_id,
            sessionId=session_id,
            requestContentType="audio/l16; rate=16000; channels=1",
            responseContentType="text/plain; charset=utf-8",
            inputStream=pcm_bytes,
        )
        duration_ms = (time.perf_counter() - t0) * 1000

        transcript = _decode_transcript(response.get("inputTranscript"))
        logger.info(
            "Amazon Lex transcription completed in %.1fms: transcript=%r",
            duration_ms,
            transcript,
        )
        return transcript

    def clean_note(self, note: str, context: str = "") -> str:
        logger.info(
            "Clean note requested on AWS (note_len=%d, has_context=%s)",
            len(note),
            bool(context.strip()),
        )
        return note
