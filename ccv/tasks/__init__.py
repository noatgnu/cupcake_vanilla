"""
Task-related functions and utilities for CUPCAKE Vanilla.

This package contains all the task-related functionality including:
- Export task utilities
- Import task utilities
- Bulk operation utilities
- Task execution functions
- Base task classes and decorators
- Task utility functions
"""

from .base_task import BaseTaskExecutor, save_file_result, task_with_tracking

# Import all task functions to maintain compatibility
from .export_tasks import (
    export_excel_template_task,
    export_multiple_excel_template_task,
    export_multiple_sdrf_task,
    export_sdrf_task,
)
from .import_tasks import import_excel_task, import_sdrf_task

# Import task utilities and base classes
from .task_utils import create_error_result, get_user_and_table, mark_task_failure, mark_task_started, mark_task_success
from .validation_tasks import validate_metadata_table_task

__all__ = [
    # Task functions
    "export_excel_template_task",
    "export_sdrf_task",
    "export_multiple_sdrf_task",
    "export_multiple_excel_template_task",
    "import_sdrf_task",
    "import_excel_task",
    "validate_metadata_table_task",
    # Task utilities
    "mark_task_started",
    "mark_task_success",
    "mark_task_failure",
    "get_user_and_table",
    "create_error_result",
    # Base task classes and decorators
    "task_with_tracking",
    "save_file_result",
    "BaseTaskExecutor",
]
