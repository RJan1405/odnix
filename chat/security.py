import filetype
import os
from django.core.exceptions import ValidationError
from PIL import Image

# Security Constants
MAX_IMAGE_DIMENSION = 5000  # 5000x5000px max (prevent pixel floods)
ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'video/mp4', 'video/quicktime', 'video/x-matroska', 'video/webm'
}
# Safe Extensions Map (Enforce extension matches mime)
MIME_TO_EXT = {
    'image/jpeg': ['.jpg', '.jpeg'],
    'image/png': ['.png'],
    'image/gif': ['.gif'],
    'image/webp': ['.webp'],
    'video/mp4': ['.mp4'],
    'video/quicktime': ['.mov'],
    'video/x-matroska': ['.mkv'],
    'video/webm': ['.webm']
}

def validate_media_file(file_obj):
    """
    Instagram-style Magic Byte & Security Validation.
    Reject files that are spoofed (e.g., exe renamed to jpg).
    """
    
    # 1. Reset file pointer
    file_obj.seek(0)
    
    # 2. Read Magic Bytes (first 262 bytes usually enough)
    head_sample = file_obj.read(262)
    file_obj.seek(0) # Reset immediately
    
    # 3. Detect Real Type
    kind = filetype.guess(head_sample)
    
    if kind is None:
        raise ValidationError("Unknown or unsafe file format. File signature unrecognized.")
    
    mime = kind.mime
    
    # 4. Whitelist Check
    if mime not in ALLOWED_MIME_TYPES:
        raise ValidationError(f"File type '{mime}' is not supported for security reasons.")
    
    # 5. Extension vs Content Check (Spoofing Protection)
    # Get extension provided by user
    user_ext = os.path.splitext(file_obj.name)[1].lower()
    allowed_exts = MIME_TO_EXT.get(mime, [])
    
    if user_ext not in allowed_exts:
        # If user uploads 'virus.exe' as 'virus.jpg', mime is 'application/x-dosexec' -> blocked above.
        # If user uploads 'image.png' as 'image.jpg', we catch it here.
        # We could auto-fix it, but for security, rejecting inconsistent files is safer.
        raise ValidationError(
            f"File extension '{user_ext}' does not match the detected file content ({mime}). "
            "Please upload valid files without renaming extensions."
        )
    
    # 6. Image Specific Checks (Pixel Flood / Zip Bomb)
    if mime.startswith('image/'):
        try:
            # We open without loading data to check header
            img = Image.open(file_obj)
            img.verify() # Verify file integrity
            
            # Check dimensions against DoS attacks
            width, height = img.size
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise ValidationError(f"Image is too large ({width}x{height}). Max allowed is {MAX_IMAGE_DIMENSION}px.")
                
            # Re-open for future processing (verify closes file)
            file_obj.seek(0)
            
        except Exception as e:
            if isinstance(e, ValidationError): raise e
            raise ValidationError("Invalid or corrupt image file.")

    return True
