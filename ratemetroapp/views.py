from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from .models import UserLocation

def map_view(request):
    """Main map page view"""
    return render(request, 'ratemetroapp/map.html')

def sign_in_view(request):
    """Sign in page view"""
    return render(request, 'ratemetroapp/sign-in.html')

def profile_view(request):
    """User profile page view"""
    return render(request, 'ratemetroapp/profile.html')

def my_ratings_view(request):
    """My ratings page view"""
    return render(request, 'ratemetroapp/my-ratings.html')

def settings_view(request):
    """Settings page view"""
    return render(request, 'ratemetroapp/settings.html')

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
