
import os
import django
import shutil
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "odnix.settings")
django.setup()

from chat.forms import TweetForm, ProfileUpdateForm
from chat.security import validate_media_file
from django.core.exceptions import ValidationError

def test_malicious_uploads():
    print("=== Testing Media Security (Virus/Spoof Protection) ===\n")

    # 1. Create a "Fake Image" (Text file renamed to .jpg)
    # This simulates a script or executable renamed to bypass extension checks
    fake_content = b"This is a fake virus script pretending to be an image."
    fake_img = SimpleUploadedFile("virus.jpg", fake_content, content_type="image/jpeg")
    
    print(f"[TEST 1] Uploading Fake JPEG (Text content): {fake_img.name}")
    
    try:
        # Test Direct Security Function
        validate_media_file(fake_img)
        print("❌ FAILED: Security function accepted fake file!")
    except ValidationError as e:
        print(f"✅ PASSED: Security function blocked it: {e}")
    except Exception as e:
        print(f"❓ ERROR: Unexpected error: {e}")

    # 2. Test via TweetForm
    print(f"\n[TEST 2] Testing TweetForm with Fake Image")
    form_data = {'content': 'Malicious Tweet'}
    file_data = {'image': fake_img}
    
    form = TweetForm(data=form_data, files=file_data)
    if form.is_valid():
        print("❌ FAILED: TweetForm accepted the fake image!")
    else:
        print("✅ PASSED: TweetForm flagged errors:")
        print(form.errors['image'])


    # 3. Test Extension Mismatch (JPEG content inside .png)
    # Create valid JPEG header (minimal)
    # JPEG Magic Bytes: FF D8 FF
    jpeg_header = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00'
    mismatched_img = SimpleUploadedFile("spoof.png", jpeg_header, content_type="image/png")
    
    print(f"\n[TEST 3] Uploading Mismatched Extension (JPEG named .png)")
    
    try:
        validate_media_file(mismatched_img)
        print("❌ FAILED: Security function accepted mismatched extension!")
    except ValidationError as e:
        print(f"✅ PASSED: Security function blocked it: {e}")

    # 4. Test Profile Update Form
    print(f"\n[TEST 4] Testing ProfileUpdateForm with Fake Image")
    # Reset fake image cursor
    fake_img.seek(0)
    p_form = ProfileUpdateForm(data={'name': 'Hacker'}, files={'profile_picture': fake_img})
    
    # We need to bind to a user instance theoretically, but for validation logic check it might suffice
    # ProfileUpdateForm requires an instance usually for username check, let's allow it to fail strict model checks
    # and just look at profile_picture errors.
    
    # Actually, let's just check the clean_profile_picture method behavior directly or full validation
    # Construct a dummy instance
    from chat.models import CustomUser
    user = CustomUser(username="test_sec_user", id=9999)
    p_form = ProfileUpdateForm(data={'username': 'test_sec_user'}, files={'profile_picture': fake_img}, instance=user)
    
    if p_form.is_valid():
         print("❌ FAILED: ProfileForm accepted the fake image!")
    else:
        if 'profile_picture' in p_form.errors:
            print("✅ PASSED: ProfileForm blocked profile picture:")
            print(p_form.errors['profile_picture'])
        else:
            print(f"⚠️  WARNING: Form failed but not due to image? Errors: {p_form.errors}")

    print("\n=== Security Test Complete ===")

if __name__ == "__main__":
    test_malicious_uploads()
