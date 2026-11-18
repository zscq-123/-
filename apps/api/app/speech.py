"""Short, local Mandarin transcription on an opt-in demo installation."""
import array
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_AUDIO_SECONDS = 35
AUDIO_FORMATS = {
    'audio/webm': 'matroska',
    'audio/ogg': 'ogg',
    'audio/mp4': 'mov',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
}
_job = threading.BoundedSemaphore(1)


class SpeechError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def local_engine():
    model = os.environ.get('SPEECH_MODEL_PATH', '').strip()
    if not model or not Path(model).is_file():
        return None
    ffmpeg = shutil.which('ffmpeg')
    whisper = shutil.which('whisper-cli')
    return (model, ffmpeg, whisper) if ffmpeg and whisper else None


def has_speech_level(wav: Path) -> bool:
    with wave.open(str(wav), 'rb') as audio:
        # Check short windows so pauses don't hide quiet speech. Clip-level
        # energy is only a silence check, not a measure of recognizer accuracy.
        while chunk := audio.readframes(320):
            samples = array.array('h', chunk)
            if samples and sum(sample * sample for sample in samples) > len(samples) * 105**2:
                return True
    return False


def transcribe(recording: bytes, content_type: str) -> str:
    demuxer = AUDIO_FORMATS.get(content_type.split(';', 1)[0].strip().lower())
    if not demuxer:
        raise SpeechError(415, '此浏览器的录音格式暂不支持，请改用文字。')
    if not recording or len(recording) > MAX_AUDIO_BYTES:
        raise SpeechError(413, '录音为空或太长，请说一小段后停止。')
    engine = local_engine()
    if not engine:
        raise SpeechError(503, '本地语音转写服务暂不可用，请改用文字。')
    if not _job.acquire(blocking=False):
        raise SpeechError(429, '语音转写正在处理另一段录音，请稍后重试。')
    try:
        model, ffmpeg, whisper = engine
        with tempfile.TemporaryDirectory(prefix='legal-aid-speech-') as temp:
            directory = Path(temp)
            wav = directory / 'speech.wav'
            decoded = subprocess.run(
                [ffmpeg, '-nostdin', '-loglevel', 'error', '-protocol_whitelist', 'pipe',
                 '-f', demuxer, '-i', 'pipe:0', '-map', '0:a:0', '-vn', '-t', str(MAX_AUDIO_SECONDS),
                 '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)],
                input=recording, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6,
            )
            if decoded.returncode != 0 or not wav.is_file():
                raise SpeechError(422, '未能读取这段录音，请重录或改用文字。')
            if not has_speech_level(wav):
                raise SpeechError(422, '这段录音没有听到清晰的声音，请靠近麦克风重试。')
            output = directory / 'transcript'
            result = subprocess.run(
                [whisper, '-m', model, '-f', str(wav), '-l', 'zh', '-t', '4', '-nt', '-np',
                 '-otxt', '-of', str(output), '--prompt', '这是一段普通话对话。'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=22,
            )
            text_file = output.with_suffix('.txt')
            if result.returncode != 0 or not text_file.is_file():
                raise SpeechError(503, '本地语音转写没有完成，请重试或改用文字。')
            text = text_file.read_text(encoding='utf-8').strip()
            if not text:
                raise SpeechError(422, '没有得到可用的转写，请重试或改用文字。')
            return text[:4000]
    except subprocess.TimeoutExpired:
        raise SpeechError(504, '语音处理超时，请重试或改用文字。') from None
    except (OSError, ValueError, EOFError, wave.Error):
        raise SpeechError(503, '本地语音转写暂不可用，请改用文字。') from None
    finally:
        _job.release()
