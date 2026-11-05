"""Audio and video annotations created through the annotation endpoint are queued for transcription."""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from rest_framework.test import APIRequestFactory, APITestCase

from ccc.serializers import AnnotationSerializer
from tests.factories import UserFactory


@override_settings(USE_WHISPER=True, ENABLE_CUPCAKE_RED_VELVET=True)
class AnnotationTranscriptionQueueTests(APITestCase):
    def create(self, annotation_type, filename):
        request = APIRequestFactory().post("/api/v1/annotations/")
        request.user = UserFactory.create_user(username=f"recorder_{annotation_type}")
        serializer = AnnotationSerializer(
            data={
                "annotation": "Recording",
                "annotation_type": annotation_type,
                "file": SimpleUploadedFile(filename, b"data"),
            },
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_audio_is_queued(self):
        with patch("ccrv.tasks.transcribe_tasks.transcribe_audio.delay") as queued:
            annotation = self.create("audio", "note.webm")
        queued.assert_called_once()
        self.assertEqual(queued.call_args.kwargs["annotation_id"], annotation.id)

    def test_video_is_queued(self):
        with patch("ccrv.tasks.transcribe_tasks.transcribe_audio_from_video.delay") as queued:
            annotation = self.create("video", "clip.mp4")
        queued.assert_called_once()
        self.assertEqual(queued.call_args.kwargs["annotation_id"], annotation.id)
