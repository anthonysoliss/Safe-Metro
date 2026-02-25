from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.files.base import ContentFile
import json
import io
from .models import UserLocation, Rating, Station, RatingPhoto, UserProfile, Feedback

def map_view(request):
    """Main map page view"""
    avatar_url = ''
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            if profile.avatar and hasattr(profile.avatar, 'url'):
                avatar_url = profile.avatar.url
        except (UserProfile.DoesNotExist, ValueError):
            pass
    
    context = {
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else None,
        'avatar_url': avatar_url,
    }
    return render(request, 'ratemetroapp/map.html', context)

def station_reviews_view(request):
    """Station reviews page — station name passed via ?station= query param"""
    return render(request, 'ratemetroapp/station-reviews.html')

def sign_in_view(request):
    """Sign in page view"""
    if request.user.is_authenticated:
        next_url = request.GET.get('next', 'ratemetroapp:map')
        return redirect(next_url)
    return render(request, 'ratemetroapp/sign-in.html')

@login_required
def profile_view(request):
    """User profile page view"""
    # Get or create user profile
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    # Get user's ratings from database
    user_ratings = Rating.objects.filter(user=request.user).select_related('station').order_by('-created_at')[:10]
    
    # Get activity data for the past 12 months
    from datetime import datetime, timedelta
    from django.utils import timezone
    from collections import defaultdict
    
    # Calculate activity by month for the past 12 months
    activity_by_month = defaultdict(int)
    twelve_months_ago = timezone.now() - timedelta(days=365)
    recent_ratings = Rating.objects.filter(
        user=request.user,
        created_at__gte=twelve_months_ago
    )
    
    for rating in recent_ratings:
        month_key = rating.created_at.strftime('%Y-%m')
        activity_by_month[month_key] += 1
    
    # Convert ratings to JSON-serializable format
    ratings_data = []
    for rating in user_ratings:
        ratings_data.append({
            'station': rating.station.name,
            'safety': rating.safety,
            'cleanliness': rating.cleanliness,
            'staff': rating.staff_present,
            'timestamp': int(rating.created_at.timestamp() * 1000),  # Convert to milliseconds
            'description': rating.description or '',
        })
    
    # Prepare activity data for the grid (last 12 months, oldest to newest)
    # The grid displays months from left to right: F M A M J J A S O N D J (Feb through Jan)
    activity_data = []
    current_date = timezone.now()
    for i in range(11, -1, -1):  # Go from 11 months ago to current month
        month_date = current_date - timedelta(days=30 * i)
        month_key = month_date.strftime('%Y-%m')
        count = activity_by_month.get(month_key, 0)
        activity_data.append(count)
    
    # Get user's rating stats
    user_ratings_count = Rating.objects.filter(user=request.user).count()
    user_stations_count = Rating.objects.filter(user=request.user).values('station').distinct().count()
    
    # Check achievements
    achievements = {
        'first_star': user_ratings_count >= 1,
        'explorer': user_stations_count >= 10,
        'on_fire': False,  # Would need streak calculation
        'champion': user_stations_count >= 25,
        'line_rider': False,  # Would need to check all A line stations
        'photog': RatingPhoto.objects.filter(rating__user=request.user).count() >= 3,
        'regular': False,  # Would need to check same station 5 times
        'diamond': False,  # Would need 30-day streak calculation
    }
    
    # Get user's full name (first_name + last_name, or username if no name)
    full_name = request.user.get_full_name() or request.user.username
    if not full_name or full_name == request.user.username:
        full_name = request.user.first_name or request.user.username
    
    # Get avatar URL
    avatar_url = ''
    if user_profile.avatar and hasattr(user_profile.avatar, 'url'):
        try:
            avatar_url = user_profile.avatar.url
        except ValueError:
            avatar_url = ''
    
    import json
    context = {
        'is_authenticated': True,
        'user': request.user,
        'user_profile': user_profile,
        'full_name': full_name,
        'email': request.user.email,
        'username': request.user.username,
        'ratings_count': user_ratings_count,
        'stations_count': user_stations_count,
        'ratings_json': json.dumps(ratings_data),
        'activity_json': json.dumps(activity_data),
        'achievements': achievements,
        'avatar_url': avatar_url,
    }
    return render(request, 'ratemetroapp/profile.html', context)

