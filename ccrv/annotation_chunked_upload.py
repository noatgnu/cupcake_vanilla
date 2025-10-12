"""
Chunked upload views for CCRV annotations with automatic binding.
"""


from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ccc.annotation_chunked_upload import (
    AnnotationChunkedUploadView,
    AnnotationFileUpload,
    AnnotationFileUploadSerializer,
)
from ccc.models import AnnotationFolder

from .models import ProtocolStep, Session, SessionAnnotationFolder, StepAnnotation


class StepAnnotationChunkedUploadView(AnnotationChunkedUploadView):
    """
    Chunked upload view for step annotations with automatic binding.

    Accepts session_id and step_id, uploads file, creates Annotation,
    and automatically creates StepAnnotation junction record.
    """

    model = AnnotationFileUpload
    serializer_class = AnnotationFileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def on_completion(self, uploaded_file, request):
        """
        Handle completion and automatically create step annotation junction.
        """
        try:
            session_id = request.data.get("session_id")
            step_id = request.data.get("step_id")
            annotation_text = request.data.get("annotation", "")
            annotation_type = request.data.get(
                "annotation_type",
                self._detect_annotation_type(uploaded_file.filename),
            )
            folder_id = request.data.get("folder_id")

            if not session_id:
                return Response(
                    {"error": "session_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not step_id:
                return Response(
                    {"error": "step_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                session = Session.objects.get(id=session_id)
            except Session.DoesNotExist:
                return Response(
                    {"error": "Session not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not session.can_edit(request.user):
                return Response(
                    {"error": "Permission denied: cannot edit this session"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            try:
                step = ProtocolStep.objects.get(id=step_id)
            except ProtocolStep.DoesNotExist:
                return Response(
                    {"error": "Step not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            folder = None
            if folder_id:
                try:
                    folder = AnnotationFolder.objects.get(id=folder_id, owner=request.user)
                except AnnotationFolder.DoesNotExist:
                    pass

            annotation = self._create_annotation_from_upload(
                uploaded_file,
                annotation_text,
                annotation_type,
                folder,
                request.user,
            )

            order = StepAnnotation.objects.filter(session=session, step=step).count()

            step_annotation = StepAnnotation.objects.create(
                session=session,
                step=step,
                annotation=annotation,
                order=order,
            )

            result = {
                "annotation_id": annotation.id,
                "step_annotation_id": step_annotation.id,
                "message": "Step annotation created successfully",
            }
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create step annotation: {str(e)}")
            result = {"warning": f"File uploaded but annotation creation failed: {str(e)}"}
            return Response(result, status=status.HTTP_200_OK)


class SessionAnnotationFolderChunkedUploadView(AnnotationChunkedUploadView):
    """
    Chunked upload view for session annotation folders with automatic binding.

    Accepts session_id and folder_id, uploads file, creates Annotation,
    and automatically creates SessionAnnotationFolder junction record.
    """

    model = AnnotationFileUpload
    serializer_class = AnnotationFileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def on_completion(self, uploaded_file, request):
        """
        Handle completion and automatically create session annotation folder junction.
        """
        try:
            session_id = request.data.get("session_id")
            folder_id = request.data.get("folder_id")
            annotation_text = request.data.get("annotation", "")
            annotation_type = request.data.get(
                "annotation_type",
                self._detect_annotation_type(uploaded_file.filename),
            )

            if not session_id:
                return Response(
                    {"error": "session_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not folder_id:
                return Response(
                    {"error": "folder_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                session = Session.objects.get(id=session_id)
            except Session.DoesNotExist:
                return Response(
                    {"error": "Session not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not session.can_edit(request.user):
                return Response(
                    {"error": "Permission denied: cannot edit this session"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            try:
                folder = AnnotationFolder.objects.get(id=folder_id, owner=request.user)
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Folder not found or access denied"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            annotation = self._create_annotation_from_upload(
                uploaded_file,
                annotation_text,
                annotation_type,
                folder,
                request.user,
            )

            order = SessionAnnotationFolder.objects.filter(session=session, folder=folder).count()

            session_annotation_folder = SessionAnnotationFolder.objects.create(
                session=session,
                folder=folder,
                order=order,
            )

            result = {
                "annotation_id": annotation.id,
                "session_annotation_folder_id": session_annotation_folder.id,
                "message": "Session annotation folder created successfully",
            }
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create session annotation folder: {str(e)}")
            result = {"warning": f"File uploaded but annotation creation failed: {str(e)}"}
            return Response(result, status=status.HTTP_200_OK)
