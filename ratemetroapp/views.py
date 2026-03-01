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
from .models import UserLocation, Rating, Station, RatingPhoto, UserProfile, Feedback, ChatConversation, ChatMessage

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
   - Metro Security contact: 1-888-950-7233 (non-emergency)

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
- Aviation/LAX: C, K lines
- Aviation/Century: C, K lines
- LAX/Metro Transit Center: C, K lines
- Pico: A, E lines
- Wilshire/Vermont: B, D lines
- North Hollywood: B, G lines
- Civic Center/Grand Park: B, D lines
- Pershing Square: B, D lines
- Westlake/MacArthur Park: B, D lines

Line Descriptions (current as of 2025 — post-Regional Connector):
- A Line (Blue): Long Beach ↔ Azusa/Pomona via Downtown LA, Pasadena. Includes old Gold Line north segment. Stops at 7th St/Metro Center, Grand Ave Arts/Bunker Hill, Historic Broadway, Little Tokyo/Arts District, Union Station, Chinatown, Highland Park, Pasadena, Azusa, and all the way to Pomona North.
- B Line (Red): Union Station ↔ North Hollywood via Downtown, Hollywood. Stops at Hollywood/Highland (Walk of Fame), Hollywood/Vine, Universal City.
- C Line (Green): Norwalk ↔ LAX/Metro Transit Center via South Bay. East-west line along I-105.
- D Line (Purple): Union Station ↔ Wilshire/Western (extending to Westwood in 2026). Shares many Downtown stations with B Line.
- E Line (Expo): Downtown Santa Monica ↔ Atlantic (East LA) via Downtown LA. This line absorbed the old Gold Line East LA extension. Goes through Culver City, USC, DTLA (7th St/Metro Center, Grand Ave Arts/Bunker Hill, Historic Broadway, Little Tokyo/Arts District), then through Boyle Heights (Mariachi Plaza, Soto) to East LA (Maravilla, East LA Civic Center, Atlantic).
- G Line (Orange): North Hollywood ↔ Chatsworth. BRT (bus rapid transit) through the San Fernando Valley.
- K Line (Crenshaw): Expo/Crenshaw ↔ Aviation/LAX via Inglewood, Westchester. Serves SoFi Stadium area.

Wayfinding Rules — ALWAYS follow these when giving directions:
1. ALWAYS use the user's current location and the "Nearby stations" list to find their CLOSEST station as the starting point
2. Pick the route with the fewest transfers — direct lines beat transfers every time
3. If two routes have equal transfers, pick the one starting from the closer station
4. Mention the specific LINE LETTER AND COLOR for every segment (e.g. "Take the E (Expo) Line")
5. Name every transfer station explicitly (e.g. "Transfer to the B (Red) Line at 7th St/Metro Center")
6. When someone is in East LA, Boyle Heights, or near Maravilla/Atlantic/Soto/Indiana stations — they are on the E Line, NOT the old Gold/L Line
7. When someone is in Pasadena, Highland Park, Azusa, or SGV — they are on the A Line, NOT the old Gold/L Line
8. The A and E lines share 3 Regional Connector stations in DTLA: Grand Ave Arts/Bunker Hill, Historic Broadway, Little Tokyo/Arts District
9. For Hollywood destinations, the B (Red) Line is usually the best — transfer at 7th St/Metro Center or Union Station
10. For Santa Monica/Westside, use the E (Expo) Line
11. For LAX, use K Line or C Line to Aviation/LAX or LAX/Metro Transit Center
12. Never refer to the "L Line" or "Gold Line" — it no longer exists. Use A Line or E Line instead

Response Format Rules — CRITICAL:
- You are writing for a mobile chat bubble. Keep it SHORT.
- NEVER use emojis, asterisks for emphasis, or markdown headers.
- For directions, use a numbered list. Each step = one short sentence starting with an action verb.
- Example of a good direction response:
  1. Board the Blue (A) Line at Maravilla.
  2. Ride to 7th St/Metro Center (~25 min).
  3. Switch to the Red (B) Line.
  4. Ride to North Hollywood (~15 min).
  Total: ~40 min, 1 transfer.
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

Guidelines:
- Be warm but concise — every word should earn its place
- If someone asks about emergencies, direct them to call 911
- If a question is unrelated to LA Metro or LA tourism, politely redirect
- Never make up real-time data (delays, crime stats) — speak in general terms
- Use a casual tone
- Lead directions with action verbs: "Board...", "Ride to...", "Get off at...", "Switch to..."
- Include travel time estimates (e.g. "~20 min")
- Skip jargon — "switch to" not "transfer to", "get off" not "alight"
- You will receive a CURRENT USER CONTEXT section with each request. Use it to personalize your responses:
  - Reference nearby stations by name and distance when relevant
  - Greet signed-in users by their username on the first message only
  - If the user asks for their coordinates or location data, share it
  - ALWAYS start directions from the user's closest station

Structured Route Data — IMPORTANT:
Whenever you give step-by-step Metro directions (riding from one station to another), you MUST append a machine-readable JSON block at the very end of your response in this exact format:

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

Structured Arrivals Data — IMPORTANT:
When the user asks about train times, schedule, next trains, or arrivals at a station, append a machine-readable JSON block at the very end of your response in this exact format:

