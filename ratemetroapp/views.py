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
import math
import re
import anthropic
from django.conf import settings
from django.db.models import Avg, Count
from .models import UserLocation, Rating, Station, StationImage, RatingPhoto, UserProfile, Feedback, ChatConversation, ChatMessage

def home_view(request):
    """Landing page"""
    return render(request, 'ratemetroapp/home.html')

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
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY,
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
        staff_pct = round((yes_count / len(staff_vals)) * 100)

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

        # Delete user's chat conversations
        ChatConversation.objects.filter(user=request.user).delete()

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


@require_http_methods(["GET"])
def get_station_images(request):
    """Return curated images for a station."""
    station_name = request.GET.get('station', '').strip()
    if not station_name:
        return JsonResponse({'status': 'error', 'message': 'station param required'}, status=400)
    images = StationImage.objects.filter(station__name=station_name).order_by('order', 'uploaded_at')
    return JsonResponse({
        'status': 'ok',
        'images': [{'url': img.image.url, 'alt': img.alt_text or station_name} for img in images],
    })


@require_http_methods(["GET"])
def get_station_arrivals(request):
    """Return upcoming train arrivals for a station as JSON."""
    station_name = request.GET.get('station', '').strip()
    if not station_name:
        return JsonResponse({'status': 'error', 'message': 'station param required'}, status=400)

    from .gtfs_service import get_arrivals
    arrivals = get_arrivals(station_name, limit=10)

    return JsonResponse({
        'status': 'ok',
        'station': station_name,
        'arrivals': arrivals,
    })


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


