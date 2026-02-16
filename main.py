import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ai_client import AIClient, LocalAIClient

# Load .env file for local development; in production, systemd provides env vars
if os.getenv("ENVIRONMENT") != "production":
    from dotenv import load_dotenv

    load_dotenv()


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
    client = os.environ.get("AI_CLIENT", "local")
    match client:
        case "local":
            model_path = os.environ["LLM_MODEL_PATH"]
            whisper_model = os.environ.get("WHISPER_MODEL", "base.en")
            return LocalAIClient(model_path, whisper_model)
        # case "aws":
        #    bucket = os.environ["S3_BUCKET"]
        #    return AWSAIClient(local_path=".", s3_bucket=bucket)
        case _:
            raise ValueError("Unknown client type")


app = FastAPI()
ai_client = create_ai_client()

# TODO(human): Serve the web frontend. Two things needed:
# 1. Mount the "static" directory so files in it are served under /static.
#    Use: app.mount("/static", StaticFiles(directory=...), name="static")
#    Hint: use Path(__file__).parent / "static" to get the directory path.
# 2. Add a GET route for "/" that returns static/index.html using FileResponse.
#    Hint: use the @app.get() decorator, and return FileResponse(path_to_file).
app.mount(
    "/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"
)


@app.get("/")
async def root():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


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
