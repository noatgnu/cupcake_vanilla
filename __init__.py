"""
CUPCAKE Core - Comprehensive scientific metadata management platform.

CUPCAKE combines user management, lab group collaboration, and
scientific metadata management in a unified Django package.

This package includes:
- CUPCAKE Core (CCC): User management, lab groups, and site administration
- CUPCAKE Vanilla (CCV): Scientific metadata management and SDRF compliance
"""

import ccc
import ccv

__version__ = "1.0.0"
__author__ = "Toan Phung"
__email__ = "toan.phung@proteo.info"
__description__ = "CUPCAKE - Comprehensive platform for scientific metadata management"
__url__ = "https://github.com/noatgnu/cupcake_vanilla"

# Package information
__title__ = "cupcake-core"
__license__ = "MIT"
__copyright__ = "Copyright 2024 Toan Phung"

# Version information for subpackages
__ccc_version__ = ccc.__version__
__ccv_version__ = ccv.__version__

# Expose main components
from ccc.models import (
    AbstractResource,
    AccountMergeRequest,
    LabGroup,
    LabGroupInvitation,
    ResourcePermission,
    ResourceRole,
    ResourceType,
    ResourceVisibility,
    SiteConfig,
    UserOrcidProfile,
)
from ccv.models import (  # Base classes for extension; Concrete implementations
    BaseMetadataTable,
    BaseMetadataTableTemplate,
    HumanDisease,
    MetadataColumn,
    MetadataColumnTemplate,
    MetadataTable,
    MetadataTableTemplate,
    SamplePool,
    Schema,
    Species,
    SubcellularLocation,
    Tissue,
)

__all__ = [
    # CCC models
    "LabGroup",
    "LabGroupInvitation",
    "SiteConfig",
    "UserOrcidProfile",
    "AccountMergeRequest",
    "AbstractResource",
    "ResourcePermission",
    "ResourceVisibility",
    "ResourceRole",
    "ResourceType",
    # CCV base models for extension
    "BaseMetadataTable",
    "BaseMetadataTableTemplate",
    # CCV concrete models
    "MetadataTable",
    "MetadataColumn",
    "MetadataTableTemplate",
    "MetadataColumnTemplate",
    "SamplePool",
    "Schema",
    "Species",
    "Tissue",
    "HumanDisease",
    "SubcellularLocation",
    # Version info
    "__version__",
    "__ccc_version__",
    "__ccv_version__",
]