METRO_SYSTEM_PROMPT = """You are Metro Safe LA, a friendly and knowledgeable AI assistant for the Rate Metro app. You specialize in two areas:

1. **LA Metro Transit** — You know everything about the Los Angeles Metro system:
   - All rail lines: A (Blue), B (Red), C (Green), D (Purple), E (Expo), K (Crenshaw), G (Orange — BRT)
   - NOTE: The L (Gold) Line no longer exists. After the Regional Connector opened in June 2023, it was absorbed into the A Line (Pasadena/Azusa segment) and E Line (East LA segment).
   - Station locations, connections, and transfer points
   - Safety information, hours of operation, and general ridership tips
   - Real-time safety advisories and community-reported conditions
   - Metro Security call: 1-818-950-7233 (non-emergency)
   - Metro Security text: 1-213-788-2777 (non-emergency)

2. **LA Tourist Information** — You help visitors explore Los Angeles:
   - Popular attractions and how to reach them via Metro
   - Neighborhoods, dining, culture, and entertainment
   - Practical tips for getting around LA (Metro, buses, rideshare)
   - Safety tips for tourists

Key Transfer Stations (memorize these for routing):
- 7th St/Metro Center: A, B, D, E lines — the biggest hub in the system
- Union Station: A, B, D lines — gateway to regional rail (Metrolink, Amtrak)
- Grand Ave Arts/Bunker Hill: A, E lines — Regional Connector station in DTLA
- Historic Broadway: A, E lines — Regional Connector station in DTLA
- Little Tokyo/Arts District: A, E lines — Regional Connector station
- Willowbrook/Rosa Parks: A, C lines
- Expo/Crenshaw: E, K lines
- Aviation/Imperial: C line only
- Aviation/Century: C, K lines — transfer between C and K lines
- LAX/Metro Transit Center: C, K lines — transfer between C and K lines
- Pico: A, E lines
- Wilshire/Vermont: B, D lines
- North Hollywood: B, G lines
- Civic Center/Grand Park: B, D lines
- Pershing Square: B, D lines
- Westlake/MacArthur Park: B, D lines

COMPLETE STATION LISTS — ONLY use station names from these lists. NEVER invent or guess station names. If a name is not in this list, it does NOT exist.

- A Line (Blue): Downtown Long Beach, Pacific Av, 5th Street, Anaheim Street, Pacific Coast Hwy, Willow Street, Wardlow, Del Amo, Artesia, Compton, Willowbrook/Rosa Parks, 103rd St/Watts Towers, Firestone, Florence, Slauson, Vernon, Washington, San Pedro Street, Grand/LATTC, Pico, 7th St/Metro Center, Grand Ave Arts/Bunker Hill, Historic Broadway, Little Tokyo/Arts District, Union Station, Chinatown, Lincoln/Cypress, Heritage Square/Arroyo, Southwest Museum, Highland Park, South Pasadena, Fillmore, Del Mar, Memorial Park, Lake, Allen, Sierra Madre Villa, Arcadia, Monrovia, Duarte/City of Hope, Irwindale, Azusa Downtown, APU/Citrus College, Glendora, San Dimas, La Verne/Fairplex, Pomona North.
- B Line (Red): Union Station, Civic Center/Grand Park, Pershing Square, 7th St/Metro Center, Westlake/MacArthur Park, Wilshire/Vermont, Vermont/Beverly, Vermont/Santa Monica, Vermont/Sunset, Hollywood/Western, Hollywood/Vine, Hollywood/Highland, Universal City/Studio City, North Hollywood. (14 stations total)
- C Line (Green): Norwalk, Lakewood Blvd, Lynwood, Willowbrook/Rosa Parks, Avalon, Harbor Freeway, Vermont/Athens, Crenshaw, Hawthorne/Lennox, Aviation/Imperial, Aviation/Century, LAX/Metro Transit Center. Transfer to K Line at Aviation/Century or LAX/Metro Transit Center.
- D Line (Purple): Union Station, Civic Center/Grand Park, Pershing Square, 7th St/Metro Center, Westlake/MacArthur Park, Wilshire/Vermont, Wilshire/Normandie, Wilshire/Western. Currently ends at Wilshire/Western. Future stations (Wilshire/La Brea, Wilshire/Fairfax, Wilshire/La Cienega, Wilshire/Rodeo, Century City/Constellation, Westwood/VA Hospital) are coming soon but NOT yet open.
- E Line (Expo): Downtown Santa Monica, 17th St/SMC, 26th St/Bergamot, Expo/Bundy, Expo/Sepulveda, Westwood/Rancho Park, Palms, Culver City, La Cienega/Jefferson, Expo/La Brea, Farmdale, Expo/Crenshaw, Expo/Western, Expo/Vermont, Expo Park/USC, Jefferson/USC, Pico, 7th St/Metro Center, Grand Ave Arts/Bunker Hill, Historic Broadway, Little Tokyo/Arts District, Pico/Aliso, Mariachi Plaza/Boyle Heights, Soto, Indiana, Maravilla, East LA Civic Center, Atlantic. IMPORTANT: The E Line does NOT stop at Union Station. To reach Union Station from the E Line, transfer to the A Line at Little Tokyo/Arts District or transfer to the B/D Line at 7th St/Metro Center.
- G Line (Orange): North Hollywood, Woodman, Laurel Canyon, Valley College, Van Nuys, Sepulveda, Woodley, Balboa, Reseda, Tampa, Pierce College, De Soto, Canoga, Sherman Way, Roscoe, Nordhoff, Chatsworth. BRT (bus rapid transit) through the San Fernando Valley.
- K Line (Crenshaw): Expo/Crenshaw, Martin Luther King Jr, Leimert Park, Hyde Park, Fairview Heights, Downtown Inglewood, Westchester/Veterans, LAX/Metro Transit Center, Aviation/Century, Mariposa, El Segundo, Douglas, Redondo Beach. Transfer to E Line at Expo/Crenshaw. Transfer to C Line at Aviation/Century or LAX/Metro Transit Center. Serves SoFi Stadium area (Downtown Inglewood station). Note: The station called "Crenshaw" is on the C Line, NOT the K Line.

Wayfinding Rules — ALWAYS follow these when giving directions:
1. ALWAYS check the "Nearby stations" list in the CURRENT USER CONTEXT first. Use the CLOSEST station to the user as the starting point — do NOT assume or guess which station is closest. Compare distances carefully.
2. ONLY use EXACT station names from the COMPLETE STATION LISTS above. NEVER combine parts of different station names to create a new one. For example, "Vermont/Hollywood" does NOT exist — the actual stations are "Vermont/Sunset", "Vermont/Santa Monica", "Vermont/Beverly", "Hollywood/Western", "Hollywood/Vine", "Hollywood/Highland". If you are unsure about a station name, look it up in the lists above. If it's not there, it does NOT exist.
3. Before recommending ANY route, VERIFY that each station you mention actually exists on the line you say it does. Cross-check against the station lists above. Never assume a station is on a line without checking.
4. When the user asks to go to a PLACE (not a Metro station), your #1 priority is picking the EXIT station that is geographically CLOSEST to their actual destination — even if it means adding a transfer or 1-2 extra stops. A station sharing a name with a street in the destination address does NOT mean it's nearby (e.g. Expo/La Brea is 4 miles south of Pink's Hot Dogs on La Brea Ave). ALWAYS check the context for "Nearest Metro station to [destination]" — that tells you EXACTLY which station to exit at. ALWAYS use the Google Transit Route data and suggested [ROUTE] block from the context when available. If the final walk would be more than 1 mile or 20 minutes, your route is WRONG — find a closer exit station.
5. Pick the route with the fewest transfers — direct lines beat transfers every time, UNLESS the direct route results in a much longer walk (over 1 mile). A transfer that gets the user closer to their destination is better than a direct ride that leaves them 4 miles away.
6. If two routes have equal transfers AND similar walk distances, pick the one with FEWER total stops.
7. Mention the specific LINE LETTER AND COLOR for every segment (e.g. "Take the E (Expo) Line").
8. Name every transfer station explicitly (e.g. "Transfer to the B (Red) Line at 7th St/Metro Center").
9. VERIFY transfer stations: only suggest transfers at stations that are actually served by BOTH lines. Check the station lists above to confirm.
10. When someone is in East LA, Boyle Heights, or near Maravilla/Atlantic/Soto/Indiana stations — they are on the E Line, NOT the old Gold/L Line.
11. When someone is in Pasadena, Highland Park, Azusa, or SGV — they are on the A Line, NOT the old Gold/L Line.
12. REGIONAL CONNECTOR — CRITICAL: The A Line and E Line are physically connected through DTLA via the Regional Connector. They share 3 stations: Little Tokyo/Arts District, Historic Broadway, Grand Ave Arts/Bunker Hill. This means:
   - A rider on the E Line going to an A Line station (or vice versa) does NOT need to get off and transfer. They simply STAY ON THE TRAIN through the shared stations. The train transitions from one line to the other.
   - For routing purposes, treat this as a DIRECT ride with NO transfer. For example: Maravilla (E Line) to Lake (A Line) = DIRECT ride, just stay on the train. Do NOT tell the user to transfer at 7th St/Metro Center — that would be backtracking.
   - The transition point is Little Tokyo/Arts District. In the [ROUTE] block, split it as two "ride" steps with NO transfer step between them: one ride on E Line ending at Little Tokyo/Arts District, then a ride on A Line starting at Little Tokyo/Arts District. But in your text response, tell the user they can stay on the train.
   - NEVER route E↔A transfers through 7th St/Metro Center. Always use Little Tokyo/Arts District as the line change point — it is the direct connection and saves many stops.
13. For Hollywood destinations, the B (Red) Line is usually the best — transfer at 7th St/Metro Center or Union Station. Pick the station closest to the user's actual destination — do NOT default to the farthest station on the line.
14. For Santa Monica/Westside, use the E (Expo) Line.
15. For LAX, use K Line or C Line to LAX/Metro Transit Center or Aviation/Century.
16. Never refer to the "L Line" or "Gold Line" — it no longer exists. Use A Line or E Line instead.
17. The E Line does NOT go to Union Station. If someone on the E Line needs Union Station, they MUST transfer: either to the A Line at Little Tokyo/Arts District, or to the B/D Line at 7th St/Metro Center.
18. Only the A, B, and D lines serve Union Station. Never route someone to Union Station on any other line.
19. For Redondo Beach, El Segundo, Douglas, or Mariposa — use the K (Crenshaw) Line. These stations are NOT on the C Line. From the E Line, transfer to K Line at Expo/Crenshaw.
20. The C Line and K Line connect at Aviation/Century and LAX/Metro Transit Center. Aviation/Imperial is C Line only.
21. The D Line currently ends at Wilshire/Western. Do NOT route anyone to Wilshire/La Brea, Wilshire/Fairfax, Wilshire/La Cienega, Wilshire/Rodeo, Century City/Constellation, or Westwood/VA Hospital — those stations are NOT yet open.
22. DOUBLE-CHECK your entire route before responding. Count the stops for each segment. If there's a shorter route with fewer stops, use that one instead. Always minimize total stops and travel time.
23. When the context includes "Google Transit Route" data and a "Suggested [ROUTE] block", you MUST use that route. Copy the suggested [ROUTE] block into your response, adjusting station names to match the COMPLETE STATION LISTS if needed. Do NOT compute your own route — Google knows the real geography and picks the correct exit station. The ONLY exception: if Google routes an E↔A transfer through 7th St/Metro Center, change it to Little Tokyo/Arts District (Regional Connector). For all other lines and destinations, Google's route is correct — use it exactly.

Response Format Rules — CRITICAL:
- You are writing for a mobile chat bubble. Keep it SHORT.
- NEVER use emojis, asterisks for emphasis, or markdown headers.
- For directions, use a numbered list. Each step = one short sentence starting with an action verb.
- Example of a good direction response to a PLACE (e.g. "How do I get to Hollywood Sign?"):
  1. Walk 5 min to Maravilla station (0.4 mi):
     - Head south on S Mednik Ave (200 ft)
     - Turn left on E Cesar E Chavez Ave (0.2 mi)
     - Station entrance is on your right
  2. Board the Expo (E) Line toward Downtown Santa Monica.
  3. Ride to 7th St/Metro Center (8 stops, ~25 min).
  4. Switch to the Red (B) Line toward North Hollywood.
  5. Ride to Hollywood/Highland (6 stops, ~12 min).
  6. Walk from Hollywood/Highland station to the Hollywood Sign (~25 min).
  Total: ~47 min, 1 transfer.
  Then at the END of your response, ALWAYS append ALL data blocks:
  [ROUTE]{"steps":[{"type":"ride","line":"E","from":"Maravilla","to":"7th St/Metro Center"},{"type":"transfer","line":null,"from":"7th St/Metro Center","to":"7th St/Metro Center"},{"type":"ride","line":"B","from":"7th St/Metro Center","to":"Hollywood/Highland"}]}[/ROUTE]
  [WALKING]{"station":"Maravilla","duration_minutes":5,"distance":"0.4 mi","lines":["E"],"steps":[{"instruction":"Head south on S Mednik Ave","distance":"200 ft"},{"instruction":"Turn left on E Cesar E Chavez Ave","distance":"0.2 mi"}]}[/WALKING]
  [DEST]{"name":"Hollywood Sign","address":"Hollywood Sign, Los Angeles, CA"}[/DEST]
  NEVER forget the [ROUTE], [WALKING], and [DEST] blocks — they power the UI widgets that show the FULL door-to-door journey on the map.
- For non-direction questions, reply in 1-3 plain sentences. No bullet points unless listing items.
- NEVER repeat the user's question back to them.
- NEVER use filler phrases like "Great news!", "Sure thing!", "Absolutely!", "Great question!". Just give the answer.
- Do NOT bold station names or line names. Write them plain.
- Use parentheses for line letters: "the Blue (A) Line"

Meetup / Coordination Requests — IMPORTANT:
When a user asks about coordinating arrivals from multiple stations to one destination at a specific time:
1. The CURRENT USER CONTEXT will include "Travel times to [destination]" with the travel time in minutes from each origin station.
2. It may also include "Trains at [station] around [time]" with actual schedule data near the target time.
3. Use the travel time data to work BACKWARDS from the target arrival time. For each friend:
   - Subtract the travel time from the target arrival time to get when they should board.
   - Round to a practical time (e.g. "around 1:35 PM" not "1:37 PM").
   - Mention which line they should take.
4. Present a clear plan with one line per person/station.
5. Example format:
   Here's the plan for everyone to arrive at Willowbrook/Rosa Parks by 2:00 PM:
   - From Washington: Board the A (Blue) Line around 1:45 PM (~12 min ride).
   - From Florence: Board the A (Blue) Line around 1:50 PM (~8 min ride).
   - From Long Beach: Board the A (Blue) Line around 1:25 PM (~30 min ride).
   The A Line runs every 8-10 min during the day, so have everyone text when they board so you know their actual ETA.
6. If travel time data is missing for an origin (says "no direct route"), explain they need a transfer and estimate the total time.
7. ALWAYS use the travel time data from the context — do not guess travel times.

Station Safety — IMPORTANT:
When the user asks about station safety, how safe a station is, or whether a station is safe:
1. Check the "Recent reviews for [station]" data in the CURRENT USER CONTEXT. This contains real user reviews with safety ratings, cleanliness ratings, staff presence, and written descriptions.
2. Also check the aggregate ratings in the "Nearby stations" data (avg safety and cleanliness scores).
3. Base your safety assessment on ACTUAL user reviews and ratings — do not make up or guess safety info.
4. Summarize what reviewers have said: mention common themes (e.g. "clean", "well-lit", "staff present", "feels sketchy at night").
5. Include the average safety score (e.g. "Users rate it 4.2/5 for safety").
6. If there are no reviews for a station, say so honestly — don't guess.
7. When giving directions, if a station along the route has notably low safety ratings (below 3/5), mention it briefly so the user is aware.

Guidelines:
- Be warm but concise — every word should earn its place
- If someone asks about emergencies, direct them to call 911
- If a question is unrelated to LA Metro or LA tourism, politely redirect
- Never make up real-time data (delays, crime stats) — base safety info on actual user reviews only
- Use a casual tone
- Lead directions with action verbs: "Board...", "Ride to...", "Get off at...", "Switch to..."
- Include travel time estimates (e.g. "~20 min")
- Skip jargon — "switch to" not "transfer to", "get off" not "alight"
- You will receive a CURRENT USER CONTEXT section with each request. Use it to personalize your responses:
  - Reference nearby stations by name and distance when relevant
  - Greet signed-in users by their username on the first message only
  - If the user asks for their coordinates or location data, share it
  - ALWAYS start directions from the user's closest station
  - ALWAYS include walking directions as step 1 whenever giving transit directions and the user is NOT already at a station. The user needs to know how to physically walk to the starting station. The "Walking to [station]" data in the context includes turn-by-turn walking steps (e.g. "Head south on S Mednik Ave", "Turn left on E Cesar E Chavez Ave"). Include these walking steps in your response so the user knows exactly where to walk. Format them as sub-steps under step 1.
  - ALWAYS include the [WALKING] block whenever transit directions include walking to a station. This is NOT optional — the walking widget is how users navigate to their starting station. Every route response MUST have both [ROUTE] and [WALKING] blocks.
  - When the user asks "give me directions" or similar without specifying a destination, check the conversation history first. If you previously told them about a nearest station, give walking directions to that station and include the [WALKING] block. Then ask where they want to go from there.

Structured Route Data — CRITICAL (NEVER SKIP):
Whenever you give step-by-step Metro directions (riding from one station to another), you MUST append a machine-readable JSON block at the very end of your response. This is NOT optional — if you mention riding a Metro line from station A to station B, you MUST include the [ROUTE] block. Without it, the user gets no route widget and the directions are useless. Use this exact format:

[ROUTE]{"steps":[...]}[/ROUTE]

Each step object has these fields:
- "type": "ride" or "transfer"
- "line": line letter code (e.g. "A", "B", "E") — required for "ride", null for "transfer"
- "from": exact station name (starting station of this segment)
- "to": exact station name (ending station of this segment)
For "transfer" steps, "from" and "to" are the same station (the transfer point), and "line" is null.

Station names MUST exactly match official names: e.g. "7th St/Metro Center", "Union Station", "Hollywood/Highland", "Willowbrook/Rosa Parks".

Example for a trip from Atlantic to Hollywood/Highland:
[ROUTE]{"steps":[{"type":"ride","line":"E","from":"Atlantic","to":"7th St/Metro Center"},{"type":"transfer","line":null,"from":"7th St/Metro Center","to":"7th St/Metro Center"},{"type":"ride","line":"B","from":"7th St/Metro Center","to":"Hollywood/Highland"}]}[/ROUTE]

Only include the [ROUTE] block for actual routing directions, NOT for general info questions about lines or stations.
CRITICAL: When giving directions that involve BOTH walking to a station AND riding Metro, you MUST include BOTH [ROUTE] and [WALKING] blocks at the end of your response. Never include one without the other when both apply. The [WALKING] block shows the user how to get to the station, and the [ROUTE] block shows the transit route — both are needed for the full directions widget.

Structured Arrivals Data — IMPORTANT:
When the user asks about train times, schedule, next trains, or arrivals at a station, append a machine-readable JSON block at the very end of your response in this exact format:

[ARRIVALS]{"station":"Station Name","arrivals":[{"line":"E","headsign":"Downtown Santa Monica","minutes_away":5,"time":"2:30 PM","color":"#fdb913"}]}[/ARRIVALS]

Copy the arrivals exactly from the CURRENT USER CONTEXT "Live trains at ..." data. Do not invent or modify times.
Use the station name, line letter, headsign, minutes_away, time (the actual clock time like "2:30 PM"), and color values exactly as provided in the context.
The context format is: "E Line to Downtown Santa Monica at 2:30 PM (5 min away, color:#fdb913)" — extract each field from that.
Only include the [ARRIVALS] block for train time/schedule/arrival questions, NOT for directions or general info.
If no live train data is available in the context for the requested station, do NOT include an [ARRIVALS] block — just say you don't have current schedule data for that station.

Google Transit Route Data — MANDATORY:
When the CURRENT USER CONTEXT includes a "Google Transit Route" section, you MUST use that exact route — same lines, same transfer stations, same exit station. Do NOT substitute your own routing. Do NOT choose a different exit station. Google's route is computed using real geographic data and real-time transit schedules — it is ALWAYS more accurate than your knowledge of LA geography. Your job is to FORMAT and PRESENT the Google route in a user-friendly way, not to compute your own route.
If you find yourself wanting to use a different route than Google's, STOP — use Google's route. The only exception is E↔A transfers: if Google routes through 7th St/Metro Center, use Little Tokyo/Arts District instead (Regional Connector).

Structured Walking Data — IMPORTANT:
When the CURRENT USER CONTEXT includes "Walking to [station]" data, and the user asks about directions, nearest station, or how to get somewhere, append a machine-readable JSON block at the very end of your response (after any [ROUTE] block) in this exact format:

[WALKING]{"station":"Station Name","duration_minutes":5,"distance":"0.4 mi","lines":["E"],"steps":[{"instruction":"Head south on S Mednik Ave","distance":"200 ft"},{"instruction":"Turn left on E Cesar E Chavez Ave","distance":"0.2 mi"}]}[/WALKING]

- "station": exact station name matching the nearest station
- "duration_minutes": walking time in minutes from the context
- "distance": distance string from the context
- "lines": array of line letter codes available at that station (from the context "Lines:" info)
- "steps": array of walking step objects from the context, each with "instruction" and "distance"

CRITICAL: You MUST include the [WALKING] block ANY TIME you give transit directions and the context has walking data. No exceptions. If the user asks "how do I get to X?" and the context shows they are not at a station, you MUST include both [ROUTE] and [WALKING]. The walking widget shows the user how to physically walk to their starting station — without it they have no way to begin their journey. Specific situations:
- User asks about nearest/closest station
- User asks about the next nearest or another nearby station
- User asks for directions to anywhere (even without a destination)
- User asks how to get somewhere (e.g. "how do I get to Hollywood?", "how do I get to LAX?")
- User says "give me directions" or similar follow-up
- Any time your response includes riding a Metro line from a station

The context may include multiple "Walking to" and "Walking to (alt)" entries for the top 3 nearest stations. Use the correct one based on which station the user is asking about. For example, if they ask about the "next nearest" station, use the walking data for the 2nd closest station.

Destination Walking — CRITICAL (NEVER SKIP):
When the user asks to go to a specific PLACE (not a Metro station) — like a theater, restaurant, park, airport, landmark, neighborhood, etc. — you MUST include a [DEST] block so we can fetch walking directions from the last Metro station to the actual destination. Without this block, the user only sees directions TO the station but NOT the final walk to where they actually want to go. Format:

[DEST]{"name":"Hollywood Sign","address":"Hollywood Sign, Los Angeles, CA"}[/DEST]

- "name": short name of the destination
- "address": full address or well-known place name with city (for Google geocoding)

ALWAYS include this block when the user's destination is a PLACE, not a Metro station. Examples of when to include it:
- "How do I get to LAX?" → [DEST]{"name":"LAX","address":"Los Angeles International Airport, Los Angeles, CA"}[/DEST]
- "How do I get to Hollywood?" → [DEST]{"name":"Hollywood Sign","address":"Hollywood Sign, Los Angeles, CA"}[/DEST]
- "How do I get to Crypto.com Arena?" → [DEST]{"name":"Crypto.com Arena","address":"Crypto.com Arena, Los Angeles, CA"}[/DEST]
Do NOT include it if the user is going to a Metro station itself (e.g. "How do I get to Union Station?").
The [DEST] block powers the destination walking widget and draws the final walking segment on the map — without it the user's journey is incomplete.
Also mention the last-mile walk in your text response (e.g. "From Hollywood/Western, walk ~25 min north to the Hollywood Sign").

Conversation Memory — IMPORTANT:
You receive the full conversation history. When the user asks a follow-up like "give me directions" or "how do I get there", ALWAYS check previous messages for context. If you already told them their nearest station, use that as the starting point. Never ask them to repeat information they already gave you or that you already told them."""


