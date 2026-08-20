import base64
import gzip
import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import av

from ai_client import AIClient

logger = logging.getLogger("secretary.aws")


def _convert_to_pcm16_16k(audio_data: bytes) -> bytes:
    """Resample/convert arbitrary audio (WebM, WAV, etc.) to 16kHz mono 16-bit PCM."""
    input_container = av.open(io.BytesIO(audio_data))
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


def _decode_lex_field(value: str | bytes | None, is_json: bool = True) -> Any:
    """Decode and decompress base64/gzip encoded fields from recognize_utterance."""
    if not value:
        return {} if is_json else ""
    if isinstance(value, (dict, list)):
        return value
    try:
        if isinstance(value, str):
            raw_bytes = base64.b64decode(value)
        else:
            raw_bytes = value
        try:
            decompressed = gzip.decompress(raw_bytes)
        except Exception:
            decompressed = raw_bytes
        if is_json:
            return json.loads(decompressed.decode("utf-8"))
        else:
            return decompressed.decode("utf-8")
    except Exception as e:
        logger.debug("Lex field decode failed, returning raw/fallback: %s", e)
        if is_json and isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return {}
        return value if not is_json else {}


def _extract_slot_values(slot: dict[str, Any] | None) -> list[str]:
    """Extract string values recursively from an Amazon Lex V2 slot structure."""
    if not slot or not isinstance(slot, dict):
        return []
    values: list[str] = []
    if "values" in slot and isinstance(slot["values"], list):
        for sub_slot in slot["values"]:
            values.extend(_extract_slot_values(sub_slot))
    if "value" in slot and isinstance(slot["value"], dict):
        val_dict = slot["value"]
        if "resolvedValues" in val_dict and val_dict["resolvedValues"]:
            for rv in val_dict["resolvedValues"]:
                if rv:
                    values.append(str(rv))
        elif val_dict.get("interpretedValue"):
            values.append(str(val_dict["interpretedValue"]))
        elif val_dict.get("originalValue"):
            values.append(str(val_dict["originalValue"]))
    return [v.strip() for v in values if v and v.strip()]


