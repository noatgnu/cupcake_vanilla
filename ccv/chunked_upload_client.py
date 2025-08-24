"""
Client utility for chunked upload of metadata files.

Example usage for uploading large SDRF/Excel files to CUPCAKE Vanilla.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

import requests


class MetadataChunkedUploadClient:
    """Client for uploading large metadata files using chunked upload."""

    def __init__(self, base_url: str, token: str):
        """
        Initialize the upload client.

        Args:
            base_url: Base URL of the CUPCAKE Vanilla API (e.g., 'http://localhost:8000')
            token: Authentication token
        """
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {token}",
        }
        self.chunk_size = 1024 * 1024 * 2  # 2MB chunks

    def calculate_file_checksum(self, file_path: str) -> str:
        """Calculate SHA-256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def upload_file(
        self,
        file_path: str,
        target_content_type_id: int,
        target_object_id: int,
        import_type: str = "user_metadata",
        create_pools: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Upload a metadata file using chunked upload.

        Args:
            file_path: Path to the file to upload
            target_content_type_id: ContentType ID of target model
            target_object_id: ID of target object
            import_type: Type of import ('user_metadata', 'staff_metadata', 'both')
            create_pools: Whether to create sample pools from SDRF data
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with upload result
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size
        filename = file_path.name

        # Calculate file checksum
        print(f"Calculating SHA-256 checksum for {filename}...")
        checksum = self.calculate_file_checksum(str(file_path))
        print(f"File checksum: {checksum}")

        # Step 1: Create upload session
        print("Creating upload session...")
        create_data = {
            "filename": filename,
        }

        create_response = requests.post(
            f"{self.base_url}/api/v1/chunked-upload/",
            headers=self.headers,
            data=create_data,
            timeout=30,
        )

        if create_response.status_code != 201:
            raise Exception(f"Failed to create upload session: {create_response.text}")

        upload_data = create_response.json()
        upload_id = upload_data["id"]
        print(f"Upload session created: {upload_id}")

        # Step 2: Upload file chunks
        uploaded_bytes = 0

        with open(file_path, "rb") as f:
            while uploaded_bytes < file_size:
                # Read chunk
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break

                # Upload chunk
                print(f"Uploading chunk: {uploaded_bytes}-{uploaded_bytes + len(chunk) - 1}/{file_size}")

                files = {"file": chunk}
                data = {"offset": uploaded_bytes}

                chunk_response = requests.put(
                    f"{self.base_url}/api/v1/chunked-upload/{upload_id}/",
                    headers=self.headers,
                    files=files,
                    data=data,
                    timeout=60,
                )

                if chunk_response.status_code not in [200, 201]:
                    raise Exception(f"Failed to upload chunk: {chunk_response.text}")

                uploaded_bytes += len(chunk)

                # Call progress callback if provided
                if progress_callback:
                    progress_callback(uploaded_bytes, file_size)

        # Step 3: Complete upload and process file
        print("Completing upload and processing file...")
        complete_data = {
            "checksum": checksum,
            "target_content_type_id": target_content_type_id,
            "target_object_id": target_object_id,
            "import_type": import_type,
            "create_pools": create_pools,
        }

        complete_response = requests.post(
            f"{self.base_url}/api/v1/chunked-upload/{upload_id}/",
            headers=self.headers,
            data=complete_data,
            timeout=30,
        )

        if complete_response.status_code != 200:
            raise Exception(f"Failed to complete upload: {complete_response.text}")

        result = complete_response.json()
        print("Upload completed successfully!")
        return result

    def upload_with_progress(
        self,
        file_path: str,
        target_content_type_id: int,
        target_object_id: int,
        **kwargs,
    ) -> Dict[str, Any]:
        """Upload file with console progress display."""

        def progress_callback(uploaded: int, total: int):
            percent = (uploaded / total) * 100
            bar_length = 50
            filled_length = int(bar_length * uploaded // total)
            bar = "█" * filled_length + "-" * (bar_length - filled_length)
            print(
                f"\rProgress: |{bar}| {percent:.1f}% ({uploaded}/{total} bytes)",
                end="",
                flush=True,
            )

        try:
            result = self.upload_file(
                file_path=file_path,
                target_content_type_id=target_content_type_id,
                target_object_id=target_object_id,
                progress_callback=progress_callback,
                **kwargs,
            )
            print()  # New line after progress bar
            return result
        except Exception as e:
            print(f"\nUpload failed: {e}")
            raise


# Example usage
def example_usage():
    """Example of how to use the chunked upload client."""

    # Initialize client
    import os

    token = os.environ.get("CUPCAKE_AUTH_TOKEN", "your_auth_token_here")
    client = MetadataChunkedUploadClient(base_url="http://localhost:8000", token=token)

    try:
        # Upload a large SDRF file
        result = client.upload_with_progress(
            file_path="/path/to/large_metadata.sdrf",
            target_content_type_id=1,  # ContentType ID for your target model
            target_object_id=1,  # ID of your target object
            import_type="user_metadata",
            create_pools=True,
        )

        print("Upload result:")
        print(f"- Created {result['created_columns']} metadata columns")
        print(f"- Created {result['created_pools']} sample pools")
        print(f"- Processed {result['sample_rows']} sample rows")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    example_usage()
