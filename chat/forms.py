# forms.py - COMPLETE NEW VERSION WITH ALL FIXES

from django import forms
from django.core.exceptions import ValidationError
from .models import CustomUser, Tweet
import os

class CustomUserCreationForm(forms.ModelForm):
    """Enhanced user registration form"""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        }),
        min_length=6,
        help_text="Password must be at least 6 characters long"
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password'
        })
    )
    
    class Meta:
        model = CustomUser
        fields = ('username', 'name', 'lastname', 'email', 'profile_picture')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Choose a username'
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First name'
            }),
            'lastname': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Your email address'
            }),
            'profile_picture': forms.ClearableFileInput(attrs={
                'class': 'file-input',
                'accept': 'image/*',
                'style': 'display: none;'
            }),
        }
    
    def clean_confirm_password(self):
        password = self.cleaned_data.get('password')
        confirm_password = self.cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise ValidationError("Passwords don't match")
        
        return confirm_password
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if CustomUser.objects.filter(username=username).exists():
            raise ValidationError("Username already exists")
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.objects.filter(email=email).exists():
            raise ValidationError("Email already exists")
        return email
    
    def clean_profile_picture(self):
        profile_picture = self.cleaned_data.get('profile_picture')
        if profile_picture:
            # Check file size (max 5MB)
            if profile_picture.size > 5 * 1024 * 1024:
                raise ValidationError("Profile picture file too large. Maximum size is 5MB.")
            
            # Check file extension
            ext = os.path.splitext(profile_picture.name)[1].lower()
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            if ext not in valid_extensions:
                raise ValidationError("Invalid image format. Use JPG, PNG, GIF, or WEBP.")
        
        return profile_picture
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user

class LoginForm(forms.Form):
    """Simple login form"""
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )

class TweetForm(forms.ModelForm):
    """FIXED - Tweet form with image support - THIS WAS THE MAIN ISSUE"""
    
    class Meta:
        model = Tweet
        fields = ['content', 'image']  # CRITICAL FIX: Added 'image' field!
        widgets = {
            'content': forms.Textarea(attrs={
                'id': 'id_content',
                'class': 'form-control tweet-textarea',
                'placeholder': "What's happening?",
                'rows': 4,
                'maxlength': 280,
                'style': 'resize: none; border: none; outline: none; font-size: 1.1rem; padding: 1rem; background: #f8f9fa; border-radius: 0.5rem;'
            }),
            'image': forms.ClearableFileInput(attrs={
                'id': 'id_image',
                'class': 'form-control-file',
                'accept': 'image/*',
                'style': 'display: none;'  # Hide default input
            })
        }
    
    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if content and len(content) > 280:
            raise ValidationError("Tweet must be 280 characters or less")
        return content
    
    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            # Check file size (max 5MB)
            if image.size > 5 * 1024 * 1024:
                raise ValidationError("Image file too large. Maximum size is 5MB.")
            
            # Check file extension
            ext = os.path.splitext(image.name)[1].lower()
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            if ext not in valid_extensions:
                raise ValidationError("Invalid image format. Use JPG, PNG, GIF, or WEBP.")
        
        return image
    
    def clean(self):
        cleaned_data = super().clean()
        content = cleaned_data.get('content', '').strip()
        image = cleaned_data.get('image')
        
        # At least content or image must be provided
        if not content and not image:
            raise ValidationError("Tweet must have either text content or an image.")
        
        return cleaned_data

class ProfileUpdateForm(forms.ModelForm):
    """Form for updating user profile"""
    
    # Override profile_picture to use simple FileInput (no clear checkbox, no path display)
    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'profile-picture-input',
            'accept': 'image/*',
            'id': 'id_profile_picture'
        })
    )
    
    class Meta:
        model = CustomUser
        fields = ('name', 'lastname', 'username', 'profile_picture', 'is_private')
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First name'
            }),
            'lastname': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last name'
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username'
            }),
            'is_private': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        # Check if username is being changed
        if username != self.instance.username:
            if CustomUser.objects.filter(username=username).exists():
                raise ValidationError("Username already taken. Please choose another.")
        return username
    
    def clean_profile_picture(self):
        profile_picture = self.cleaned_data.get('profile_picture')
        if profile_picture:
            # Check file size (max 5MB)
            if profile_picture.size > 5 * 1024 * 1024:
                raise ValidationError("Profile picture file too large. Maximum size is 5MB.")
            
            # Check file extension
            ext = os.path.splitext(profile_picture.name)[1].lower()
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            if ext not in valid_extensions:
                raise ValidationError("Invalid image format. Use JPG, PNG, GIF, or WEBP.")
        
        return profile_picture