def _haversine_miles(lat1, lng1, lat2, lng2):
    """Calculate distance in miles between two coordinates."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _station_mentioned(station_name, msg_lower):
    """Check if a station is mentioned in a message, with fuzzy matching."""
    name_lower = station_name.lower()
    # Direct: full station name found in message
    if name_lower in msg_lower:
        return True
    # Normalize slashes to spaces for both name and message
    name_norm = name_lower.replace('/', ' ')
    msg_norm = msg_lower.replace('/', ' ')
    if name_norm in msg_norm:
        return True
    # Reverse: check if 2+ consecutive words from station name appear in message
    name_words = name_norm.split()
    for length in range(len(name_words), 1, -1):
        for start in range(len(name_words) - length + 1):
            phrase = ' '.join(name_words[start:start + length])
            if len(phrase) >= 5 and phrase in msg_norm:
                return True
    return False


def _build_user_context(request, data, user_message=''):
    """Build a context string with user info for the AI."""
    from .gtfs_service import get_arrivals
    parts = []

    # --- User identity ---
    if request.user.is_authenticated:
        user = request.user
        parts.append(f"User: {user.username} (signed in)")
        try:
            profile = user.profile
            if profile.home_station:
                parts.append(f"Home station: {profile.home_station.name}")
        except UserProfile.DoesNotExist:
            pass

        # User's rating history
        user_ratings = (
            Rating.objects.filter(user=user)
            .select_related('station')
            .order_by('-created_at')[:5]
        )
        if user_ratings.exists():
            rated = []
            for r in user_ratings:
                rated.append(f"{r.station.name} (safety:{r.safety}/5, cleanliness:{r.cleanliness}/5)")
            parts.append(f"Recent ratings: {'; '.join(rated)}")
    else:
        parts.append("User: anonymous (not signed in)")

    # --- User location & nearby stations ---
    user_lat = data.get('lat')
    user_lng = data.get('lng')
    if user_lat is not None and user_lng is not None:
        try:
            user_lat = float(user_lat)
            user_lng = float(user_lng)
            parts.append(f"Current location: {user_lat:.4f}, {user_lng:.4f}")

            # Find nearby stations with lines and ratings
            stations = Station.objects.prefetch_related('lines').annotate(
                avg_safety=Avg('ratings__safety'),
                avg_cleanliness=Avg('ratings__cleanliness'),
                rating_count=Count('ratings'),
            )
            nearby = []
            for s in stations:
                dist = _haversine_miles(user_lat, user_lng, s.latitude, s.longitude)
                if dist <= 5:  # within 5 miles
                    line_codes = [l.code for l in s.lines.all()]
                    lines_str = ','.join(line_codes) if line_codes else '?'
                    info = f"{s.name} [Lines: {lines_str}] ({dist:.1f} mi)"
                    if s.rating_count and s.rating_count > 0:
                        info += f" — avg safety {s.avg_safety:.1f}/5, cleanliness {s.avg_cleanliness:.1f}/5 ({s.rating_count} ratings)"
                    nearby.append((dist, info))
            nearby.sort()
            if nearby:
                parts.append(f"Closest station: {nearby[0][1]}")
                parts.append("Nearby stations: " + "; ".join(info for _, info in nearby[:10]))

                # Fetch live arrivals and walking directions for top 3 nearest stations
                from .google_routes import get_walking_route
                for i, (dist, info) in enumerate(nearby[:3]):
                    station_name = info.split(' [')[0]
                    # Live arrivals
                    try:
                        station_arrivals = get_arrivals(station_name, limit=5)
                        if station_arrivals:
                            arr_strs = [f"{a['line']} Line to {a['headsign']} at {a['time']} ({a['minutes_away']} min away, color:{a['color']})" for a in station_arrivals]
                            parts.append(f"Live trains at {station_name}: " + "; ".join(arr_strs))
                    except Exception:
                        pass
                    # Walking directions
                    try:
                        station_obj = Station.objects.get(name=station_name)
                        walk_data = get_walking_route(
                            {"lat": user_lat, "lng": user_lng},
                            {"lat": station_obj.latitude, "lng": station_obj.longitude},
                            settings.GOOGLE_MAPS_API_KEY,
                        )
                        if walk_data:
                            label = "Walking to" if i == 0 else "Walking to (alt)"
                            walk_info = f"{label} {station_name}: {walk_data['duration_minutes']} min walk ({walk_data['distance_text']})"
                            # Include turn-by-turn steps
                            if walk_data.get('steps'):
                                step_strs = [f"  {j+1}. {s['instruction']}" + (f" ({s['distance']})" if s.get('distance') else "") for j, s in enumerate(walk_data['steps'])]
                                walk_info += "\n" + "\n".join(step_strs)
                            parts.append(walk_info)
                    except Exception:
                        pass
            else:
                parts.append("No Metro stations within 5 miles of user.")
        except (ValueError, TypeError):
            pass

    # --- Station reviews for safety context ---
    # Fetch recent reviews for nearby stations so AI can assess safety
    def _get_station_reviews(station_name, limit=5):
        """Get recent reviews with descriptions for a station."""
        try:
            reviews = Rating.objects.filter(
                station__name=station_name,
                description__isnull=False,
            ).exclude(description='').select_related('user').order_by('-created_at')[:limit]
            if not reviews:
                return None
            review_strs = []
            for r in reviews:
                username = r.user.username if r.user else 'anonymous'
                staff_str = f", staff:{r.staff_present}" if r.staff_present else ""
                review_strs.append(
                    f"[{username}] safety:{r.safety}/5, cleanliness:{r.cleanliness}/5{staff_str} — \"{r.description}\""
                )
            return "; ".join(review_strs)
        except Exception:
            return None

    # Add reviews for top 3 nearby stations
    if user_lat is not None and user_lng is not None:
        try:
            stations_qs = Station.objects.prefetch_related('lines').annotate(
                rating_count_val=Count('ratings'),
            )
            nearby_for_reviews = []
            for s in stations_qs:
                dist = _haversine_miles(float(user_lat), float(user_lng), s.latitude, s.longitude)
                if dist <= 5 and s.rating_count_val and s.rating_count_val > 0:
                    nearby_for_reviews.append((dist, s.name))
            nearby_for_reviews.sort()
            for _, sname in nearby_for_reviews[:3]:
                reviews_str = _get_station_reviews(sname)
                if reviews_str:
                    parts.append(f"Recent reviews for {sname}: {reviews_str}")
        except Exception:
            pass

    # Fetch arrivals and travel times for stations mentioned in the user message
    mentioned_stations = []
    if user_message:
        from .gtfs_service import get_travel_times, get_schedule_at_station
        try:
            all_stations = Station.objects.all()
            msg_lower = user_message.lower()
            for s in all_stations:
                if _station_mentioned(s.name, msg_lower):
                    mentioned_stations.append(s.name)
                    try:
                        mentioned_arrivals = get_arrivals(s.name, limit=5)
                        if mentioned_arrivals:
                            arr_strs = [
                                f"{a['line']} Line to {a['headsign']} at {a['time']} ({a['minutes_away']} min away, color:{a['color']})"
                                for a in mentioned_arrivals
                            ]
                            parts.append(f"Live trains at {s.name}: " + "; ".join(arr_strs))
                    except Exception:
                        pass
                    # Also fetch reviews for mentioned stations
                    reviews_str = _get_station_reviews(s.name)
                    if reviews_str:
                        parts.append(f"Recent reviews for {s.name}: {reviews_str}")

            # If 2+ stations mentioned, compute travel times between them
            # Detect a destination/meetup station (look for keywords like "at", "to", "arrive")
            if len(mentioned_stations) >= 2:
                # Try to identify the destination station
                import re as _re
                dest_station = None
                # Check for patterns like "arrive at X", "get to X", "meet at X", "at X station"
                for s_name in mentioned_stations:
                    s_lower = s_name.lower()
                    s_norm = s_lower.replace('/', ' ')
                    patterns = [
                        rf'(?:arrive|get|meet|be)\s+(?:at|to)\s+.*{_re.escape(s_norm)}',
                        rf'(?:at|to)\s+{_re.escape(s_norm)}\s+(?:station|at)',
                    ]
                    for pat in patterns:
                        if _re.search(pat, msg_lower.replace('/', ' ')):
                            dest_station = s_name
                            break
                    if dest_station:
                        break

                # If no explicit destination found, use the last mentioned station
                if not dest_station:
                    dest_station = mentioned_stations[-1]

                origin_stations = [s for s in mentioned_stations if s != dest_station]
                if origin_stations:
                    try:
                        travel_data = get_travel_times(origin_stations, dest_station)
                        travel_strs = []
                        for origin, info in travel_data.items():
                            if info:
                                travel_strs.append(
                                    f"{origin} -> {dest_station}: ~{info['minutes']} min on {info['line']} Line"
                                )
                            else:
                                travel_strs.append(
                                    f"{origin} -> {dest_station}: no direct route found (transfer needed)"
                                )
                        if travel_strs:
                            parts.append(f"Travel times to {dest_station}: " + "; ".join(travel_strs))
                    except Exception:
                        pass

                # Check if user mentioned a specific target time
                time_match = _re.search(r'(\d{1,2})\s*:\s*(\d{2})\s*(am|pm|AM|PM)?', msg_lower)
                if not time_match:
                    time_match = _re.search(r'(\d{1,2})\s*(am|pm|AM|PM)', msg_lower)
                if time_match:
                    groups = time_match.groups()
                    if len(groups) == 3:
                        hour, minute, period = int(groups[0]), int(groups[1]), (groups[2] or '').lower()
                    else:
                        hour, minute, period = int(groups[0]), 0, (groups[1] or '').lower()
                    if period == 'pm' and hour != 12:
                        hour += 12
                    elif period == 'am' and hour == 12:
                        hour = 0
                    target_time = f"{hour:02d}:{minute:02d}"

                    # Get schedule at each origin around the target time, heading toward destination
                    for origin in origin_stations:
                        try:
                            schedule = get_schedule_at_station(origin, target_time, direction_station=dest_station, limit=3)
                            if schedule:
                                sched_strs = [f"{s['time']} ({s['line']} Line to {s['headsign']})" for s in schedule]
                                parts.append(f"Trains at {origin} around {target_time}: " + "; ".join(sched_strs))
                        except Exception:
                            pass
        except Exception:
            pass

    # --- Directions: try RAPTOR first, fall back to Google Routes ---
    google_route_block = None
    if user_message:
        # Try RAPTOR first (internal routing, no API call)
        directions_result = _get_raptor_directions_context(user_message, data, mentioned_stations)

        # Fallback to Google Routes if RAPTOR fails
        if not directions_result:
            directions_result = _get_google_directions_context(user_message, data, mentioned_stations)

        if directions_result:
            directions_context, google_route_block = directions_result
            parts.append(directions_context)

    return "\n".join(parts), google_route_block


def _is_directions_request(msg_lower):
    """Check if a user message is asking for transit directions."""
    direction_phrases = [
        "how do i get to", "how to get to", "how can i get to",
        "directions to", "directions from", "give me directions", "get directions",
        "give me the directions", "get the directions",
        "the directions", "show directions", "show me directions",
        "take me to", "get me to",
        "travel to", "travel from",
        "go to", "go from",
        "ride to", "ride from",
        "get to", "get from",
        "route to", "route from",
        "trip to", "trip from",
        "commute to", "commute from",
        "way to get to", "best way to",
        "how long to get to", "how far to",
        "navigate to",
        "from here to",
        "how do i get there", "how to get there",
        "nearest station", "closest station", "walk to the station",
        "give me direction", "give direction",
    ]
    for phrase in direction_phrases:
        if phrase in msg_lower:
            return True
    # Also match "from X to Y" pattern
    if re.search(r'\bfrom\b.+\bto\b', msg_lower):
        return True
    return False


def _match_place_to_station(place_text):
    """Try to match a place/destination text to a known Metro station.

    Handles cases like "lax" → "LAX/Metro Transit Center",
    "usc" → "Expo Park/USC", "union station" → "Union Station", etc.
    Returns the station name or None.
    """
    text = place_text.lower().strip()
    try:
        all_stations = Station.objects.all()
    except Exception:
        return None

    best = None
    best_score = (0, 0)  # (matched_words, total_matched_chars)
    for s in all_stations:
        name_lower = s.name.lower()
        name_parts = re.split(r'[/\s\-]+', name_lower)
        text_parts = [tp for tp in re.split(r'[/\s\-]+', text) if tp and len(tp) >= 3]

        # Count how many text parts match station name parts
        matched = [tp for tp in text_parts if tp in name_parts]
        if matched:
            score = (len(matched), sum(len(w) for w in matched))
            if score > best_score:
                best_score = score
                best = s.name

    return best


def _extract_place_destination(msg_lower):
    """Extract a non-station place destination from a directions request.

    Handles messages like:
      'how do i get to pink's hot dogs'  → "pink's hot dogs"
      'directions to lax'                → 'lax'
      'take me to crypto.com arena'      → 'crypto.com arena'
    """
    patterns = [
        r'(?:get|go|going|travel|ride|head|take\s+me|directions?|way)\s+to\s+(?:the\s+)?(.+?)(?:\?|!|$)',
        r'how\s+(?:do|can|would|could)\s+(?:i|we)\s+(?:get|go)\s+to\s+(?:the\s+)?(.+?)(?:\?|!|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, msg_lower)
        if match:
            place = match.group(1).strip().rstrip('?!., ')
            # Skip generic words that are not real places
            skip_phrases = {
                'a station', 'the station', 'there', 'work', 'home', 'school',
                'nearest station', 'closest station', 'my station',
                'the nearest station', 'the closest station',
            }
            if place and len(place) > 2 and place not in skip_phrases:
                return place
    return None


def _extract_destination_from_message(msg_lower, mentioned_stations):
    """Extract the destination station from a directions request."""
    # Look for "to <station>" pattern
    for station in mentioned_stations:
        s_lower = station.lower()
        s_norm = s_lower.replace('/', ' ')
        # Check "to <station>" or "get to <station>"
        if re.search(rf'\bto\s+(?:the\s+)?{re.escape(s_norm)}', msg_lower.replace('/', ' ')):
            return station
        if re.search(rf'\bto\s+(?:the\s+)?{re.escape(s_lower)}', msg_lower):
            return station
    # Fallback: last mentioned station is usually the destination
    if mentioned_stations:
        return mentioned_stations[-1]
    return None


def _extract_origin_from_message(msg_lower, mentioned_stations, destination):
    """Extract the origin station from a directions request."""
    for station in mentioned_stations:
        if station == destination:
            continue
        s_lower = station.lower()
        s_norm = s_lower.replace('/', ' ')
        if re.search(rf'\bfrom\s+(?:the\s+)?{re.escape(s_norm)}', msg_lower.replace('/', ' ')):
            return station
        if re.search(rf'\bfrom\s+(?:the\s+)?{re.escape(s_lower)}', msg_lower):
            return station
    # Return first non-destination station
    for station in mentioned_stations:
        if station != destination:
            return station
    return None


def _geocode_place(place_name, api_key):
    """Geocode a place name to lat/lng using Google Geocoding API."""
    import requests
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": place_name + ", Los Angeles, CA",
        "key": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            loc = results[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception:
        pass
    return None, None


# Stations that exist in the DB but are NOT yet open for service
_NOT_YET_OPEN_STATIONS = {
    'Wilshire/La Brea', 'Wilshire/Fairfax', 'Wilshire/La Cienega',
    'Wilshire/Rodeo', 'Century City/Constellation', 'Westwood/VA Hospital',
}


def _find_nearest_station_to_place(place_name, api_key):
    """Find the nearest OPEN Metro station to a place destination.

    Excludes stations that are not yet open (D Line extension).
    Returns (station_name, distance_miles, (lat, lng)) or (None, None, None).
    """
    lat, lng = _geocode_place(place_name, api_key)
    if lat is None:
        return None, None, None

    stations = Station.objects.all()
    closest = None
    closest_dist = float('inf')
    for s in stations:
        if s.name in _NOT_YET_OPEN_STATIONS:
            continue
        dist = _haversine_miles(lat, lng, s.latitude, s.longitude)
        if dist < closest_dist:
            closest_dist = dist
            closest = s.name
    return closest, closest_dist, (lat, lng)


def _normalize_google_station_name(google_name):
    """Map a Google-returned station name to our system's station name."""
    if not google_name:
        return google_name
    # Try exact match first
    try:
        if Station.objects.filter(name=google_name).exists():
            return google_name
    except Exception:
        pass
    # Common Google name variations
    name = google_name.strip()
    # Remove common suffixes Google adds
    for suffix in [' Station', ' station', ' Metro Station', ' Metrolink Station']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    # Try match after cleaning
    try:
        s = Station.objects.filter(name=name).first()
        if s:
            return s.name
        # Try case-insensitive / fuzzy match
        s = Station.objects.filter(name__iexact=name).first()
        if s:
            return s.name
        # Try contains match (e.g., "7th Street / Metro Center" → "7th St/Metro Center")
        name_simple = name.replace(' / ', '/').replace('Street', 'St').replace('Avenue', 'Ave')
        s = Station.objects.filter(name__iexact=name_simple).first()
        if s:
            return s.name
        # Try partial match
        for station in Station.objects.all():
            sn = station.name.lower()
            nn = name.lower().replace(' / ', '/').replace('street', 'st').replace('avenue', 'ave')
            if sn == nn or sn.replace(' ', '') == nn.replace(' ', ''):
                return station.name
    except Exception:
        pass
    return google_name


