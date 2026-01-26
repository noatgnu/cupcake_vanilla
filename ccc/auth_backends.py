"""
Custom authentication backends for CUPCAKE Core.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.urls import reverse

import requests
from requests_oauthlib import OAuth2Session

logger = logging.getLogger(__name__)
User = get_user_model()


class ORCIDOAuth2Backend(BaseBackend):
    """
    Custom authentication backend for ORCID OAuth2.

    This backend allows users to authenticate using their ORCID account
    without requiring prior registration in the system.
    """

    def authenticate(self, request, **credentials):
        """
        Authenticate user using ORCID OAuth2 token.

        Args:
            request: The HTTP request object
            **credentials: Should contain 'orcid_token' and 'orcid_id'
                          Optional: 'orcid_name', 'verify_token' (default True)

        Returns:
            User object if authentication successful, None otherwise
        """
        orcid_token = credentials.get("orcid_token")
        orcid_id = credentials.get("orcid_id")
        orcid_name = credentials.get("orcid_name", "")
        verify_token = credentials.get("verify_token", True)

        if not orcid_token or not orcid_id:
            return None

        try:
            user_data = None

            # Verify the token with ORCID API if requested
            if verify_token:
                user_data = self._get_orcid_user_data(orcid_token, orcid_id)

            # If verification skipped or failed but we have credentials (fallback only if verification wasn't required)
            if not user_data and not verify_token:
                # Construct user data from credentials
                first_name = ""
                last_name = ""
                if orcid_name:
                    parts = orcid_name.split(" ", 1)
                    first_name = parts[0]
                    last_name = parts[1] if len(parts) > 1 else ""

                user_data = {
                    "orcid_id": orcid_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f'{orcid_id.replace("-", "")}@orcid.org',
                    "full_name": orcid_name or f"ORCID User {orcid_id}",
                }

            if not user_data:
                return None

            # Get or create user based on ORCID ID
            user = self._get_or_create_user(user_data)
            return user

        except Exception as e:
            logger.error(f"ORCID authentication error: {e}")
            return None

    def _get_orcid_user_data(self, token, orcid_id):
        """
        Fetch user data from ORCID API using access token.

        Args:
            token: OAuth2 access token
            orcid_id: ORCID identifier

        Returns:
            Dict containing user data or None if failed
        """
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        # Use sandbox or production based on settings
        base_url = getattr(settings, "ORCID_BASE_URL", "https://sandbox.orcid.org")
        api_url = f"{base_url}/v3.0/{orcid_id}/person"

        try:
            response = requests.get(api_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return self._extract_user_info(data, orcid_id)
            else:
                logger.warning(f"ORCID API returned status {response.status_code}")
                return None

        except requests.RequestException as e:
            logger.error(f"Error fetching ORCID data: {e}")
            return None

    def _extract_user_info(self, orcid_data, orcid_id):
        """
        Extract relevant user information from ORCID API response.

        Args:
            orcid_data: Raw data from ORCID API
            orcid_id: ORCID identifier

        Returns:
            Dict with extracted user information
        """
        try:
            name_data = orcid_data.get("name", {})

            # Extract name components
            given_names = name_data.get("given-names", {}).get("value", "") if name_data.get("given-names") else ""
            family_name = name_data.get("family-name", {}).get("value", "") if name_data.get("family-name") else ""

            # Extract email (if available and public)
            emails = orcid_data.get("emails", {}).get("email", [])
            primary_email = None
            for email in emails:
                if email.get("primary", False):
                    primary_email = email.get("email")
                    break

            # If no primary email, use first available
            if not primary_email and emails:
                primary_email = emails[0].get("email")

            return {
                "orcid_id": orcid_id,
                "first_name": given_names,
                "last_name": family_name,
                "email": primary_email or f'{orcid_id.replace("-", "")}@orcid.org',  # Fallback email
                "full_name": f"{given_names} {family_name}".strip() or f"ORCID User {orcid_id}",
            }

        except Exception as e:
            logger.error(f"Error extracting ORCID user info: {e}")
            return {
                "orcid_id": orcid_id,
                "first_name": "",
                "last_name": "",
                "email": f'{orcid_id.replace("-", "")}@orcid.org',
                "full_name": f"ORCID User {orcid_id}",
            }

    def _get_or_create_user(self, user_data):
        """
        Get existing user or create new one based on ORCID ID.

        Args:
            user_data: Dict containing user information from ORCID

        Returns:
            User object
        """
        orcid_id = user_data["orcid_id"]

        # Try to find existing user by ORCID ID stored in username or a custom field
        # First check if user exists with ORCID ID as username
        try:
            user = User.objects.get(username=orcid_id)
            # Update user data if needed
            self._update_user_from_orcid(user, user_data)
            return user
        except User.DoesNotExist:
            pass

        # Try to find by email if available
        email = user_data.get("email")
        if email and "@orcid.org" not in email:  # Don't match fallback emails
            try:
                user = User.objects.get(email=email)
                # Update ORCID ID in username if not set
                if user.username != orcid_id:
                    user.username = orcid_id
                    user.save()
                self._update_user_from_orcid(user, user_data)
                return user
            except User.DoesNotExist:
                pass

        # Create new user
        user = User.objects.create_user(
            username=orcid_id,
            email=user_data["email"],
            first_name=user_data["first_name"],
            last_name=user_data["last_name"],
        )
        user.is_active = True
        user.save()

        logger.info(f"Created new user for ORCID ID: {orcid_id}")
        return user

    def _update_user_from_orcid(self, user, user_data):
        """
        Update user information from ORCID data.

        Args:
            user: User object to update
            user_data: Dict containing user information from ORCID
        """
        updated = False

        # Update names if they are more complete in ORCID
        if user_data["first_name"] and not user.first_name:
            user.first_name = user_data["first_name"]
            updated = True

        if user_data["last_name"] and not user.last_name:
            user.last_name = user_data["last_name"]
            updated = True

        # Update email if it's a real email (not our fallback)
        if user_data["email"] and "@orcid.org" not in user_data["email"] and not user.email:
            user.email = user_data["email"]
            updated = True

        if updated:
            user.save()
            logger.info(f"Updated user data for ORCID ID: {user_data['orcid_id']}")

    def get_user(self, user_id):
        """
        Get user by ID - required by Django authentication backend interface.
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class ORCIDOAuth2Helper:
    """
    Helper class for ORCID OAuth2 operations.
    """

    @staticmethod
    def get_authorization_url(request):
        """
        Generate ORCID OAuth2 authorization URL.

        Args:
            request: HTTP request object for building redirect URI

        Returns:
            Tuple of (authorization_url, state)
        """
        client_id = getattr(settings, "ORCID_CLIENT_ID", None)
        if not client_id:
            raise ValueError("ORCID_CLIENT_ID not configured")

        # Build redirect URI
        redirect_path = reverse("orcid-callback")
        redirect_uri = request.build_absolute_uri(redirect_path)

        # Force HTTPS in production
        base_url = getattr(settings, "ORCID_BASE_URL", "https://sandbox.orcid.org")
        is_production = "sandbox" not in base_url

        if (not settings.DEBUG or is_production) and redirect_uri.startswith("http://"):
            redirect_uri = redirect_uri.replace("http://", "https://", 1)

        authorization_base_url = f"{base_url}/oauth/authorize"

        # Create OAuth2 session
        orcid = OAuth2Session(
            client_id, scope=["/authenticate"], redirect_uri=redirect_uri  # Basic authentication scope
        )

        authorization_url, state = orcid.authorization_url(authorization_base_url)
        return authorization_url, state

    @staticmethod
    def exchange_code_for_token(request, code, state):
        """
        Exchange authorization code for access token.

        Args:
            request: HTTP request object
            code: Authorization code from ORCID
            state: State parameter for CSRF protection

        Returns:
            Dict containing token data or None if failed
        """
        client_id = getattr(settings, "ORCID_CLIENT_ID", None)
        client_secret = getattr(settings, "ORCID_CLIENT_SECRET", None)

        if not client_id or not client_secret:
            raise ValueError("ORCID credentials not configured")

        # Build redirect URI
        redirect_path = reverse("orcid-callback")
        redirect_uri = request.build_absolute_uri(redirect_path)

        # Force HTTPS in production/Cloudflare environments if not detected correctly
        base_url = getattr(settings, "ORCID_BASE_URL", "https://sandbox.orcid.org")
        is_production = "sandbox" not in base_url

        if (not settings.DEBUG or is_production) and redirect_uri.startswith("http://"):
            redirect_uri = redirect_uri.replace("http://", "https://", 1)

        token_url = f"{base_url}/oauth/token"

        try:
            # Create OAuth2 session
            orcid = OAuth2Session(client_id, state=state, redirect_uri=redirect_uri)

            # Exchange code for token
            token = orcid.fetch_token(token_url, code=code, client_secret=client_secret)

            return token

        except Exception as e:
            logger.error(f"Error exchanging ORCID code for token: {e}")
            return None