def _get_slot(slots: dict[str, Any] | None, *names: str) -> dict[str, Any] | None:
    """Find a slot by one or more candidate names (case-insensitive)."""
    if not slots:
        return None
    for name in names:
        for k, v in slots.items():
            if k.lower() == name.lower() and v is not None:
                return v
    return None


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
            description="Secretary Voice Command Bot",
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

        intents_config = [
            {
                "name": "AddTags",
                "description": "Tag a note",
                "slot_name": "Tags",
                "prompt": "What tags would you like to add?",
                "utterances": [
                    "add tags {Tags}",
                    "add tag {Tags}",
                    "tag as {Tags}",
                    "tag note {Tags}",
                    "tag this note {Tags}",
                    "tags {Tags}",
                    "tag {Tags}",
                    "set tags {Tags}",
                ],
            },
            {
                "name": "AddLinks",
                "description": "Link to an existing note",
                "slot_name": "Link",
                "prompt": "What note would you like to link?",
                "utterances": [
                    "add link {Link}",
                    "add links {Link}",
                    "link to {Link}",
                    "link note {Link}",
                    "link this to {Link}",
                    "link {Link}",
                    "add link to {Link}",
                ],
            },
            {
                "name": "CreateNote",
                "description": "Create a new note",
                "slot_name": "Title",
                "prompt": "What is the note title?",
                "utterances": [
                    "create note {Title}",
                    "create a note {Title}",
                    "create note titled {Title}",
                    "make note {Title}",
                    "make a note {Title}",
                    "new note {Title}",
                    "create new note {Title}",
                    "start note {Title}",
                ],
            },
            {
                "name": "AppendText",
                "description": "Append text or general dictation",
                "slot_name": "Text",
                "prompt": "What text would you like to append?",
                "utterances": [
                    "append {Text}",
                    "append text {Text}",
                    "add text {Text}",
                    "dictate {Text}",
                    "write {Text}",
                    "note {Text}",
                ],
            },
        ]

        for ic in intents_config:
            logger.info("Creating intent %s...", ic["name"])
            int_resp = self.lex_models.create_intent(
                botId=bot_id,
                botVersion="DRAFT",
                localeId=self.locale_id,
                intentName=ic["name"],
                description=ic["description"],
                sampleUtterances=[{"utterance": u} for u in ic["utterances"]],
            )
            intent_id = int_resp["intentId"]

            slot_resp = self.lex_models.create_slot(
                botId=bot_id,
                botVersion="DRAFT",
                localeId=self.locale_id,
                intentId=intent_id,
                slotName=ic["slot_name"],
                slotTypeName="AMAZON.FreeFormInput",
                valueElicitationSetting={
                    "slotConstraint": "Optional",
                    "promptSpecification": {
                        "messageGroupsList": [
                            {"message": {"plainTextMessage": {"value": ic["prompt"]}}}
                        ],
                        "maxRetries": 2,
                    },
                },
            )
            slot_id = slot_resp["slotId"]

            self.lex_models.update_intent(
                botId=bot_id,
                botVersion="DRAFT",
                localeId=self.locale_id,
                intentId=intent_id,
                intentName=ic["name"],
                description=ic["description"],
                sampleUtterances=[{"utterance": u} for u in ic["utterances"]],
                slotPriorities=[{"priority": 1, "slotId": slot_id}],
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

        transcript = _decode_lex_field(response.get("inputTranscript"), is_json=False)
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

    def _recognize_command_utterance(
        self,
        audio_data: bytes,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        titles = existing_titles or []
        session_id = str(uuid.uuid4())
        pcm_bytes = _convert_to_pcm16_16k(audio_data)

        logger.info(
            "Calling Lex recognize_utterance (bot_id=%s, alias_id=%s, "
            "raw_bytes=%d, pcm_bytes=%d, session_id=%s)",
            self.bot_id,
            self.bot_alias_id,
            len(audio_data),
            len(pcm_bytes),
            session_id,
        )
        t0 = time.perf_counter()

        kwargs: dict[str, Any] = {
            "botId": self.bot_id,
            "botAliasId": self.bot_alias_id,
            "localeId": self.locale_id,
            "sessionId": session_id,
            "requestContentType": "audio/l16; rate=16000; channels=1",
            "responseContentType": "text/plain; charset=utf-8",
            "inputStream": pcm_bytes,
        }
        if note_context:
            raw_session = json.dumps(
                {"sessionAttributes": {"note_context": note_context[:1000]}}
            )
            compressed = gzip.compress(raw_session.encode("utf-8"))
            kwargs["sessionState"] = base64.b64encode(compressed).decode("utf-8")

        response = self.lex_runtime.recognize_utterance(**kwargs)
        duration_ms = (time.perf_counter() - t0) * 1000

        input_transcript = _decode_lex_field(
            response.get("inputTranscript"), is_json=False
        )
        session_state = _decode_lex_field(response.get("sessionState"), is_json=True)
        interpretations = _decode_lex_field(
            response.get("interpretations"), is_json=True
        )

        logger.info(
            "Amazon Lex recognize_utterance completed in %.1fms (transcript=%r)",
            duration_ms,
            input_transcript,
        )

        intent = session_state.get("intent")
        if not intent and isinstance(interpretations, list) and interpretations:
            intent = interpretations[0].get("intent")

        if not intent:
            logger.info(
                "No intent detected in Lex response; falling back to append_text"
            )
            return {
                "action": "append_text",
                "text": input_transcript,
                "transcript": input_transcript,
            }

        intent_name = intent.get("name", "")
        slots = intent.get("slots") or {}
        normalized = (
            intent_name.lower().replace("_", "").replace("-", "").replace(" ", "")
        )
        logger.info(
            "Lex recognized intent=%r (normalized=%r) with slots=%r",
            intent_name,
            normalized,
            slots,
        )

        result: dict[str, Any] = {"transcript": input_transcript}

        if normalized in ("addtags", "addtag", "tags", "tag", "tagtarget"):
            raw_tags = _extract_slot_values(
                _get_slot(slots, "tags", "tag", "items", "values")
            )
            parsed_tags: list[str] = []
            for tag in raw_tags:
                cleaned = [
                    t.strip().lstrip("#")
                    for t in re.split(r",|\sand\s", tag)
                    if t.strip()
                ]
                parsed_tags.extend(cleaned)
            result.update({"action": "add_tags", "tags": parsed_tags or raw_tags})

        elif normalized in ("addlinks", "addlink", "links", "link", "linknote"):
            raw_links = _extract_slot_values(
                _get_slot(slots, "links", "link", "title", "notes", "target")
            )
            matched_links = []
            for link in raw_links:
                link_clean = str(link).strip().lower()
                best = next((t for t in titles if t.lower() == link_clean), None)
                if not best:
                    best = next(
                        (
                            t
                            for t in titles
                            if link_clean in t.lower() or t.lower() in link_clean
                        ),
                        str(link),
                    )
                matched_links.append(best)
            result.update({"action": "add_links", "links": matched_links})

        elif normalized in ("createnote", "newnote", "makenote", "addnote"):
            title_vals = _extract_slot_values(
                _get_slot(slots, "title", "name", "note_title", "topic", "subject")
            )
            title = title_vals[0] if title_vals else input_transcript
            result.update({"action": "create_note", "title": title})

        elif normalized in (
            "appendtext",
            "appendnote",
            "dictate",
            "dictation",
            "addtext",
        ):
            text_vals = _extract_slot_values(
                _get_slot(slots, "text", "content", "body", "note", "dictation")
            )
            text = text_vals[0] if text_vals else input_transcript
            result.update({"action": "append_text", "text": text})

        elif normalized in ("fallbackintent", "fallback"):
            logger.info("Lex returned FallbackIntent; defaulting to append_text")
            result.update({"action": "append_text", "text": input_transcript})

        else:
            logger.warning(
                "Unrecognized Lex intent: %r; defaulting to append_text",
                intent_name,
            )
            result.update({"action": "append_text", "text": input_transcript})

        return result

    def _recognize_command_lex(
        self,
        transcript: str,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        titles = existing_titles or []
        session_id = str(uuid.uuid4())
        logger.info(
            "Recognizing command with Amazon Lex text (bot_id=%s, alias_id=%s, "
            "transcript=%r, session_id=%s)",
            self.bot_id,
            self.bot_alias_id,
            transcript,
            session_id,
        )
        t0 = time.perf_counter()

        kwargs: dict[str, Any] = {
            "botId": self.bot_id,
            "botAliasId": self.bot_alias_id,
            "localeId": self.locale_id,
            "sessionId": session_id,
            "text": transcript,
        }
        if note_context:
            kwargs["sessionState"] = {
                "sessionAttributes": {
                    "note_context": note_context[:1000],
                }
            }

        response = self.lex_runtime.recognize_text(**kwargs)
        duration_ms = (time.perf_counter() - t0) * 1000
        logger.info("Amazon Lex response received in %.1fms: %s", duration_ms, response)

        session_state = response.get("sessionState") or {}
        intent = session_state.get("intent")
        if not intent:
            interpretations = response.get("interpretations") or []
            if interpretations:
                intent = interpretations[0].get("intent")

        if not intent:
            logger.info(
                "No intent detected in Lex response; falling back to append_text"
            )
            return {
                "action": "append_text",
                "text": transcript,
                "transcript": transcript,
            }

        intent_name = intent.get("name", "")
        slots = intent.get("slots") or {}
        normalized = (
            intent_name.lower().replace("_", "").replace("-", "").replace(" ", "")
        )
        logger.info(
            "Lex recognized intent=%r (normalized=%r) with slots=%r",
            intent_name,
            normalized,
            slots,
        )

        result: dict[str, Any] = {"transcript": transcript}

        if normalized in ("addtags", "addtag", "tags", "tag", "tagtarget"):
            raw_tags = _extract_slot_values(
                _get_slot(slots, "tags", "tag", "items", "values")
            )
            parsed_tags: list[str] = []
            for tag in raw_tags:
                cleaned = [
                    t.strip().lstrip("#")
                    for t in re.split(r",|\sand\s", tag)
                    if t.strip()
                ]
                parsed_tags.extend(cleaned)
            result.update({"action": "add_tags", "tags": parsed_tags or raw_tags})

        elif normalized in ("addlinks", "addlink", "links", "link", "linknote"):
            raw_links = _extract_slot_values(
                _get_slot(slots, "links", "link", "title", "notes", "target")
            )
            matched_links = []
            for link in raw_links:
                link_clean = str(link).strip().lower()
                best = next((t for t in titles if t.lower() == link_clean), None)
                if not best:
                    best = next(
                        (
                            t
                            for t in titles
                            if link_clean in t.lower() or t.lower() in link_clean
                        ),
                        str(link),
                    )
                matched_links.append(best)
            result.update({"action": "add_links", "links": matched_links})

        elif normalized in ("createnote", "newnote", "makenote", "addnote"):
            title_vals = _extract_slot_values(
                _get_slot(slots, "title", "name", "note_title", "topic", "subject")
            )
            title = title_vals[0] if title_vals else transcript
            result.update({"action": "create_note", "title": title})

        elif normalized in (
            "appendtext",
            "appendnote",
            "dictate",
            "dictation",
            "addtext",
        ):
            text_vals = _extract_slot_values(
                _get_slot(slots, "text", "content", "body", "note", "dictation")
            )
            text = text_vals[0] if text_vals else transcript
            result.update({"action": "append_text", "text": text})

        elif normalized in ("fallbackintent", "fallback"):
            logger.info("Lex returned FallbackIntent; defaulting to append_text")
            result.update({"action": "append_text", "text": transcript})

        else:
            logger.warning(
                "Unrecognized Lex intent: %r; defaulting to append_text",
                intent_name,
            )
            result.update({"action": "append_text", "text": transcript})

        return result

    def recognize_command(
        self,
        transcript_or_audio: str | bytes,
        note_context: str = "",
        existing_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.bot_id and self.bot_alias_id:
            try:
                if isinstance(transcript_or_audio, bytes):
                    return self._recognize_command_utterance(
                        transcript_or_audio,
                        note_context=note_context,
                        existing_titles=existing_titles,
                    )
                else:
                    return self._recognize_command_lex(
                        transcript_or_audio,
                        note_context=note_context,
                        existing_titles=existing_titles,
                    )
            except Exception as e:
                logger.warning(
                    "Lex command recognition failed (%s): %s",
                    type(e).__name__,
                    e,
                )
        else:
            logger.info(
                "Lex bot_id/bot_alias_id not configured; defaulting to append_text"
            )

        fallback_text = (
            transcript_or_audio if isinstance(transcript_or_audio, str) else ""
        )
        logger.info("Falling back to action='append_text' with text=%r", fallback_text)
        return {
            "action": "append_text",
            "text": fallback_text,
            "transcript": fallback_text,
        }

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
                cmd = self.recognize_command(
                    audio_data,
                    note_context=note_context,
                    existing_titles=existing_titles,
                )
                transcript = cmd.get("transcript") or ""
                return {
                    "transcript": transcript,
                    "action": cmd.get("action", "append_text"),
                    "command": cmd,
                    "result": cmd.get("text") or transcript,
                }
            case _:
                raise ValueError(f"Unknown mode: {mode}")
