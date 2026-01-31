import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ai_client import AWSAIClient

app = FastAPI()

# Initialize AI client - requires S3_BUCKET environment variable
ai_client = AWSAIClient(s3_bucket=os.environ.get("S3_BUCKET", "your-bucket-name"))


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
