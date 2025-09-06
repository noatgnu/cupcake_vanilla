#!/usr/bin/env python
"""
Quick test runner for auto-reorder functionality tests.
Run this to verify the auto-reorder tests work correctly.
"""

import os
import sys

import django

# Add project to path
sys.path.append(os.path.dirname(__file__))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cupcake_vanilla.settings")
django.setup()

# Run specific tests
if __name__ == "__main__":
    from django.conf import settings
    from django.test.utils import get_runner

    TestRunner = get_runner(settings)
    test_runner = TestRunner()

    # Run our auto-reorder tests
    failures = test_runner.run_tests(
        [
            "ccv.tests.test_auto_reorder_functionality.MetadataTableAutoReorderTest",
            "ccv.tests.test_auto_reorder_functionality.MetadataTableTemplateAutoReorderTest",
            "ccv.tests.test_auto_reorder_functionality.MetadataTableAutoReorderAPITest",
            "ccv.tests.test_auto_reorder_functionality.MetadataTableTemplateAutoReorderAPITest",
        ]
    )

    if failures:
        sys.exit(1)
    else:
        print("All auto-reorder tests passed!")
        sys.exit(0)