def _google_line_to_code(google_line_name):
    """Map a Google transit line name to our line letter code."""
    if not google_line_name:
        return None
    name = google_line_name.strip().upper()
    # Direct letter match
    if name in ('A', 'B', 'C', 'D', 'E', 'G', 'J', 'K', 'L'):
        return name
    # Common Google names
    mappings = {
        'A LINE': 'A', 'B LINE': 'B', 'C LINE': 'C', 'D LINE': 'D',
        'E LINE': 'E', 'G LINE': 'G', 'J LINE': 'J', 'K LINE': 'K',
        'BLUE': 'A', 'RED': 'B', 'GREEN': 'C', 'PURPLE': 'D',
        'EXPO': 'E', 'GOLD': 'A', 'ORANGE': 'G', 'SILVER': 'J',
        'CRENSHAW': 'K',
        'METRO A LINE': 'A', 'METRO B LINE': 'B', 'METRO C LINE': 'C',
        'METRO D LINE': 'D', 'METRO E LINE': 'E', 'METRO G LINE': 'G',
        'METRO J LINE': 'J', 'METRO K LINE': 'K',
        'A LINE (BLUE)': 'A', 'B LINE (RED)': 'B', 'C LINE (GREEN)': 'C',
        'D LINE (PURPLE)': 'D', 'E LINE (EXPO)': 'E',
    }
    return mappings.get(name)


