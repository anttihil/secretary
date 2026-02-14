import os  # noqa: F401

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ai_client import AIClient, AWSAIClient, LocalAIClient  # noqa: F401


def create_ai_client() -> AIClient:
    # TODO(human): Read the AI_CLIENT env var (default to "local").
    # Use match/case to return the right client:
    #   "local" -> read LLM_MODEL_PATH (required) and WHISPER_MODEL
    #              (default "base.en") from env vars, return LocalAIClient(...)
    #   "aws"   -> read S3_BUCKET (required) from env var,
    #              return AWSAIClient(local_path=".", s3_bucket=...)
    #   _       -> raise ValueError with the unknown client type
    # Hint: use os.environ[] for required vars (raises KeyError if missing)
    # and os.environ.get("VAR", "default") for optional ones.
    raise NotImplementedError("Fill in create_ai_client()")


app = FastAPI()
ai_client = create_ai_client()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    recording: bool = False
    chunks: list[bytes] = []
    mode: str = ""

    try:
        while True:
            message = await websocket.receive()
            if "text" in message:
                data = message["text"]
                match data:
                    case "close":
                        await websocket.close()
                        break
                    case "note":
                        if recording:
                            continue
                        recording = True
                        mode = "note"
                        chunks = []
                        await websocket.send_text("Recording started (note mode)")
                    case "command":
                        if recording:
                            continue
                        recording = True
                        mode = "command"
                        chunks = []
                        await websocket.send_text("Recording started (command mode)")
                    case "stop":
                        if not recording:
                            continue
                        recording = False
                        audio_data = b"".join(chunks)
                        await websocket.send_text("Processing audio...")
                        result = ai_client.process_audio(audio_data, mode)
                        await websocket.send_text(result)
                        chunks = []
                        mode = ""
                    case _:
                        await websocket.send_text(f"Unknown command: {data}")
            elif "bytes" in message:
                data = message["bytes"]
                if recording:
                    chunks.append(data)

    except WebSocketDisconnect:
        pass


@app.post("/note")
def post_note():
    return {"Hello": "World"}


def main():
    print("Hello from secretary!")


if __name__ == "__main__":
    main()
