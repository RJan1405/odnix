from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
import logging
from chat.models import CustomUser, EmailVerificationToken
from chat.forms import CustomUserCreationForm

User = get_user_model()
logger = logging.getLogger(__name__)

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'chat/login.html')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if not username or not password:
            messages.error(request, 'Username and password are required')
            return render(request, 'chat/login.html')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            # if user.is_email_verified:
            login(request, user)
            user.mark_online()
            messages.success(request, f'Welcome back, {user.full_name}!')
            return redirect('dashboard')
            # else:
            #     messages.error(request, 'Please verify your email before logging in.')
        else:
            try:
                existing_user = CustomUser.objects.get(username=username)
                messages.error(request, 'Invalid password. Please try again.')
            except CustomUser.DoesNotExist:
                # User doesn't exist - redirect to signup with a message
                messages.info(request, f'No account found with username "{username}". Please create an account to get started.')
                return redirect('register')
    
    return render(request, 'chat/login.html')

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.is_email_verified = True  # Auto-verify email for now
                
                user.save()
                
                # Send verification email
                send_verification_email(user, request)
                messages.success(request, f'Account created! Please check your email to verify your account.')
                return redirect('login')
                
            except Exception as e:
                logger.error(f"Error creating account: {str(e)}")
                messages.error(request, f'Error creating account: {str(e)}')
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    
    return render(request, 'chat/register.html')

def send_verification_email(user, request):
    try:
        # Delete any existing tokens for this user
        EmailVerificationToken.objects.filter(user=user).delete()
        
        token = EmailVerificationToken.objects.create(user=user)
        verification_url = request.build_absolute_uri(
            reverse('verify_email', kwargs={'token': token.token})
        )
        
        subject = 'Verify your Odnix account'
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: #667eea; color: white; padding: 20px; text-align: center;">
                    <h1>Welcome to Odnix!</h1>
                </div>
                <div style="padding: 20px;">
                    <h2>Hello {user.full_name}!</h2>
                    <p>Thank you for registering with Odnix. Please verify your email address:</p>
                    <a href="{verification_url}" style="background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 20px 0;">Verify Email</a>
                    <p>If the button doesn't work, copy this link: {verification_url}</p>
                    <p>This link expires in 24 hours.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        Hello {user.full_name}!
        
        Thank you for registering with Odnix. Please verify your email by visiting: {verification_url}
        
        This link expires in 24 hours.
        """
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_content,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False

def verify_email(request, token):
    try:
        verification_token = get_object_or_404(EmailVerificationToken, token=token)
        
        if verification_token.is_used:
            messages.error(request, 'This verification link has already been used.')
            return redirect('login')
        
        if verification_token.is_expired:
            messages.error(request, 'This verification link has expired.')
            return redirect('login')
        
        user = verification_token.user
        user.is_email_verified = True
        user.save()
        
        verification_token.is_used = True
        verification_token.save()
        
        messages.success(request, 'Email verified successfully! You can now log in.')
        return redirect('login')
        
    except Exception as e:
        logger.error(f"Email verification error: {e}")
        messages.error(request, 'Invalid verification link.')
        return redirect('login')

@login_required
def logout_view(request):
    request.user.mark_offline()
    logout(request)
    return redirect('login')
