"""
WebSocket URL pattern manager to prevent conflicts across applications.

This module provides utilities to collect, validate, and merge WebSocket URL patterns
from multiple Django applications while detecting and resolving conflicts.
"""

import importlib
import logging
import re
from typing import List, Optional, Tuple

from django.apps import apps
from django.urls import path

from channels.routing import URLRouter

logger = logging.getLogger(__name__)


class WebSocketPatternConflict(Exception):
    """Exception raised when WebSocket URL patterns conflict."""

    pass


class WebSocketUrlManager:
    """Manager for collecting and validating WebSocket URL patterns across applications."""

    def __init__(self):
        """Initialize the WebSocketUrlManager."""
        self.patterns = []
        self.app_patterns = {}
        self.conflicts = []

    def register_app_patterns(self, app_name: str, patterns: List, prefix: Optional[str] = None):
        """
        Register WebSocket URL patterns for an application.

        Args:
            app_name: Name of the Django application
            patterns: List of URL patterns from the app's routing.py
            prefix: Optional prefix to add to all patterns
        """
        processed_patterns = []

        for pattern in patterns:
            original_route = pattern.pattern._route.strip("/")

            if prefix:
                new_route = f"ws/{prefix.strip('/')}/{original_route}/"
            else:
                new_route = f"ws/{original_route}/"

            new_pattern = path(new_route, pattern.callback)
            processed_patterns.append(new_pattern)

        self.app_patterns[app_name] = processed_patterns
        logger.info(f"Registered {len(processed_patterns)} WebSocket patterns for app: {app_name}")

    def auto_discover_patterns(self):
        """
        Automatically discover WebSocket patterns from all installed Django apps.

        Looks for 'routing.py' files with 'websocket_urlpatterns' in each app.
        """
        logger.info("Starting WebSocket pattern auto-discovery...")
        for app_config in apps.get_app_configs():
            app_name = app_config.name

            # Skip built-in Django apps
            if app_name.startswith("django."):
                continue

            logger.debug(f"Checking app: {app_name}")
            try:
                # Try to import the routing module
                routing_module = importlib.import_module(f"{app_name}.routing")
                logger.debug(f"Found routing module for {app_name}")

                if hasattr(routing_module, "websocket_urlpatterns"):
                    patterns = routing_module.websocket_urlpatterns
                    logger.info(f"Found {len(patterns)} WebSocket patterns in {app_name}")

                    # Use app name as prefix to avoid conflicts
                    prefix = self._get_app_prefix(app_name)
                    self.register_app_patterns(app_name, patterns, prefix)

            except (ImportError, AttributeError) as e:
                logger.debug(f"App {app_name} doesn't have routing.py or websocket_urlpatterns: {e}")
                continue
            except Exception as e:
                logger.warning(f"Error importing WebSocket patterns from {app_name}: {e}")

        logger.info(f"Auto-discovery completed. Found patterns for {len(self.app_patterns)} apps")

    def _get_app_prefix(self, app_name: str) -> str:
        """
        Generate a URL prefix for an app to avoid conflicts.

        Args:
            app_name: Name of the Django application

        Returns:
            URL prefix string (without 'ws/')
        """
        app_short_name = app_name.split(".")[-1]
        return f"{app_short_name}/"

    def detect_conflicts(self) -> List[Tuple[str, str, str]]:
        """
        Detect conflicts between WebSocket URL patterns.

        Returns:
            List of tuples containing (pattern1, app1, pattern2, app2) for conflicts
        """
        conflicts = []
        all_patterns = []

        # Flatten all patterns with their source apps
        for app_name, patterns in self.app_patterns.items():
            for pattern in patterns:
                pattern_str = self._extract_pattern_string(pattern)
                all_patterns.append((pattern_str, app_name, pattern))

        # Check for conflicts
        for i, (pattern1, app1, _) in enumerate(all_patterns):
            for j, (pattern2, app2, _) in enumerate(all_patterns[i + 1 :], i + 1):
                if self._patterns_conflict(pattern1, pattern2):
                    conflicts.append((pattern1, app1, pattern2, app2))

        self.conflicts = conflicts
        return conflicts

    def _extract_pattern_string(self, pattern) -> str:
        """Extract the pattern string from a URL pattern object."""
        if hasattr(pattern, "pattern"):
            if hasattr(pattern.pattern, "_route"):
                return pattern.pattern._route
            elif hasattr(pattern.pattern, "regex"):
                return pattern.pattern.regex.pattern
        return str(pattern)

    def _patterns_conflict(self, pattern1: str, pattern2: str) -> bool:
        """
        Check if two URL patterns conflict.

        Args:
            pattern1: First URL pattern string
            pattern2: Second URL pattern string

        Returns:
            True if patterns conflict, False otherwise
        """
        # Exact match
        if pattern1 == pattern2:
            return True

        # Convert Django URL patterns to regex for comparison
        regex1 = self._pattern_to_regex(pattern1)
        regex2 = self._pattern_to_regex(pattern2)

        # Check if patterns could match the same URLs
        return self._regex_overlap(regex1, regex2)

    def _pattern_to_regex(self, pattern: str) -> str:
        """Convert a Django URL pattern to a regex pattern."""
        # Replace Django path converters with regex equivalents
        pattern = pattern.replace("<int:", "(?P<")
        pattern = pattern.replace("<str:", "(?P<")
        pattern = pattern.replace("<slug:", "(?P<")
        pattern = pattern.replace("<uuid:", "(?P<")
        pattern = pattern.replace(">", ">\\w+)")

        # Escape special regex characters that aren't converters
        pattern = re.escape(pattern)

        # Unescape the converter patterns we just created
        pattern = pattern.replace("\\(\\?P\\<", "(?P<")
        pattern = pattern.replace("\\>\\\\w\\+\\)", ">\\w+)")

        return f"^{pattern}$"

    def _regex_overlap(self, regex1: str, regex2: str) -> bool:
        """Check if two regex patterns could match overlapping URLs."""
        try:
            compiled1 = re.compile(regex1)
            compiled2 = re.compile(regex2)

            # Test with some common URL examples
            test_urls = [
                "ws/notifications/",
                "ws/admin/",
                "ws/data/",
                "ws/users/123/",
                "ws/groups/456/",
            ]

            for url in test_urls:
                if compiled1.match(url) and compiled2.match(url):
                    return True

        except re.error:
            # If regex compilation fails, assume conflict for safety
            return True

        return False

    def get_merged_patterns(self, raise_on_conflict: bool = True) -> List:
        """
        Get all registered patterns merged into a single list.

        Args:
            raise_on_conflict: Whether to raise an exception if conflicts are detected

        Returns:
            List of merged URL patterns

        Raises:
            WebSocketPatternConflict: If conflicts are detected and raise_on_conflict is True
        """
        conflicts = self.detect_conflicts()

        if conflicts and raise_on_conflict:
            conflict_details = []
            for pattern1, app1, pattern2, app2 in conflicts:
                conflict_details.append(f"'{pattern1}' ({app1}) conflicts with '{pattern2}' ({app2})")

            raise WebSocketPatternConflict("WebSocket URL pattern conflicts detected:\n" + "\n".join(conflict_details))

        if conflicts:
            logger.warning(f"WebSocket URL pattern conflicts detected but ignored: {len(conflicts)} conflicts")
            for pattern1, app1, pattern2, app2 in conflicts:
                logger.warning(f"Conflict: '{pattern1}' ({app1}) vs '{pattern2}' ({app2})")

        # Merge all patterns
        merged_patterns = []
        for app_name, patterns in self.app_patterns.items():
            merged_patterns.extend(patterns)

        logger.info(f"Merged {len(merged_patterns)} WebSocket patterns from {len(self.app_patterns)} apps")
        return merged_patterns

    def get_url_router(self, raise_on_conflict: bool = True) -> URLRouter:
        """
        Get a URLRouter with all merged patterns.

        Args:
            raise_on_conflict: Whether to raise an exception if conflicts are detected

        Returns:
            Configured URLRouter instance
        """
        patterns = self.get_merged_patterns(raise_on_conflict)
        return URLRouter(patterns)


def create_websocket_router(auto_discover: bool = True, raise_on_conflict: bool = True) -> URLRouter:
    """
    Create a WebSocket URL router with automatic pattern discovery and conflict detection.

    Args:
        auto_discover: Whether to automatically discover patterns from all apps
        raise_on_conflict: Whether to raise an exception if conflicts are detected

    Returns:
        Configured URLRouter instance
    """
    manager = WebSocketUrlManager()

    if auto_discover:
        manager.auto_discover_patterns()

    return manager.get_url_router(raise_on_conflict)


def register_websocket_patterns(app_name: str, patterns: List, prefix: Optional[str] = None):
    """
    Helper function to manually register WebSocket patterns for an app.

    Args:
        app_name: Name of the Django application
        patterns: List of URL patterns
        prefix: Optional prefix for the patterns
    """
    if not hasattr(register_websocket_patterns, "_manager"):
        register_websocket_patterns._manager = WebSocketUrlManager()

    register_websocket_patterns._manager.register_app_patterns(app_name, patterns, prefix)
    return register_websocket_patterns._manager
