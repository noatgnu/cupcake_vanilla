"""
Chunked upload views for CCM annotations with automatic binding.
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

from .models import (
    Instrument,
    InstrumentAnnotation,
    MaintenanceLog,
    MaintenanceLogAnnotation,
    StoredReagent,
    StoredReagentAnnotation,
)


class InstrumentAnnotationChunkedUploadView(AnnotationChunkedUploadView):
    """
    Chunked upload view for instrument annotations with automatic binding.

    Accepts instrument_id and folder_id, uploads file, creates Annotation,
    and automatically creates InstrumentAnnotation junction record.
    """

    model = AnnotationFileUpload
    serializer_class = AnnotationFileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def on_completion(self, uploaded_file, request):
        """
        Handle completion and automatically create instrument annotation junction.
        """
        try:
            instrument_id = request.data.get("instrument_id")
            folder_id = request.data.get("folder_id")
            annotation_text = request.data.get("annotation", "")
            annotation_type = request.data.get(
                "annotation_type",
                self._detect_annotation_type(uploaded_file.filename),
            )

            if not instrument_id:
                return Response(
                    {"error": "instrument_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not folder_id:
                return Response(
                    {"error": "folder_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                instrument = Instrument.objects.get(id=instrument_id)
            except Instrument.DoesNotExist:
                return Response(
                    {"error": "Instrument not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            try:
                folder = AnnotationFolder.objects.get(id=folder_id)
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Folder not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if folder.folder_name not in ["Manuals", "Certificates", "Maintenance"]:
                return Response(
                    {"error": f"Folder must be one of: Manuals, Certificates, Maintenance. Got: {folder.folder_name}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if folder.folder_name == "Maintenance" and not request.user.is_staff:
                return Response(
                    {"error": "Permission denied: only staff can upload to Maintenance folder"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if not instrument.user_can_manage(request.user):
                return Response(
                    {"error": "Permission denied: cannot manage this instrument"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            annotation = self._create_annotation_from_upload(
                uploaded_file,
                annotation_text,
                annotation_type,
                folder,
                request.user,
            )

            order = InstrumentAnnotation.objects.filter(instrument=instrument, folder=folder).count()

            instrument_annotation = InstrumentAnnotation.objects.create(
                instrument=instrument,
                annotation=annotation,
                folder=folder,
                order=order,
            )

            result = {
                "annotation_id": annotation.id,
                "instrument_annotation_id": instrument_annotation.id,
                "message": "Instrument annotation created successfully",
            }
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create instrument annotation: {str(e)}")
            result = {"warning": f"File uploaded but annotation creation failed: {str(e)}"}
            return Response(result, status=status.HTTP_200_OK)


class StoredReagentAnnotationChunkedUploadView(AnnotationChunkedUploadView):
    """
    Chunked upload view for stored reagent annotations with automatic binding.

    Accepts stored_reagent_id and folder_id, uploads file, creates Annotation,
    and automatically creates StoredReagentAnnotation junction record.
    """

    model = AnnotationFileUpload
    serializer_class = AnnotationFileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def on_completion(self, uploaded_file, request):
        """
        Handle completion and automatically create stored reagent annotation junction.
        """
        try:
            stored_reagent_id = request.data.get("stored_reagent_id")
            folder_id = request.data.get("folder_id")
            annotation_text = request.data.get("annotation", "")
            annotation_type = request.data.get(
                "annotation_type",
                self._detect_annotation_type(uploaded_file.filename),
            )

            if not stored_reagent_id:
                return Response(
                    {"error": "stored_reagent_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not folder_id:
                return Response(
                    {"error": "folder_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                stored_reagent = StoredReagent.objects.get(id=stored_reagent_id)
            except StoredReagent.DoesNotExist:
                return Response(
                    {"error": "StoredReagent not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if stored_reagent.user != request.user and not (request.user.is_staff or request.user.is_superuser):
                return Response(
                    {"error": "Permission denied: cannot manage this stored reagent"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            try:
                folder = AnnotationFolder.objects.get(id=folder_id)
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Folder not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if folder.folder_name not in ["MSDS", "Certificates", "Manuals"]:
                return Response(
                    {"error": f"Folder must be one of: MSDS, Certificates, Manuals. Got: {folder.folder_name}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            annotation = self._create_annotation_from_upload(
                uploaded_file,
                annotation_text,
                annotation_type,
                folder,
                request.user,
            )

            order = StoredReagentAnnotation.objects.filter(stored_reagent=stored_reagent, folder=folder).count()

            stored_reagent_annotation = StoredReagentAnnotation.objects.create(
                stored_reagent=stored_reagent,
                annotation=annotation,
                folder=folder,
                order=order,
            )

            result = {
                "annotation_id": annotation.id,
                "stored_reagent_annotation_id": stored_reagent_annotation.id,
                "message": "Stored reagent annotation created successfully",
            }
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create stored reagent annotation: {str(e)}")
            result = {"warning": f"File uploaded but annotation creation failed: {str(e)}"}
            return Response(result, status=status.HTTP_200_OK)


class MaintenanceLogAnnotationChunkedUploadView(AnnotationChunkedUploadView):
    """
    Chunked upload view for maintenance log annotations with automatic binding.

    Accepts maintenance_log_id, uploads file, creates Annotation,
    and automatically creates MaintenanceLogAnnotation junction record.
    """

    model = AnnotationFileUpload
    serializer_class = AnnotationFileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def on_completion(self, uploaded_file, request):
        """
        Handle completion and automatically create maintenance log annotation junction.
        """
        try:
            maintenance_log_id = request.data.get("maintenance_log_id")
            annotation_text = request.data.get("annotation", "")
            annotation_type = request.data.get(
                "annotation_type",
                self._detect_annotation_type(uploaded_file.filename),
            )

            if not maintenance_log_id:
                return Response(
                    {"error": "maintenance_log_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                maintenance_log = MaintenanceLog.objects.get(id=maintenance_log_id)
            except MaintenanceLog.DoesNotExist:
                return Response(
                    {"error": "Maintenance log not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not maintenance_log.user_can_edit(request.user):
                return Response(
                    {"error": "Permission denied: cannot edit this maintenance log"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            annotation = self._create_annotation_from_upload(
                uploaded_file,
                annotation_text,
                annotation_type,
                None,
                request.user,
            )

            order = MaintenanceLogAnnotation.objects.filter(maintenance_log=maintenance_log).count()

            maintenance_log_annotation = MaintenanceLogAnnotation.objects.create(
                maintenance_log=maintenance_log,
                annotation=annotation,
                order=order,
            )

            result = {
                "annotation_id": annotation.id,
                "maintenance_log_annotation_id": maintenance_log_annotation.id,
                "message": "Maintenance log annotation created successfully",
            }
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create maintenance log annotation: {str(e)}")
            result = {"warning": f"File uploaded but annotation creation failed: {str(e)}"}
            return Response(result, status=status.HTTP_200_OK)
