import base64
import mimetypes
import os
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils.html import escape


def get_mime_type(file_path):
    """Get MIME type for a file."""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"


def encode_file_to_base64(file_path):
    """Encode file to base64 data URI."""
    if not os.path.exists(file_path):
        return None

    mime_type = get_mime_type(file_path)

    try:
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"
    except Exception:
        return None


def get_html_template():
    """
    Get the HTML template for session protocol export.

    Returns:
        str: HTML template string with Python format placeholders
    """
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{session_name} - Protocol Export</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #212529;
            background: #ffffff;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
        }}

        .header {{
            border-bottom: 3px solid #0d6efd;
            padding-bottom: 20px;
            margin-bottom: 30px;
            page-break-after: avoid;
        }}

        .header h1 {{
            color: #212529;
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 600;
        }}

        .meta-info {{
            color: #6c757d;
            font-size: 0.95em;
            line-height: 1.8;
        }}

        .meta-info-item {{
            display: inline-block;
            margin-right: 24px;
            margin-bottom: 6px;
        }}

        .meta-info-item strong {{
            color: #495057;
            font-weight: 600;
        }}

        .session-annotations {{
            background: #f8f9fa;
            padding: 24px;
            border-radius: 8px;
            margin-bottom: 30px;
            border: 1px solid #dee2e6;
            page-break-inside: avoid;
        }}

        .session-annotations h2 {{
            color: #212529;
            margin-bottom: 16px;
            font-size: 1.5em;
            font-weight: 600;
            border-bottom: 2px solid #0d6efd;
            padding-bottom: 8px;
        }}

        .protocol {{
            margin-bottom: 50px;
            page-break-before: always;
        }}

        .protocol:first-of-type {{
            page-break-before: auto;
        }}

        .protocol-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 24px;
            border-radius: 8px;
            margin-bottom: 24px;
            page-break-inside: avoid;
            page-break-after: avoid;
        }}

        .protocol-header h2 {{
            font-size: 2em;
            margin-bottom: 12px;
            font-weight: 600;
        }}

        .protocol-description {{
            opacity: 0.95;
            line-height: 1.6;
            margin-top: 8px;
        }}

        .protocol-meta {{
            display: flex;
            gap: 24px;
            margin-top: 16px;
            font-size: 0.9em;
            flex-wrap: wrap;
        }}

        .protocol-meta span {{
            opacity: 0.9;
        }}

        .section {{
            margin-bottom: 32px;
            padding-bottom: 0;
            page-break-inside: avoid;
        }}

        .section-header {{
            color: #0d6efd;
            font-size: 1.4em;
            margin-bottom: 20px;
            font-weight: 600;
            padding-bottom: 12px;
            border-bottom: 2px solid #0d6efd;
            page-break-after: avoid;
        }}

        .step {{
            background: #fff;
            padding: 20px 0;
            margin-bottom: 24px;
            page-break-inside: avoid;
        }}

        .step:last-child {{
            margin-bottom: 0;
        }}

        .step-number {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: #0d6efd;
            color: white;
            min-width: 36px;
            height: 36px;
            border-radius: 6px;
            text-align: center;
            font-weight: 600;
            margin-right: 12px;
            padding: 0 10px;
            font-size: 0.95em;
        }}

        .step-header {{
            display: flex;
            align-items: center;
            margin-bottom: 16px;
            gap: 12px;
            flex-wrap: wrap;
            page-break-after: avoid;
        }}

        .step-title {{
            font-size: 1.15em;
            font-weight: 600;
            color: #212529;
            flex: 1;
        }}

        .step-duration {{
            background: #e9ecef;
            color: #495057;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 0.9em;
            white-space: nowrap;
            border: 1px solid #dee2e6;
            font-weight: 500;
        }}

        .step-description {{
            color: #495057;
            margin-bottom: 16px;
            white-space: pre-wrap;
            line-height: 1.7;
            padding-left: 48px;
        }}

        .step-reagents {{
            background: #fff3cd;
            padding: 16px;
            border-radius: 6px;
            margin-bottom: 16px;
            border: 1px solid #ffc107;
            margin-left: 48px;
            page-break-inside: avoid;
        }}

        .step-reagents h4 {{
            color: #856404;
            margin-bottom: 10px;
            font-size: 1em;
            font-weight: 600;
        }}

        .reagent-list {{
            list-style: none;
            padding-left: 0;
        }}

        .reagent-list li {{
            padding: 5px 0;
            color: #856404;
            font-weight: 500;
        }}

        .reagent-list li::before {{
            content: "• ";
            margin-right: 8px;
            font-weight: bold;
        }}

        .step-annotations {{
            border-top: 2px solid #e9ecef;
            padding-top: 16px;
            margin-top: 16px;
            margin-left: 48px;
            page-break-inside: avoid;
        }}

        .step-annotations h4 {{
            color: #6f42c1;
            margin-bottom: 14px;
            font-size: 1.1em;
            font-weight: 600;
        }}

        .annotation {{
            background: #f8f9fa;
            padding: 16px;
            border-radius: 6px;
            margin-bottom: 14px;
            border: 1px solid #dee2e6;
            border-left: 4px solid #6f42c1;
            page-break-inside: avoid;
        }}

        .annotation-meta {{
            font-size: 0.88em;
            color: #6c757d;
            margin-bottom: 10px;
            font-weight: 500;
        }}

        .annotation-meta strong {{
            color: #495057;
            font-weight: 600;
        }}

        .annotation-text {{
            color: #212529;
            margin-bottom: 12px;
            line-height: 1.6;
        }}

        .annotation-file {{
            margin-top: 12px;
        }}

        .annotation-file img {{
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border: 1px solid #dee2e6;
        }}

        .annotation-file video {{
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            border: 1px solid #dee2e6;
        }}

        .annotation-file audio {{
            width: 100%;
            margin-top: 10px;
        }}

        .annotation-file a {{
            display: inline-block;
            background: #6f42c1;
            color: white;
            padding: 8px 16px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.9em;
            font-weight: 500;
            border: 1px solid #6f42c1;
        }}

        .footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 2px solid #dee2e6;
            text-align: center;
            color: #6c757d;
            font-size: 0.9em;
            page-break-inside: avoid;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 600;
            margin-left: 8px;
        }}

        .badge-sketch {{ background: #fff3cd; color: #856404; border: 1px solid #ffc107; }}
        .badge-image {{ background: #cfe2ff; color: #084298; border: 1px solid #0d6efd; }}
        .badge-video {{ background: #e7d6f5; color: #59399c; border: 1px solid #6f42c1; }}
        .badge-audio {{ background: #d1e7dd; color: #0f5132; border: 1px solid #198754; }}
        .badge-file {{ background: #f8d7da; color: #842029; border: 1px solid #dc3545; }}
        .badge-text {{ background: #e9ecef; color: #495057; border: 1px solid #6c757d; }}
        .badge-calculator {{ background: #d3f9d8; color: #146c43; border: 1px solid #198754; }}
        .badge-molarity {{ background: #cff4fc; color: #055160; border: 1px solid #0dcaf0; }}
        .badge-booking {{ background: #fce8e6; color: #8b4513; border: 1px solid #fd7e14; }}

        .transcription {{
            background: #e7f1ff;
            padding: 14px;
            border-radius: 6px;
            margin-top: 12px;
            font-size: 0.9em;
            color: #084298;
            border: 1px solid #b6d4fe;
        }}

        .transcription h5 {{
            margin-bottom: 8px;
            font-size: 0.95em;
            font-weight: 600;
            color: #052c65;
        }}

        .template-value {{
            background: #e7f1ff;
            padding: 2px 6px;
            border-radius: 3px;
            font-weight: 600;
            color: #084298;
            border: 1px solid #b6d4fe;
            white-space: nowrap;
        }}

        .template-value-scaled {{
            background: #d1e7dd;
            color: #0f5132;
            border: 1px solid #badbcc;
        }}

        .template-value-name {{
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffc107;
        }}

        .template-value-unit {{
            background: #f8f9fa;
            color: #495057;
            border: 1px solid #dee2e6;
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
                font-size: 11pt;
                line-height: 1.5;
            }}

            .container {{
                padding: 0;
                max-width: 100%;
            }}

            .header {{
                page-break-after: avoid;
            }}

            .step,
            .protocol-header,
            .annotation,
            .step-annotations,
            .step-reagents,
            .section {{
                page-break-inside: avoid;
            }}

            .section-header,
            .step-header,
            .protocol-header {{
                page-break-after: avoid;
            }}

            .protocol {{
                page-break-before: always;
            }}

            .protocol:first-of-type {{
                page-break-before: auto;
            }}

            .step-number,
            .protocol-header,
            .badge,
            .template-value,
            .template-value-scaled,
            .template-value-name,
            .template-value-unit {{
                print-color-adjust: exact;
                -webkit-print-color-adjust: exact;
                color-adjust: exact;
            }}

            .footer {{
                page-break-before: auto;
                margin-top: 20mm;
            }}

            a {{
                text-decoration: none;
                color: inherit;
            }}

            .annotation-file a {{
                background: #6f42c1 !important;
                color: white !important;
                print-color-adjust: exact;
                -webkit-print-color-adjust: exact;
            }}
        }}

        @page {{
            margin: 20mm;
            size: A4;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{session_name}</h1>
            <div class="meta-info">
                {started_at_html}
                {ended_at_html}
                <div class="meta-info-item"><strong>Owner:</strong> {owner_name}</div>
                <div class="meta-info-item"><strong>Exported:</strong> {export_date}</div>
            </div>
        </div>

        {session_annotations_section}

        {protocols_html}

        <div class="footer">
            <p>Generated by CUPCAKE Vanilla - Research Protocol Management System</p>
            <p>{export_date}</p>
        </div>
    </div>
</body>
</html>
    """


def _process_annotation_file(annotation):
    """Process annotation file and return HTML for display."""
    if not annotation.file:
        return None

    file_path = annotation.file.path
    if not os.path.exists(file_path):
        return None

    annotation_type = annotation.annotation_type
    file_name = os.path.basename(annotation.file.name)

    if annotation_type == "image":
        data_uri = encode_file_to_base64(file_path)
        if data_uri:
            return f'<img src="{data_uri}" alt="{escape(file_name)}" />'

    elif annotation_type == "video":
        data_uri = encode_file_to_base64(file_path)
        if data_uri:
            return f'<video controls><source src="{data_uri}" /></video>'

    elif annotation_type == "audio":
        data_uri = encode_file_to_base64(file_path)
        if data_uri:
            return f'<audio controls><source src="{data_uri}" /></audio>'

    elif annotation_type == "sketch":
        data_uri = encode_file_to_base64(file_path)
        if data_uri and file_path.endswith(".json"):
            return f"<div><strong>Sketch File:</strong> {escape(file_name)}</div>"

    return f'<a href="#" onclick="return false;"><strong>File:</strong> {escape(file_name)}</a>'


def save_session_export_to_temp(session):
    """
    Generate HTML export for session and save to temporary file.

    Args:
        session: Session instance

    Returns:
        tuple: (relative_path, filename) for X-Accel-Redirect
    """
    html_content = session.export_protocols_html()

    media_root = Path(settings.MEDIA_ROOT)
    temp_dir = media_root / "temp" / "exports"
    temp_dir.mkdir(parents=True, exist_ok=True)

    unique_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"session_{session.id}_{timestamp}_{unique_id}.html"
    temp_file_path = temp_dir / filename

    with open(temp_file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    relative_path = f"temp/exports/{filename}"

    return relative_path, filename


def save_protocol_export_to_temp(protocol, session=None):
    """
    Generate HTML export for protocol and save to temporary file.

    Args:
        protocol: ProtocolModel instance
        session: Optional Session instance for session-specific export

    Returns:
        tuple: (relative_path, filename) for X-Accel-Redirect
    """
    html_content = protocol.export_html(session=session)

    media_root = Path(settings.MEDIA_ROOT)
    temp_dir = media_root / "temp" / "exports"
    temp_dir.mkdir(parents=True, exist_ok=True)

    unique_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if session:
        filename = f"protocol_{protocol.id}_session_{session.id}_{timestamp}_{unique_id}.html"
    else:
        filename = f"protocol_{protocol.id}_{timestamp}_{unique_id}.html"

    temp_file_path = temp_dir / filename

    with open(temp_file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    relative_path = f"temp/exports/{filename}"

    return relative_path, filename
