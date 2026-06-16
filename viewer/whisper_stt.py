#!/usr/bin/env python3
"""
faster-whisper STT CLI wrapper for OpenClaw tools.media.audio
Usage: whisper-stt.py <audio_file>

Supports: wav, mp3, m4a, ogg, flac, webm
Outputs: transcribed text to stdout
"""
import sys
import json

def main():
    if len(sys.argv) < 2:
        print("Usage: whisper-stt.py <audio_file>", file=sys.stderr)
        sys.exit(1)
    
    audio_path = sys.argv[1]
    
    try:
        from faster_whisper import WhisperModel
        
        # Use tiny.en model for speed, CPU-friendly
        model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        
        segments, info = model.transcribe(
            audio_path,
            language="en",
            beam_size=5,
            vad_filter=True,  # voice activity detection
        )
        
        # Collect full transcript
        transcript_parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                transcript_parts.append(text)
        
        full_transcript = " ".join(transcript_parts)
        print(full_transcript, end="")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()