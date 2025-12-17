import os
import uuid
import mimetypes
import logging
from django.conf import settings
from django.core.files.storage import default_storage
from django.http import HttpResponse, Http404

logger = logging.getLogger(__name__)

from PIL import Image, ImageOps
from io import BytesIO
from django.core.files.base import ContentFile

def handle_media_upload(media_file):
    if not media_file:
        return None, None, None, None
    
    try:
        # SECURITY CHECK
        from chat.security import validate_media_file, ValidationError
        validate_media_file(media_file)

        file_extension = os.path.splitext(media_file.name)[1].lower()
        
        # IMAGE COMPRESSION PIPELINE (Pillow)
        if file_extension in ['.jpg', '.jpeg', '.png', '.webp']:
            try:
                # Open image
                image = Image.open(media_file)
                
                # Fix orientation based on EXIF data
                image = ImageOps.exif_transpose(image)
                
                # 1. Resize if dimension > 1080px (Instagram standard)
                max_dimension = 1080
                if image.width > max_dimension or image.height > max_dimension:
                    # Calculate new size maintaining aspect ratio
                    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                
                # 2. Compress
                output_io = BytesIO()
                
                # Handle varying formats
                if file_extension in ['.jpg', '.jpeg']:
                    # Convert to RGB for JPEGs (handles RGBA->RGB)
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                    image.save(output_io, format='JPEG', quality=80, optimize=True)
                elif file_extension == '.png':
                    # Optimize PNG (lossless)
                    image.save(output_io, format='PNG', optimize=True)
                elif file_extension == '.webp':
                    image.save(output_io, format='WEBP', quality=80, optimize=True)
                
                # Update file pointer to compressed data
                if output_io.tell() > 0:
                     # Only replace if compression actually happened/worked
                    media_file = ContentFile(output_io.getvalue(), name=media_file.name)
                
            except Exception as e:
                logger.error(f"Image compression failed (skipping): {e}")

        unique_filename = f'chat_media/{uuid.uuid4()}{file_extension}'
        
        file_path = default_storage.save(unique_filename, media_file)
        file_url = default_storage.url(file_path)
        
        if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            media_type = 'image'
        elif file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
            media_type = 'video'
        else:
            media_type = 'document'
        
        return file_url, media_type, media_file.name, media_file.size
        
    except Exception as e:
        logger.error(f"Error uploading media: {e}")
        return None, None, None, None

# FIXED: Media serving function with path traversal protection
def serve_media_file(request, file_path):
    """Serve media files with path traversal protection"""
    try:
        # Normalize the path and ensure it stays within MEDIA_ROOT
        # This prevents path traversal attacks like ../../../etc/passwd
        full_path = os.path.normpath(os.path.join(settings.MEDIA_ROOT, file_path))
        
        # Security check: ensure the resolved path is within MEDIA_ROOT
        if not full_path.startswith(str(settings.MEDIA_ROOT)):
            logger.warning(f"Path traversal attempt detected: {file_path}")
            raise Http404("Invalid file path")
        
        if not os.path.exists(full_path):
            raise Http404("Media file not found")
        
        mime_type, _ = mimetypes.guess_type(full_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        with open(full_path, 'rb') as f:
            file_data = f.read()
        
        response = HttpResponse(file_data, content_type=mime_type)
        response['Content-Length'] = len(file_data)
        response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_path)}"'
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        
        return response
        
    except Exception as e:
        logger.error(f"Error serving media file: {e}")
        raise Http404("Error serving media file")