def _build_route_block_from_google(route_data):
    """Build a suggested [ROUTE] block from Google Routes API data."""
    if not route_data or not route_data.get('steps'):
        return None
    import json as _json
    steps = []
    ride_steps = [s for s in route_data['steps'] if s.get('type') == 'ride']
    prev_to = None
    for i, step in enumerate(ride_steps):
        line_code = _google_line_to_code(step.get('line', ''))
        from_station = _normalize_google_station_name(step.get('from_station', ''))
        to_station = _normalize_google_station_name(step.get('to_station', ''))
        if not line_code:
            continue
        # Add transfer step if this ride starts at same station prev ride ended
        if prev_to and from_station and prev_to == from_station and i > 0:
            steps.append({"type": "transfer", "line": None, "from": prev_to, "to": from_station})
        steps.append({"type": "ride", "line": line_code, "from": from_station, "to": to_station})
        prev_to = to_station
    if not steps:
        return None
    return _json.dumps({"steps": steps})


def _get_raptor_directions_context(user_message, data, mentioned_stations):
    """Get RAPTOR-computed transit directions if the message is a directions request.

    Returns (context_string, route_block_json) or None.
    Uses GTFS data to route Metro-to-Metro without any Google API calls.
    """
    from .gtfs_service import get_raptor_index, get_active_service_ids, _find_stop_ids_for_station, _get_cached_data
    from .raptor import raptor_query, format_journey_for_context, build_route_block

    msg_lower = user_message.lower()
    if not _is_directions_request(msg_lower):
        return None

    # Determine origin and destination station names
    destination = _extract_destination_from_message(msg_lower, mentioned_stations)

    origin = _extract_origin_from_message(msg_lower, mentioned_stations, destination)

    # If no explicit origin, use user's closest station
    user_lat = data.get('lat')
    user_lng = data.get('lng')
    if not origin and user_lat and user_lng:
        try:
            user_lat_f = float(user_lat)
            user_lng_f = float(user_lng)
            stations = Station.objects.all()
            closest = None
            closest_dist = float('inf')
            for s in stations:
                dist = _haversine_miles(user_lat_f, user_lng_f, s.latitude, s.longitude)
                if dist < closest_dist:
                    closest_dist = dist
                    closest = s.name
            origin = closest
        except (ValueError, TypeError):
            pass

    # If no destination but one station mentioned, use it
    if not destination and len(mentioned_stations) == 1:
        destination = mentioned_stations[0]

    # Handle place destinations
    is_place = False
    place_name = None
    place_coords = None
    nearest_to_place = None
    if not destination:
        place_name = _extract_place_destination(msg_lower)
        if place_name:
            # First: try matching the place text to a known Metro station
            # (handles "lax" → "LAX/Metro Transit Center", "usc" → "Expo Park/USC", etc.)
            matched_station = _match_place_to_station(place_name)
            if matched_station:
                destination = matched_station
            else:
                # Geocode and find nearest station
                nearest_station, dist_miles, coords = _find_nearest_station_to_place(
                    place_name, settings.GOOGLE_MAPS_API_KEY
                )
                if nearest_station:
                    destination = nearest_station
                    is_place = True
                    place_coords = coords
                    nearest_to_place = (nearest_station, dist_miles)
                else:
                    return None  # Can't geocode — let Google handle it
        else:
            return None

    if not origin or not destination:
        return None

    # Get RAPTOR index
    raptor_index = get_raptor_index()
    if raptor_index is None:
        return None

    # Resolve station names to GTFS stop_ids
    try:
        gtfs_data = _get_cached_data()
    except Exception:
        return None

    origin_stop_ids = _find_stop_ids_for_station(gtfs_data, origin)
    dest_stop_ids = _find_stop_ids_for_station(gtfs_data, destination)

    if not origin_stop_ids or not dest_stop_ids:
        return None

    # Filter to only platform stops that RAPTOR knows about
    origin_stops = {sid for sid in origin_stop_ids if sid in raptor_index.stop_patterns}
    target_stops = {sid for sid in dest_stop_ids if sid in raptor_index.stop_patterns}

    if not origin_stops or not target_stops:
        return None

    # Get departure time and active services
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    departure_sec = now.hour * 3600 + now.minute * 60 + now.second

    service_ids = get_active_service_ids()
    if not service_ids:
        return None

    # Run RAPTOR
    try:
        journeys = raptor_query(
            raptor_index, origin_stops, target_stops,
            departure_sec, service_ids, max_rounds=4,
        )
    except Exception:
        return None

    if not journeys:
        return None

    # Pick best journey: fewest transfers first, then earliest arrival
    best = min(journeys, key=lambda j: (j.num_transfers, j.arrival_sec))

    # Format output
    origin_label = origin
    dest_label = place_name.title() if is_place else destination

    context = format_journey_for_context(best, origin_label, destination)
    route_block = build_route_block(best, raptor_index)

    # Add place destination info if applicable
    if is_place and nearest_to_place:
        station_name, dist_miles = nearest_to_place
        context += (
            f"\n\nNearest Metro station to {dest_label}: {station_name}"
            f" (~{dist_miles:.1f} mi walk from station to destination)."
            f" The rider should exit at {station_name} and walk/rideshare to {dest_label}."
        )

    if route_block:
        context += f"\n\nUse this exact route in your [ROUTE] block:\n{route_block}"

    return context, route_block