@login_required
def my_ratings_view(request):
    """My ratings page view"""
    # Get user's ratings from database
    user_ratings = Rating.objects.filter(user=request.user).select_related('station').order_by('-created_at')
    
    # Convert ratings to JSON-serializable format
    ratings_data = []
    for rating in user_ratings.prefetch_related('photos'):
        # Get station lines
        station_lines = list(rating.station.lines.values_list('code', flat=True))

        # Collect attached media
        media = []
        for m in rating.photos.all():
            if m.media_type == 'video' and m.video:
                try:
                    media.append({'type': 'video', 'url': m.video.url})
                except ValueError:
                    pass
            elif m.media_type == 'photo' and m.photo:
                try:
                    media.append({'type': 'photo', 'url': m.photo.url})
                except ValueError:
                    pass

        ratings_data.append({
            'id': rating.id,
            'station': rating.station.name,
            'lines': station_lines,
            'safety': rating.safety,
            'cleanliness': rating.cleanliness,
            'staff': rating.staff_present or '',
            'description': rating.description or '',
            'media': media,
            'timestamp': int(rating.created_at.timestamp() * 1000),
        })
    
    # Get user's rating stats
    user_ratings_count = Rating.objects.filter(user=request.user).count()
    
    import json
    context = {
        'is_authenticated': True,
        'user': request.user,
        'ratings_json': json.dumps(ratings_data),
        'ratings_count': user_ratings_count,
    }
    return render(request, 'ratemetroapp/my-ratings.html', context)