[ARRIVALS]{"station":"Station Name","arrivals":[{"line":"E","headsign":"Downtown Santa Monica","minutes_away":5,"color":"#fdb913"}]}[/ARRIVALS]

Copy the arrivals exactly from the CURRENT USER CONTEXT "Live trains at ..." data. Do not invent or modify times.
Use the station name, line letter, headsign, minutes_away, and color values exactly as provided in the context.
Only include the [ARRIVALS] block for train time/schedule/arrival questions, NOT for directions or general info.
If no live train data is available in the context for the requested station, do NOT include an [ARRIVALS] block — just say you don't have current schedule data for that station."""


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

                # Fetch live arrivals for nearest station
                try:
                    nearest_name = nearby[0][1].split(' [')[0]  # extract station name before [Lines: ...]
                    nearest_arrivals = get_arrivals(nearest_name, limit=5)
                    if nearest_arrivals:
                        arr_strs = [f"{a['line']} Line to {a['headsign']} in {a['minutes_away']} min" for a in nearest_arrivals]
                        parts.append(f"Live trains at {nearest_name}: " + "; ".join(arr_strs))
                except Exception:
                    pass
            else:
                parts.append("No Metro stations within 5 miles of user.")
        except (ValueError, TypeError):
            pass

    # Fetch arrivals and travel times for stations mentioned in the user message
    if user_message:
        from .gtfs_service import get_travel_times, get_schedule_at_station
        try:
            all_stations = Station.objects.all()
            msg_lower = user_message.lower()
            mentioned_stations = []
            for s in all_stations:
                if _station_mentioned(s.name, msg_lower):
                    mentioned_stations.append(s.name)
                    try:
                        mentioned_arrivals = get_arrivals(s.name, limit=5)
                        if mentioned_arrivals:
                            arr_strs = [
                                f"{a['line']} Line to {a['headsign']} in {a['minutes_away']} min (color:{a['color']})"
                                for a in mentioned_arrivals
                            ]
                            parts.append(f"Live trains at {s.name}: " + "; ".join(arr_strs))
                    except Exception:
                        pass

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

    return "\n".join(parts)


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
            for msg in conversation_history[-10:]:
                role = 'user' if msg.get('type') == 'user' else 'assistant'
                messages.append({'role': role, 'content': msg.get('text', '')})
            messages.append({'role': 'user', 'content': user_message})

        # Build user context
        user_context = _build_user_context(request, data, user_message)
        system_prompt = METRO_SYSTEM_PROMPT + "\n\n--- CURRENT USER CONTEXT ---\n" + user_context

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        response = client.messages.create(
            model='claude-haiku-4-5',
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )

        ai_text = response.content[0].text

        # Parse structured route data if present
        route_data = None
        ai_text_clean = ai_text
        route_match = re.search(r'\[ROUTE\](.*?)\[/ROUTE\]', ai_text, re.DOTALL)
        if route_match:
            try:
                route_data = json.loads(route_match.group(1))
            except (json.JSONDecodeError, ValueError):
                route_data = None
            # Strip the route block from display text
            ai_text_clean = ai_text[:route_match.start()].rstrip()

        # Parse structured arrivals data if present
        arrivals_data = None
        arrivals_match = re.search(r'\[ARRIVALS\](.*?)\[/ARRIVALS\]', ai_text_clean, re.DOTALL)
        if arrivals_match:
            try:
                arrivals_data = json.loads(arrivals_match.group(1))
            except (json.JSONDecodeError, ValueError):
                arrivals_data = None
            ai_text_clean = ai_text_clean[:arrivals_match.start()].rstrip()

        # Save full text (with route/arrivals blocks) to DB for AI context continuity
        if conversation:
            ChatMessage.objects.create(conversation=conversation, role='assistant', content=ai_text)
            conversation.save()  # bump updated_at

        resp = {
            'status': 'ok',
            'reply': ai_text_clean,
            'conversation_id': conversation.id if conversation else None,
        }
        if route_data:
            resp['route_data'] = route_data
        if arrivals_data:
            resp['arrivals_data'] = arrivals_data

        return JsonResponse(resp)

    except anthropic.AuthenticationError:
        return JsonResponse({'status': 'error', 'message': 'AI service configuration error'}, status=500)
    except anthropic.RateLimitError:
        return JsonResponse({'status': 'error', 'message': 'AI is busy, please try again in a moment'}, status=429)
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
        # Strip route/arrivals blocks from assistant messages and extract data
        if m.role == 'assistant':
            route_match = re.search(r'\[ROUTE\](.*?)\[/ROUTE\]', text, re.DOTALL)
            if route_match:
                try:
                    route_data = json.loads(route_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass
                text = text[:route_match.start()].rstrip()
            arrivals_match = re.search(r'\[ARRIVALS\](.*?)\[/ARRIVALS\]', text, re.DOTALL)
            if arrivals_match:
                try:
                    arrivals_data = json.loads(arrivals_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass
                text = text[:arrivals_match.start()].rstrip()
        msg_obj = {
            'type': 'user' if m.role == 'user' else 'ai',
            'text': text,
        }
        if route_data:
            msg_obj['route_data'] = route_data
        if arrivals_data:
            msg_obj['arrivals_data'] = arrivals_data
        msgs.append(msg_obj)
    return JsonResponse({
        'status': 'ok',
        'id': conversation.id,
        'title': conversation.title,
        'messages': msgs,
    })