def _get_google_directions_context(user_message, data, mentioned_stations):
    """Get Google Routes transit directions if the message is a directions request."""
    from .google_routes import get_transit_route, format_route_for_context

    msg_lower = user_message.lower()
    if not _is_directions_request(msg_lower):
        return None

    # Find mentioned stations if not passed in
    if mentioned_stations is None:
        mentioned_stations = []
        try:
            all_stations = Station.objects.all()
            for s in all_stations:
                if _station_mentioned(s.name, msg_lower):
                    mentioned_stations.append(s.name)
        except Exception:
            pass

    # Determine origin and destination
    destination = _extract_destination_from_message(msg_lower, mentioned_stations)

    # Try to get origin from message or user location
    origin = _extract_origin_from_message(msg_lower, mentioned_stations, destination)

    # If no explicit origin, use the user's closest station from location data
    user_lat = data.get('lat')
    user_lng = data.get('lng')
    if not origin and user_lat and user_lng:
        try:
            user_lat_f = float(user_lat)
            user_lng_f = float(user_lng)
            stations = Station.objects.all()
            closest = None
            closest_dist = float('inf')
            for s in stations:
                dist = _haversine_miles(user_lat_f, user_lng_f, s.latitude, s.longitude)
                if dist < closest_dist:
                    closest_dist = dist
                    closest = s.name
            origin = closest
        except (ValueError, TypeError):
            pass

    # If no explicit destination but user mentions one station + directions keywords,
    # use that station as destination and user location as origin
    if not destination and len(mentioned_stations) == 1:
        destination = mentioned_stations[0]

    # If still missing origin, try using lat/lng directly with Google
    if not origin and user_lat and user_lng:
        origin_loc = {"lat": user_lat, "lng": user_lng}
    elif origin:
        origin_loc = origin + " Metro Station, Los Angeles, CA"
    else:
        return None

    # Determine destination location for Google Routes API
    is_place = False
    if destination:
        # Destination is a known Metro station
        destination_loc = destination + " Metro Station, Los Angeles, CA"
        dest_label = destination
    else:
        # No station matched — try to extract a place destination from the message
        place = _extract_place_destination(msg_lower)
        if place:
            destination_loc = place + ", Los Angeles, CA"
            dest_label = place.title()
            is_place = True
        else:
            return None

    api_key = settings.GOOGLE_MAPS_API_KEY
    route_data = get_transit_route(origin_loc, destination_loc, api_key)

    origin_label = origin if origin else "your location"
    context = ""
    google_route_block = None

    if route_data:
        context = format_route_for_context(route_data, origin_label, dest_label)
        google_route_block = _build_route_block_from_google(route_data)

    # If it's a place destination and Google returned buses (not Metro rail),
    # geocode the place, find the nearest Metro station, and re-route there.
    if is_place and not google_route_block:
        nearest_station, dist_miles, place_coords = _find_nearest_station_to_place(
            place, api_key
        )
        if nearest_station:
            nearest_loc = nearest_station + " Metro Station, Los Angeles, CA"
            route_data_2 = get_transit_route(origin_loc, nearest_loc, api_key)
            if route_data_2:
                route_data = route_data_2
                context = format_route_for_context(route_data, origin_label, nearest_station)
                google_route_block = _build_route_block_from_google(route_data)
            context += (
                f"\n\nNearest Metro station to {dest_label}: {nearest_station}"
                f" (~{dist_miles:.1f} mi walk from station to destination)."
                f" The rider should exit at {nearest_station} and walk/rideshare to {dest_label}."
            )

    if not route_data:
        return None

    if google_route_block:
        context += f"\n\nUse this exact route in your [ROUTE] block:\n{google_route_block}"

    return context, google_route_block