@login_required
@never_cache
def settings_view(request):
    """Settings page view — also handles AJAX POST to update anonymous_ratings"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            if 'anonymous_ratings' in data:
                profile.anonymous_ratings = bool(data['anonymous_ratings'])
                profile.save()
            return JsonResponse({'status': 'success', 'anonymous_ratings': profile.anonymous_ratings})
        except (ValueError, json.JSONDecodeError) as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    context = {
        'is_authenticated': True,
        'user': request.user,
        'anonymous_ratings': profile.anonymous_ratings,
    }
    return render(request, 'ratemetroapp/settings.html', context)


def help_center_view(request):
    """Help Center page"""
    return render(request, 'ratemetroapp/help-center.html')


def terms_view(request):
    """Terms of Service page"""
    return render(request, 'ratemetroapp/terms.html')


@csrf_exempt
@require_http_methods(["POST"])
def api_update_settings(request):
    """API endpoint to update user settings (e.g. anonymous_ratings)"""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)
    try:
        data = json.loads(request.body)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if 'anonymous_ratings' in data:
            profile.anonymous_ratings = bool(data['anonymous_ratings'])
        profile.save()
        return JsonResponse({'status': 'success'})
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def update_location(request):
    """API endpoint to receive and store user location"""
    try:
        data = json.loads(request.body)
        latitude = float(data.get('latitude'))
        longitude = float(data.get('longitude'))
        
        # Ensure session exists for anonymous users
        if not request.session.session_key:
            request.session.create()
        
        # Get user if authenticated, otherwise use session
        user = request.user if request.user.is_authenticated else None
        session_id = request.session.session_key
        
        # Create location record
        UserLocation.objects.create(
            user=user,
            latitude=latitude,
            longitude=longitude,
            session_id=session_id
        )
        
        return JsonResponse({'status': 'success', 'message': 'Location updated'})
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["GET"])
def check_auth(request):
    """Check if user is authenticated"""
    avatar_url = ''
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            if profile.avatar and hasattr(profile.avatar, 'url'):
                avatar_url = profile.avatar.url
        except (UserProfile.DoesNotExist, ValueError):
            pass
    
    return JsonResponse({
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else None,
        'avatar_url': avatar_url,
    })

@csrf_exempt
@require_http_methods(["POST"])
def submit_rating(request):
    """API endpoint to submit a rating - requires authentication"""
    if not request.user.is_authenticated:
        return JsonResponse({
            'status': 'error',
            'message': 'Please sign in to submit ratings',
            'requires_auth': True
        }, status=401)

    try:
        # Support both multipart/form-data (with file) and JSON
        if request.content_type and 'multipart' in request.content_type:
            station_name = request.POST.get('station_name', '').strip()
            safety = int(request.POST.get('safety', 0))
            cleanliness = int(request.POST.get('cleanliness', 0))
            staff_present = request.POST.get('staff_present') or None
            description = request.POST.get('description', '').strip()
            lat = request.POST.get('lat')
            lng = request.POST.get('lng')
        else:
            data = json.loads(request.body)
            station_name = data.get('station_name', '').strip()
            safety = int(data.get('safety', 0))
            cleanliness = int(data.get('cleanliness', 0))
            staff_present = data.get('staff_present') or None
            description = data.get('description', '').strip()
            lat = data.get('lat')
            lng = data.get('lng')

        if not station_name:
            return JsonResponse({'status': 'error', 'message': 'station_name is required'}, status=400)
        if not (1 <= safety <= 5):
            return JsonResponse({'status': 'error', 'message': 'safety must be 1–5'}, status=400)
        if not (1 <= cleanliness <= 5):
            return JsonResponse({'status': 'error', 'message': 'cleanliness must be 1–5'}, status=400)

        # Validate media file if provided
        media_file = request.FILES.get('media')
        if media_file:
            content_type = media_file.content_type or ''
            if content_type.startswith('video/'):
                max_video_bytes = 150 * 1024 * 1024  # 150 MB ≈ 5 min mobile video
                if media_file.size > max_video_bytes:
                    return JsonResponse({'status': 'error', 'message': 'Video must be under 150 MB (approx. 5 minutes).'}, status=400)
            elif content_type.startswith('image/'):
                if media_file.size > 10 * 1024 * 1024:
                    return JsonResponse({'status': 'error', 'message': 'Photo must be under 10 MB.'}, status=400)
            else:
                return JsonResponse({'status': 'error', 'message': 'Only images and videos are allowed.'}, status=400)

        # Look up station by exact name, then case-insensitive fallback
        try:
            station = Station.objects.get(name=station_name)
        except Station.DoesNotExist:
            try:
                station = Station.objects.get(name__iexact=station_name)
            except Station.DoesNotExist:
                station = Station.objects.create(
                    name=station_name,
                    latitude=float(lat) if lat is not None else 0.0,
                    longitude=float(lng) if lng is not None else 0.0,
                )

        # Block duplicate ratings for authenticated users
        if Rating.objects.filter(station=station, user=request.user).exists():
            return JsonResponse({
                'status': 'error',
                'message': 'You have already rated this station.',
                'already_rated': True,
            }, status=409)

        # Create the rating
        rating = Rating.objects.create(
            station=station,
            user=request.user,
            safety=safety,
            cleanliness=cleanliness,
            staff_present=staff_present,
            description=description or None,
            ip_address=get_client_ip(request),
        )

        # Save media file if provided
        media_url = ''
        if media_file:
            content_type = media_file.content_type or ''
            if content_type.startswith('video/'):
                media_obj = RatingPhoto.objects.create(rating=rating, video=media_file, media_type='video')
                media_url = media_obj.video.url if media_obj.video else ''
            else:
                # Convert HEIC/HEIF to JPEG so all browsers can display it
                file_to_save = media_file
                filename = media_file.name or 'photo.jpg'
                if filename.lower().endswith(('.heic', '.heif')) or content_type in ('image/heic', 'image/heif'):
                    try:
                        import pillow_heif
                        from PIL import Image
                        pillow_heif.register_heif_opener()
                        img = Image.open(media_file)
                        buf = io.BytesIO()
                        img.save(buf, format='JPEG', quality=85)
                        buf.seek(0)
                        jpeg_name = filename.rsplit('.', 1)[0] + '.jpg'
                        file_to_save = ContentFile(buf.read(), name=jpeg_name)
                    except Exception:
                        media_file.seek(0)
                        file_to_save = media_file
                media_obj = RatingPhoto.objects.create(rating=rating, photo=file_to_save, media_type='photo')
                media_url = media_obj.photo.url if media_obj.photo else ''

        # Build avatar URL for the response
        avatar_url = ''
        try:
            profile = request.user.profile
            if profile.avatar and hasattr(profile.avatar, 'url'):
                avatar_url = profile.avatar.url
        except (UserProfile.DoesNotExist, ValueError):
            pass

        # Respect anonymous_ratings setting
        display_username = request.user.username
        display_avatar = avatar_url
        try:
            if request.user.profile.anonymous_ratings:
                display_username = 'Anonymous'
                display_avatar = ''
        except (UserProfile.DoesNotExist, AttributeError):
            pass

        return JsonResponse({
            'status': 'success',
            'message': 'Rating submitted successfully',
            'rating_id': rating.id,
            'timestamp': int(rating.created_at.timestamp() * 1000),
            'username': display_username,
            'avatar_url': display_avatar,
            'media_url': media_url,
        })
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@require_http_methods(["GET"])
def get_station_ratings(request):
    """Return all ratings for a station as JSON, newest first."""
    station_name = request.GET.get('station', '').strip()
    if not station_name:
        return JsonResponse({'status': 'error', 'message': 'station param required'}, status=400)

    try:
        station = Station.objects.get(name__iexact=station_name)
    except Station.DoesNotExist:
        return JsonResponse({'status': 'ok', 'ratings': [], 'summary': {'avg': 0, 'count': 0}})

    ratings_qs = (
        Rating.objects
        .filter(station=station)
        .select_related('user', 'user__profile')
        .prefetch_related('photos')
        .order_by('-created_at')
    )

    ratings_list = []
    safety_vals, clean_vals, staff_vals = [], [], []

    for r in ratings_qs:
        # Username + avatar — respect anonymous_ratings setting
        username = 'Anonymous'
        avatar_url = ''
        if r.user:
            try:
                if r.user.profile.anonymous_ratings:
                    username = 'Anonymous'
                    avatar_url = ''
                else:
                    username = r.user.username
                    if r.user.profile.avatar and hasattr(r.user.profile.avatar, 'url'):
                        avatar_url = r.user.profile.avatar.url
            except (UserProfile.DoesNotExist, AttributeError, ValueError):
                username = r.user.username

        # Collect attached media
        media = []
        for m in r.photos.all():
            if m.media_type == 'video' and m.video:
                try:
                    media.append({'type': 'video', 'url': m.video.url})
                except ValueError:
                    pass
            elif m.media_type == 'photo' and m.photo:
                try:
                    media.append({'type': 'photo', 'url': m.photo.url})
                except ValueError:
                    pass

        ratings_list.append({
            'id': r.id,
            'username': username,
            'avatar_url': avatar_url,
            'safety': r.safety,
            'cleanliness': r.cleanliness,
            'staff': r.staff_present or '',
            'description': r.description or '',
            'timestamp': int(r.created_at.timestamp() * 1000),
            'media': media,
        })

        safety_vals.append(r.safety)
        clean_vals.append(r.cleanliness)
        if r.staff_present:
            staff_vals.append(r.staff_present)

    # Build summary
    count = len(ratings_list)
    safety_avg = round(sum(safety_vals) / count, 1) if count else 0
    clean_avg  = round(sum(clean_vals)  / count, 1) if count else 0
    overall    = round((safety_avg + clean_avg) / 2, 1) if count else 0
    staff_pct  = None
    if staff_vals:
        yes_count = sum(1 for s in staff_vals if s == 'yes')
        staff_pct = 'Yes' if yes_count >= len(staff_vals) / 2 else 'No'

    user_has_rated = (
        request.user.is_authenticated and
        Rating.objects.filter(station=station, user=request.user).exists()
    )

    return JsonResponse({
        'status': 'ok',
        'ratings': ratings_list,
        'user_has_rated': user_has_rated,
        'summary': {
            'avg': overall,
            'count': count,
            'safety': safety_avg,
            'cleanliness': clean_avg,
            'staff': staff_pct,
        },
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_sign_in(request):
    """API endpoint for user sign in (accepts email or username)"""
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return JsonResponse({
                'status': 'error',
                'message': 'Email and password are required'
            }, status=400)
        
        # Try authenticating with input as username first
        user = authenticate(request, username=email, password=password)
        
        # If that fails, look up by email field
        if user is None:
            try:
                user_obj = User.objects.get(email=email)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                user = None
        
        if user is not None:
            login(request, user)
            return JsonResponse({
                'status': 'success',
                'message': 'Signed in successfully',
                'username': user.username
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid email or password'
            }, status=401)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def api_sign_up(request):
    """API endpoint for user sign up"""
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not name or not username or not email or not password:
            return JsonResponse({
                'status': 'error',
                'message': 'Name, username, email, and password are required'
            }, status=400)
        
        if len(password) < 8:
            return JsonResponse({
                'status': 'error',
                'message': 'Password must be at least 8 characters'
            }, status=400)
        
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return JsonResponse({
                'status': 'error',
                'message': 'Username can only contain letters, numbers, and underscores'
            }, status=400)
        
        if User.objects.filter(username=username).exists():
            return JsonResponse({
                'status': 'error',
                'message': 'This username is already taken'
            }, status=400)
        
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'status': 'error',
                'message': 'An account with this email already exists'
            }, status=400)
        
        # Split name into first/last
        name_parts = name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        login(request, user)

        from django.urls import reverse
        return JsonResponse({
            'status': 'success',
            'message': 'Account created successfully',
            'username': user.username,
            'redirect_url': reverse('ratemetroapp:map'),
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_logout(request):
    """API endpoint for user logout"""
    logout(request)
    return JsonResponse({
        'status': 'success',
        'message': 'Signed out successfully'
    })

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_delete_rating(request):
    """API endpoint to delete a rating"""
    try:
        data = json.loads(request.body)
        rating_id = data.get('rating_id')
        
        if not rating_id:
            return JsonResponse({
                'status': 'error',
                'message': 'Rating ID is required'
            }, status=400)
        
        # Get the rating and verify it belongs to the user
        try:
            rating = Rating.objects.get(id=rating_id, user=request.user)
            rating.delete()
            return JsonResponse({
                'status': 'success',
                'message': 'Rating deleted successfully'
            })
        except Rating.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Rating not found or you do not have permission to delete it'
            }, status=404)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def api_delete_account(request):
    """API endpoint for account deletion"""
    try:
        # Delete user's ratings
        Rating.objects.filter(user=request.user).delete()
        
        # Delete user's profile
        try:
            UserProfile.objects.filter(user=request.user).delete()
        except:
            pass
        
        # Delete user's location data
        UserLocation.objects.filter(user=request.user).delete()
        
        # Delete the user account
        user = request.user
        logout(request)
        user.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Account deleted successfully'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)

@login_required
@require_http_methods(["POST"])
def api_update_profile(request):
    """Update user profile including avatar"""
    try:
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        
        # Handle avatar upload (sent as a file via multipart form)
        if 'avatar' in request.FILES:
            avatar_file = request.FILES['avatar']
            if avatar_file.size > 5 * 1024 * 1024:
                return JsonResponse({'status': 'error', 'message': 'Avatar must be less than 5MB'}, status=400)
            profile.avatar = avatar_file
        
        # Handle text fields
        name = request.POST.get('name', '').strip()
        if name:
            parts = name.split(' ', 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ''
        
        email = request.POST.get('email', '').strip()
        if email:
            user.email = email
        
        username = request.POST.get('username', '').strip().lstrip('@')
        if username and username != user.username:
            if User.objects.filter(username=username).exclude(pk=user.pk).exists():
                return JsonResponse({'status': 'error', 'message': 'Username already taken'}, status=400)
            user.username = username
        
        user.save()
        profile.save()
        
        avatar_url = ''
        if profile.avatar and hasattr(profile.avatar, 'url'):
            try:
                avatar_url = profile.avatar.url
            except ValueError:
                avatar_url = ''
        
        return JsonResponse({
            'status': 'success',
            'message': 'Profile updated',
            'avatar_url': avatar_url,
            'full_name': user.get_full_name() or user.username,
            'username': user.username,
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


def privacy_policy_view(request):
    """Privacy policy page"""
    return render(request, 'ratemetroapp/privacy-policy.html')


def feedback_view(request):
    """Feedback form page"""
    success = False
    error = None
    form_data = {}

    default_email = request.user.email if request.user.is_authenticated else ''

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        category = request.POST.get('category', 'general')
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        form_data = {'email': email, 'category': category, 'subject': subject, 'message': message}

        if not email or not subject or not message:
            error = 'Please fill in all required fields.'
        elif len(subject) > 200:
            error = 'Subject must be 200 characters or fewer.'
        elif len(message) > 5000:
            error = 'Message must be 5000 characters or fewer.'
        else:
            feedback = Feedback.objects.create(
                user=request.user if request.user.is_authenticated else None,
                email=email,
                category=category,
                subject=subject,
                message=message,
            )
            from django.core.mail import send_mail
            from django.conf import settings as django_settings
            recipient = getattr(django_settings, 'FEEDBACK_EMAIL', 'feedback@ratemetro.com')
            send_mail(
                subject=f'[RateMetro Feedback] {feedback.get_category_display()}: {subject}',
                message=f'From: {email}\nCategory: {feedback.get_category_display()}\nUser: {request.user.username if request.user.is_authenticated else "Guest"}\n\n{message}',
                from_email=email,
                recipient_list=[recipient],
                fail_silently=True,
            )
            success = True
            form_data = {}

    context = {
        'success': success,
        'error': error,
        'form_data': form_data,
        'default_email': default_email,
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else None,
    }
    return render(request, 'ratemetroapp/feedback.html', context)


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
