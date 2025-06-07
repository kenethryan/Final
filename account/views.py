from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from .models import UserProfile
from django.core.mail import send_mail
from django.conf import settings
import random
from django.utils import timezone
import logging
from captcha.fields import CaptchaField
from django import forms
from django.http import JsonResponse

logger = logging.getLogger(__name__)

class RegistrationForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone_number = forms.CharField(max_length=20)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)
    captcha = CaptchaField()

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Bypass status check for superusers
            if not user.is_superuser:
                try:
                    profile = user.userprofile
                    if profile.status != 'active':
                        # Show specific status messages
                        if profile.status == 'pending':
                            msg = 'Your account is pending admin approval'
                        elif profile.status == 'inactive':
                            msg = 'Your account is inactive'
                        else:
                            msg = 'Account status invalid'
                        messages.error(request, msg)
                        return redirect('account:login')
                except UserProfile.DoesNotExist:
                    messages.error(request, 'Invalid account configuration')
                    return redirect('account:login')

            # Final check for Django's is_active flag
            if not user.is_active:
                messages.error(request, 'Account disabled')
                return redirect('account:login')

            login(request, user)
            from .models import UserActivityLog
            UserActivityLog.objects.create(
                user=user,
                action='login',
                details=f"User logged in "
            )

            # Redirect superusers to admin dashboard
            if user.is_superuser:
                return redirect('management:dashboard')
            return redirect('account:home')
        else:
            # Handle authentication failures more clearly
            try:
                user = User.objects.get(username=username)
                messages.error(request, 'Invalid password')
            except User.DoesNotExist:
                messages.error(request, 'Invalid username')

            return redirect('account:login')

    return render(request, 'login.html')

def verify_otp(request, user_id):
    user = get_object_or_404(User, id=user_id)
    profile = user.userprofile

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')

        # Check OTP expiration (5 minutes)
        time_diff = timezone.now() - profile.otp_created_at
        if time_diff.total_seconds() > 300:
            messages.error(request, 'OTP expired')
            return redirect('account:verify_otp', user_id=user_id)

        if entered_otp == profile.otp:
            profile.otp = None
            profile.save()
            messages.success(request, 'OTP verified! Waiting for admin approval')
            return redirect('account:login')
        else:
            messages.error(request, 'Invalid OTP')

    return render(request, 'verify_otp.html', {
        'user': user
    })

def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            username = request.POST.get('username')
            email = request.POST.get('email')
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')
            phone_number = form.cleaned_data['phone_number']
            otp = str(random.randint(100000, 999999))

            # Basic validation
            if not username or not email or not password1 or not password2:
                messages.error(request, 'All fields are required')
                return redirect('account:register')

            if password1 != password2:
                messages.error(request, 'Passwords do not match')
                return redirect('account:register')

            if User.objects.filter(username=username).exists():
                messages.error(request, 'Username already exists')
                return redirect('account:register')

            if User.objects.filter(email=email).exists():
                messages.error(request, 'Email already exists')
                return redirect('account:register')

            # Create user
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password1']
            )

            # Create profile
            UserProfile.objects.create(
                user=user,
                phone_number=phone_number,
                otp=otp,
                otp_created_at=timezone.now()
            )

            try:
                # Send OTP via Email
                send_mail(
                    'Your Verification OTP',
                    f'Your OTP code is: {otp}',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error(f"Error sending email: {str(e)}")
                # Clean up the created user and profile
                user.delete()
                messages.error(request, 'Error sending OTP. Please check your email address or try again later.')
                return redirect('account:register')

            messages.success(request, 'Registration successful! Please verify your OTP')
            return redirect('account:verify_otp', user_id=user.id)

        else:
            for error in form.errors.values():
                messages.error(request, error)
            return render(request, 'register.html', {'form': form})

    form = RegistrationForm()
    return render(request, 'register.html', {'form': form})

def logout_view(request):
    if request.user.is_authenticated:
        from .models import UserActivityLog
        UserActivityLog.objects.create(
            user=request.user,
            action='logout',
            details="User logged out"
        )
    logout(request)
    return redirect('account:login')

@login_required
def home(request):
    if request.user.is_superuser:
        return redirect('management:dashboard')
    return redirect('management:unit_list')

def resend_otp(request, user_id):
    user = get_object_or_404(User, id=user_id)
    profile = user.userprofile

    try:
        # Generate new OTP
        new_otp = str(random.randint(100000, 999999))
        profile.otp = new_otp
        profile.otp_created_at = timezone.now()
        profile.save()

        # Resend email
        send_mail(
            'Your New Verification OTP',
            f'Your new OTP code is: {new_otp}',
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )

        return JsonResponse({'success': True})

    except Exception as e:
        logger.error(f"Error resending OTP: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