@csrf_exempt
@require_http_methods(["POST"])
def api_chat(request):
    """AI chat endpoint using Claude API — persists messages for authenticated users"""
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        conversation_id = data.get('conversation_id')
        conversation_history = data.get('history', [])

        if not user_message:
            return JsonResponse({'status': 'error', 'message': 'Empty message'}, status=400)

        # --- Resolve or create conversation for authenticated users ---
        conversation = None
        if request.user.is_authenticated:
            if conversation_id:
                try:
                    conversation = ChatConversation.objects.get(id=conversation_id, user=request.user)
                except ChatConversation.DoesNotExist:
                    conversation = None

            if conversation is None:
                # Create new conversation; use first ~50 chars of the message as title
                conversation = ChatConversation.objects.create(
                    user=request.user,
                    title=user_message[:50],
                )

            # Save the user message
            ChatMessage.objects.create(conversation=conversation, role='user', content=user_message)

            # Load history from DB instead of client payload
            db_messages = conversation.messages.order_by('created_at')
            messages = []
            for m in db_messages:
                messages.append({'role': m.role, 'content': m.content})
            # Keep last 20 messages for context window
            messages = messages[-20:]
        else:
            # Anonymous: use client-supplied history
            messages = []
            for msg in conversation_history[-20:]:
                role = 'user' if msg.get('type') == 'user' else 'assistant'
                messages.append({'role': role, 'content': msg.get('text', '')})
            messages.append({'role': 'user', 'content': user_message})

        # Build user context
        user_context, google_route_block = _build_user_context(request, data, user_message)
        system_prompt = METRO_SYSTEM_PROMPT + "\n\n--- CURRENT USER CONTEXT ---\n" + user_context

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=[
                {"type": "web_search_20250305", "name": "web_search", "max_uses": 2},
            ],
        )

        # Extract text from all text blocks (web search responses have mixed block types)
        ai_text = ''.join(block.text for block in response.content if block.type == 'text')

        # Parse all structured data blocks from the FULL ai_text before stripping
        route_data = None
        arrivals_data = None
        walking_data = None

        # If Google Routes computed a route, USE IT as the authoritative route data
        # instead of relying on whatever the AI generated in its [ROUTE] block
        if google_route_block:
            try:
                route_data = json.loads(google_route_block)
            except (json.JSONDecodeError, ValueError):
                route_data = None

        # Fall back to AI's [ROUTE] block only if Google didn't provide one
        if not route_data:
            route_match = re.search(r'\[ROUTE\](.*?)\[/ROUTE\]', ai_text, re.DOTALL)
            if route_match:
                try:
                    route_data = json.loads(route_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    route_data = None

        arrivals_match = re.search(r'\[ARRIVALS\](.*?)\[/ARRIVALS\]', ai_text, re.DOTALL)
        if arrivals_match:
            try:
                arrivals_data = json.loads(arrivals_match.group(1))
            except (json.JSONDecodeError, ValueError):
                arrivals_data = None

        walking_match = re.search(r'\[WALKING\](.*?)\[/WALKING\]', ai_text, re.DOTALL)
        if walking_match:
            try:
                walking_data = json.loads(walking_match.group(1))
            except (json.JSONDecodeError, ValueError):
                walking_data = None

        dest_data = None
        dest_match = re.search(r'\[DEST\](.*?)\[/DEST\]', ai_text, re.DOTALL)
        if dest_match:
            try:
                dest_data = json.loads(dest_match.group(1))
            except (json.JSONDecodeError, ValueError):
                dest_data = None

        # Strip all data blocks from display text
        ai_text_clean = re.sub(r'\[ROUTE\].*?\[/ROUTE\]', '', ai_text, flags=re.DOTALL)
        ai_text_clean = re.sub(r'\[ARRIVALS\].*?\[/ARRIVALS\]', '', ai_text_clean, flags=re.DOTALL)
        ai_text_clean = re.sub(r'\[WALKING\].*?\[/WALKING\]', '', ai_text_clean, flags=re.DOTALL)
        ai_text_clean = re.sub(r'\[DEST\].*?\[/DEST\]', '', ai_text_clean, flags=re.DOTALL)
        ai_text_clean = ai_text_clean.rstrip()

        # Save full text (with route/arrivals blocks) to DB for AI context continuity
        if conversation:
            ChatMessage.objects.create(conversation=conversation, role='assistant', content=ai_text)
            conversation.save()  # bump updated_at

        # Fallback: if we have route_data but no walking_data, auto-generate it
        # from user location and the route's starting station
        if route_data and not walking_data:
            try:
                user_lat = float(data.get('lat', 0))
                user_lng = float(data.get('lng', 0))
                if user_lat and user_lng:
                    ride_steps = [s for s in route_data.get('steps', []) if s.get('type') == 'ride']
                    if ride_steps:
                        start_station_name = ride_steps[0].get('from', '')
                        start_station = Station.objects.filter(name=start_station_name).first()
                        if start_station:
                            from .google_routes import get_walking_route
                            walk = get_walking_route(
                                {"lat": user_lat, "lng": user_lng},
                                {"lat": start_station.latitude, "lng": start_station.longitude},
                                settings.GOOGLE_MAPS_API_KEY,
                            )
                            if walk:
                                walking_data = {
                                    "station": start_station_name,
                                    "duration_minutes": walk["duration_minutes"],
                                    "distance": walk["distance_text"],
                                    "lines": list(start_station.lines.values_list("code", flat=True)),
                                    "steps": walk.get("steps", []),
                                }
            except Exception:
                pass

        # Fetch destination walking directions if AI provided a [DEST] block
        dest_walking = None
        if dest_data and route_data:
            try:
                from .google_routes import get_walking_route
                ride_steps = [s for s in route_data.get('steps', []) if s.get('type') == 'ride']
                if ride_steps:
                    last_station_name = ride_steps[-1].get('to', '')
                    last_station = Station.objects.filter(name=last_station_name).first()
                    if last_station:
                        dest_address = dest_data.get('address', dest_data.get('name', ''))
                        walk = get_walking_route(
                            {"lat": last_station.latitude, "lng": last_station.longitude},
                            dest_address,
                            settings.GOOGLE_MAPS_API_KEY,
                        )
                        if walk:
                            dest_walking = {
                                "from_station": last_station_name,
                                "destination": dest_data.get('name', dest_address),
                                "address": dest_address,
                                "duration_minutes": walk["duration_minutes"],
                                "distance": walk["distance_text"],
                                "steps": walk.get("steps", []),
                            }
            except Exception:
                pass

        resp = {
            'status': 'ok',
            'reply': ai_text_clean,
            'conversation_id': conversation.id if conversation else None,
        }
        if route_data:
            resp['route_data'] = route_data
        if arrivals_data:
            resp['arrivals_data'] = arrivals_data
        if walking_data:
            resp['walking_data'] = walking_data
        if dest_walking:
            resp['dest_walking'] = dest_walking

        return JsonResponse(resp)

    except anthropic.AuthenticationError:
        return JsonResponse({'status': 'error', 'message': 'AI service configuration error'}, status=500)
    except anthropic.RateLimitError:
        return JsonResponse({'status': 'error', 'message': 'AI is busy, please try again in a moment'}, status=429)
    except anthropic.BadRequestError as e:
        if 'credit balance' in str(e).lower():
            return JsonResponse({'status': 'error', 'message': 'AI service credits depleted. Please contact the administrator.'}, status=503)
        return JsonResponse({'status': 'error', 'message': 'AI service error'}, status=400)
    except anthropic.APIError as e:
        return JsonResponse({'status': 'error', 'message': 'AI service temporarily unavailable'}, status=503)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': 'Something went wrong'}, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def api_chat_delete(request, conversation_id):
    """Delete a single chat conversation."""
    try:
        conversation = ChatConversation.objects.get(id=conversation_id, user=request.user)
        conversation.delete()
        return JsonResponse({'status': 'ok'})
    except ChatConversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def api_chat_delete_all(request):
    """Delete all chat conversations for the authenticated user."""
    ChatConversation.objects.filter(user=request.user).delete()
    return JsonResponse({'status': 'ok'})


@login_required
@require_http_methods(["GET"])
def api_chat_history(request):
    """Return the authenticated user's chat conversations."""
    conversations = ChatConversation.objects.filter(user=request.user)[:50]
    result = []
    for conv in conversations:
        last_msg = conv.messages.filter(role='assistant').order_by('-created_at').first()
        result.append({
            'id': conv.id,
            'title': conv.title,
            'date': conv.updated_at.strftime('%b %d, %Y'),
            'preview': last_msg.content[:100] if last_msg else '',
        })
    return JsonResponse({'status': 'ok', 'conversations': result})


@login_required
@require_http_methods(["GET"])
def api_chat_conversation(request, conversation_id):
    """Return all messages for a specific conversation."""
    try:
        conversation = ChatConversation.objects.get(id=conversation_id, user=request.user)
    except ChatConversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)

    msgs = []
    for m in conversation.messages.order_by('created_at'):
        text = m.content
        route_data = None
        arrivals_data = None
        walking_data = None
        # Parse all data blocks from full text, then strip them for display
        if m.role == 'assistant':
            route_match = re.search(r'\[ROUTE\](.*?)\[/ROUTE\]', text, re.DOTALL)
            if route_match:
                try:
                    route_data = json.loads(route_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass
            arrivals_match = re.search(r'\[ARRIVALS\](.*?)\[/ARRIVALS\]', text, re.DOTALL)
            if arrivals_match:
                try:
                    arrivals_data = json.loads(arrivals_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass
            walking_match = re.search(r'\[WALKING\](.*?)\[/WALKING\]', text, re.DOTALL)
            if walking_match:
                try:
                    walking_data = json.loads(walking_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass
            # Strip all blocks from display text
            text = re.sub(r'\[ROUTE\].*?\[/ROUTE\]', '', text, flags=re.DOTALL)
            text = re.sub(r'\[ARRIVALS\].*?\[/ARRIVALS\]', '', text, flags=re.DOTALL)
            text = re.sub(r'\[WALKING\].*?\[/WALKING\]', '', text, flags=re.DOTALL)
            text = text.rstrip()
        msg_obj = {
            'type': 'user' if m.role == 'user' else 'ai',
            'text': text,
        }
        if route_data:
            msg_obj['route_data'] = route_data
        if arrivals_data:
            msg_obj['arrivals_data'] = arrivals_data
        if walking_data:
            msg_obj['walking_data'] = walking_data
        msgs.append(msg_obj)
    return JsonResponse({
        'status': 'ok',
        'id': conversation.id,
        'title': conversation.title,
        'messages': msgs,
    })
