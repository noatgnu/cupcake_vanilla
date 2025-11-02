"""
Transcription and translation tasks using whisper.cpp for CCM.
"""

import logging
import os
import subprocess

from django.conf import settings

from django_rq import job

from ccc.models import Annotation
from ccm.notification_service import ccm_notification_service

logger = logging.getLogger(__name__)

print("=== TRANSCRIBE DEBUG: transcribe_tasks.py module loaded with DEBUG logging ===")
print(f"=== TRANSCRIBE DEBUG: Module file: {__file__} ===")


@job("transcribe", timeout="1h")
def transcribe_audio(
    audio_path: str,
    model_path: str,
    annotation_id: int,
    language: str = "auto",
    translate: bool = False,
    custom_id: str = None,
):
    """
    Transcribe audio file using whisper.cpp.

    Args:
        audio_path: Path to the audio file
        model_path: Path to whisper.cpp model file
        annotation_id: Annotation ID to update with transcription
        language: Language code (e.g., "en", "es", "auto")
        translate: If True, translate to English
        custom_id: Custom task identifier
    """
    print(f"=== TRANSCRIBE DEBUG: Starting transcription for {audio_path}")
    logger.info(f"Starting transcription for {audio_path}")

    annotation = Annotation.objects.get(id=annotation_id)

    ccm_notification_service.transcription_started(user_id=annotation.owner.id, annotation_id=annotation_id)

    try:
        print("=== TRANSCRIBE DEBUG: Entered try block")
        logger.info("DEBUG: Entered try block")
        if audio_path.endswith(".webm"):
            wav_path = audio_path.replace(".webm", ".wav")
        elif audio_path.endswith(".m4a"):
            wav_path = audio_path.replace(".m4a", ".wav")
        else:
            wav_path = audio_path + ".wav"

        print(f"=== TRANSCRIBE DEBUG: Converting audio to WAV: {audio_path} -> {wav_path}")
        logger.info(f"Converting audio to WAV: {audio_path} -> {wav_path}")
        subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-vn", "-ar", "16000", wav_path])

        whispercpp_bin_path = settings.WHISPERCPP_PATH
        temporary_vtt_path = wav_path + ".vtt"
        thread_count = settings.WHISPERCPP_THREAD_COUNT

        print("=== TRANSCRIBE DEBUG: About to run whisper.cpp")
        logger.info(f"Running whisper.cpp: {whispercpp_bin_path} -m {model_path} -f {wav_path}")

        cmd = [
            "stdbuf",
            "-oL",
            whispercpp_bin_path,
            "-m",
            model_path,
            "-f",
            wav_path,
            "-t",
            str(thread_count),
            "-ovtt",
        ]

        if language != "auto":
            cmd.extend(["-l", language])

        if translate:
            cmd.append("--translate")

        print(f"=== TRANSCRIBE DEBUG: Executing whisper command: {' '.join(cmd)}")
        logger.info(f"Executing whisper command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(f"=== TRANSCRIBE DEBUG: Whisper completed with return code: {result.returncode}")
        print(f"=== TRANSCRIBE DEBUG: Whisper stdout: {result.stdout[:500]}")
        print(f"=== TRANSCRIBE DEBUG: Whisper stderr: {result.stderr[:500]}")
        logger.info(f"Whisper stdout: {result.stdout[:500]}")
        logger.info(f"Whisper stderr: {result.stderr[:500]}")
        logger.info(f"Whisper return code: {result.returncode}")

        if result.returncode != 0:
            print(f"=== TRANSCRIBE DEBUG: Whisper FAILED with code {result.returncode}")
            raise Exception(f"Whisper.cpp failed with return code {result.returncode}: {result.stderr}")

        print("=== TRANSCRIBE DEBUG: Whisper.cpp completed successfully, reading VTT file")
        logger.info("Whisper.cpp completed successfully")

        print(f"=== TRANSCRIBE DEBUG: Reading VTT from {temporary_vtt_path}")
        with open(temporary_vtt_path, "r", encoding="utf-8") as f:
            vtt_content = f.read()

        print(f"=== TRANSCRIBE DEBUG: VTT content length: {len(vtt_content)}")
        detected_language = language if language != "auto" else "en"
        if "detected language:" in result.stderr.lower():
            for line in result.stderr.split("\n"):
                if "detected language:" in line.lower():
                    detected_language = line.split(":")[-1].strip().split()[0]
                    break

        annotation.transcription = vtt_content
        annotation.transcribed = True
        annotation.language = detected_language

        if translate and detected_language != "en":
            annotation.translation = vtt_content

        annotation.save()

        os.remove(temporary_vtt_path)
        logger.info(f"Transcription completed for {audio_path}")

        ccm_notification_service.transcription_completed(
            user_id=annotation.owner.id,
            annotation_id=annotation_id,
            language=detected_language,
            has_translation=translate and detected_language != "en",
        )

        logger.info("DEBUG: About to return success result from transcribe_audio")
        return {
            "status": "success",
            "annotation_id": annotation_id,
            "language": detected_language,
            "has_translation": translate and detected_language != "en",
        }

    except Exception as e:
        logger.error(f"Transcription failed for {audio_path}: {str(e)}", exc_info=True)
        ccm_notification_service.transcription_failed(
            user_id=annotation.owner.id, annotation_id=annotation_id, error=str(e)
        )
        raise


@job("transcribe", timeout="1h")
def transcribe_audio_from_video(
    video_path: str,
    model_path: str,
    annotation_id: int,
    language: str = "auto",
    translate: bool = False,
    custom_id: str = None,
):
    """
    Extract and transcribe audio from video file using whisper.cpp.

    Args:
        video_path: Path to the video file
        model_path: Path to whisper.cpp model file
        annotation_id: Annotation ID to update with transcription
        language: Language code (e.g., "en", "es", "auto")
        translate: If True, translate to English
        custom_id: Custom task identifier
    """
    logger.info(f"Starting video transcription for {video_path}")

    annotation = Annotation.objects.get(id=annotation_id)

    ccm_notification_service.transcription_started(user_id=annotation.owner.id, annotation_id=annotation_id)

    try:
        if video_path.endswith(".webm"):
            wav_path = video_path.replace(".webm", ".wav")
        elif video_path.endswith(".mp4"):
            wav_path = video_path.replace(".mp4", ".wav")
        else:
            wav_path = video_path + ".wav"

        logger.info(f"Converting video to WAV: {video_path} -> {wav_path}")
        subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", wav_path])

        whispercpp_bin_path = settings.WHISPERCPP_PATH
        temporary_vtt_path = wav_path + ".vtt"
        thread_count = settings.WHISPERCPP_THREAD_COUNT

        logger.info(f"Running whisper.cpp: {whispercpp_bin_path} -m {model_path} -f {wav_path}")

        cmd = [
            "stdbuf",
            "-oL",
            whispercpp_bin_path,
            "-m",
            model_path,
            "-f",
            wav_path,
            "-t",
            str(thread_count),
            "-ovtt",
        ]

        if language != "auto":
            cmd.extend(["-l", language])

        if translate:
            cmd.append("--translate")

        logger.info(f"Executing whisper command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.info(f"Whisper stdout: {result.stdout[:500]}")
        logger.info(f"Whisper stderr: {result.stderr[:500]}")
        logger.info(f"Whisper return code: {result.returncode}")

        if result.returncode != 0:
            print(f"=== TRANSCRIBE DEBUG: Whisper FAILED with code {result.returncode}")
            raise Exception(f"Whisper.cpp failed with return code {result.returncode}: {result.stderr}")

        print("=== TRANSCRIBE DEBUG: Whisper.cpp completed successfully, reading VTT file")
        logger.info("Whisper.cpp completed successfully")

        print(f"=== TRANSCRIBE DEBUG: Reading VTT from {temporary_vtt_path}")
        with open(temporary_vtt_path, "r", encoding="utf-8") as f:
            vtt_content = f.read()

        print(f"=== TRANSCRIBE DEBUG: VTT content length: {len(vtt_content)}")
        detected_language = language if language != "auto" else "en"
        if "detected language:" in result.stderr.lower():
            for line in result.stderr.split("\n"):
                if "detected language:" in line.lower():
                    detected_language = line.split(":")[-1].strip().split()[0]
                    break

        annotation.transcription = vtt_content
        annotation.transcribed = True
        annotation.language = detected_language

        if translate and detected_language != "en":
            annotation.translation = vtt_content

        annotation.save()

        os.remove(temporary_vtt_path)
        logger.info(f"Video transcription completed for {video_path}")

        ccm_notification_service.transcription_completed(
            user_id=annotation.owner.id,
            annotation_id=annotation_id,
            language=detected_language,
            has_translation=translate and detected_language != "en",
        )

        return {
            "status": "success",
            "annotation_id": annotation_id,
            "language": detected_language,
            "has_translation": translate,
        }

    except Exception as e:
        logger.error(f"Video transcription failed for {video_path}: {str(e)}")
        ccm_notification_service.transcription_failed(
            user_id=annotation.owner.id, annotation_id=annotation_id, error=str(e)
        )
        raise
