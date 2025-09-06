"""
URL configuration for CUPCAKE Vanilla metadata API.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .async_views import (
    AsyncExportViewSet,
    AsyncImportViewSet,
    AsyncTaskViewSet,
    AsyncValidationViewSet,
    cleanup_expired_files,
)
from .chunked_upload import MetadataChunkedUploadView
from .viewsets import (
    CellOntologyViewSet,
    ChEBICompoundViewSet,
    FavouriteMetadataOptionViewSet,
    HumanDiseaseViewSet,
    MetadataColumnTemplateShareViewSet,
    MetadataColumnTemplateViewSet,
    MetadataColumnViewSet,
    MetadataManagementViewSet,
    MetadataTableTemplateViewSet,
    MetadataTableViewSet,
    MondoDiseaseViewSet,
    MSUniqueVocabulariesViewSet,
    NCBITaxonomyViewSet,
    OntologySearchViewSet,
    PSIMSOntologyViewSet,
    SamplePoolViewSet,
    SchemaViewSet,
    SDRFDefaultsViewSet,
    SpeciesViewSet,
    SubcellularLocationViewSet,
    TissueViewSet,
    UberonAnatomyViewSet,
    UnimodViewSet,
)

app_name = "ccv"

# Create router and register CCV ViewSets
router = DefaultRouter()
router.register(r"metadata-tables", MetadataTableViewSet, basename="metadatatable")
router.register(r"metadata-columns", MetadataColumnViewSet, basename="metadatacolumn")
router.register(r"sample-pools", SamplePoolViewSet, basename="samplepool")
router.register(r"metadata-table-templates", MetadataTableTemplateViewSet, basename="metadatatabletemplate")
router.register(r"favourite-options", FavouriteMetadataOptionViewSet, basename="favouritemetadata")
router.register(r"metadata-management", MetadataManagementViewSet, basename="metadatamanagement")
router.register(r"ontology/species", SpeciesViewSet, basename="species")
router.register(r"ontology/tissues", TissueViewSet, basename="tissue")
router.register(r"ontology/diseases", HumanDiseaseViewSet, basename="humandisease")
router.register(r"ontology/subcellular-locations", SubcellularLocationViewSet, basename="subcellularlocation")
router.register(r"ontology/ms-unique-vocabularies", MSUniqueVocabulariesViewSet, basename="msuniquevocabularies")
router.register(r"ontology/unimod", UnimodViewSet, basename="unimod")
router.register(r"column-templates", MetadataColumnTemplateViewSet, basename="metadatacolumntemplate")
router.register(r"template-shares", MetadataColumnTemplateShareViewSet, basename="metadatacolumntemplateShare")
router.register(r"ontology/mondo-diseases", MondoDiseaseViewSet, basename="mondodisease")
router.register(r"ontology/uberon-anatomy", UberonAnatomyViewSet, basename="uberonanatomy")
router.register(r"ontology/ncbi-taxonomy", NCBITaxonomyViewSet, basename="ncbitaxonomy")
router.register(r"ontology/chebi-compounds", ChEBICompoundViewSet, basename="chebicompound")
router.register(r"ontology/psims", PSIMSOntologyViewSet, basename="psimsontology")
router.register(r"ontology/cell-types", CellOntologyViewSet, basename="cellontology")
router.register(r"ontology/search", OntologySearchViewSet, basename="ontologysearch")
router.register(r"schemas", SchemaViewSet, basename="schema")
router.register(r"sdrf-defaults", SDRFDefaultsViewSet, basename="sdrfdefaults")

# Async task endpoints
router.register(r"async-tasks", AsyncTaskViewSet, basename="asynctask")
router.register(r"async-export", AsyncExportViewSet, basename="asyncexport")
router.register(r"async-import", AsyncImportViewSet, basename="asyncimport")
router.register(r"async-validation", AsyncValidationViewSet, basename="asyncvalidation")

urlpatterns = [
    # DRF ViewSet endpoints (api/v1/ prefix comes from main urls.py)
    path("", include(router.urls)),
    # Non-DRF chunked upload endpoints (api/v1/ prefix comes from main urls.py)
    path(
        "chunked-upload/",
        MetadataChunkedUploadView.as_view(),
        name="chunked-upload",
    ),
    path(
        "chunked-upload/<uuid:pk>/",
        MetadataChunkedUploadView.as_view(),
        name="chunked-upload-detail",
    ),
    # Admin endpoint for cleaning up expired files
    path(
        "cleanup-expired-files/",
        cleanup_expired_files,
        name="cleanup-expired-files",
    ),
]
