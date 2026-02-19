from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
import json
from .models import UserLocation, Rating, Station, RatingPhoto, UserProfile

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
    for rating in user_ratings:
        # Get station lines
        station_lines = list(rating.station.lines.values_list('code', flat=True))
        
        ratings_data.append({
            'id': rating.id,
            'station': rating.station.name,
            'lines': station_lines,
            'safety': rating.safety,
            'cleanliness': rating.cleanliness,
            'staff': rating.staff_present or '',
            'description': rating.description or '',
            'photo': '',  # Would need to handle photo URLs if stored
            'timestamp': int(rating.created_at.timestamp() * 1000),  # Convert to milliseconds
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
def settings_view(request):
    """Settings page view"""
    context = {
        'is_authenticated': True,
        'user': request.user,
    }
    return render(request, 'ratemetroapp/settings.html', context)

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
        data = json.loads(request.body)
        station_name = data.get('station_name')
        safety = int(data.get('safety'))
        cleanliness = int(data.get('cleanliness'))
        staff_present = data.get('staff_present')
        description = data.get('description', '')
        photo_data = data.get('photo')
        
        # Get or create station
        station, created = Station.objects.get_or_create(
            name=station_name,
            defaults={'latitude': 0, 'longitude': 0}  # Will need to update with actual coords
        )
        
        # Create rating
        rating = Rating.objects.create(
            station=station,
            user=request.user,
            safety=safety,
            cleanliness=cleanliness,
            staff_present=staff_present,
            description=description,
            ip_address=get_client_ip(request)
        )
        
        # Handle photo if provided
        if photo_data:
            # In production, you'd save the file properly
            # For now, we'll store the base64 data reference
            RatingPhoto.objects.create(
                rating=rating,
                photo=None  # Would need to decode base64 and save as file
            )
        
        return JsonResponse({
            'status': 'success',
            'message': 'Rating submitted successfully',
            'rating_id': rating.id
        })
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

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
        
        return JsonResponse({
            'status': 'success',
            'message': 'Account created successfully',
            'username': user.username
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


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
