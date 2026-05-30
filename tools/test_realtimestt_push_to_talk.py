import torch
from RealtimeSTT import AudioToTextRecorder


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"RealtimeSTT device={device}")
    recorder = AudioToTextRecorder(
        model="tiny",
        language="en",
        device=device,
        spinner=False,
    )
    try:
        print("REALTIME_STT_INIT_OK")
    finally:
        recorder.shutdown()


if __name__ == "__main__":
    main()
