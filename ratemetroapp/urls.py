from django.urls import path
from . import views

app_name = 'ratemetroapp'

urlpatterns = [
    path('', views.map_view, name='map'),
    path('sign-in/', views.sign_in_view, name='sign_in'),
    path('station-reviews/', views.station_reviews_view, name='station_reviews'),
    path('profile/', views.profile_view, name='profile'),
    path('my-ratings/', views.my_ratings_view, name='my_ratings'),
    path('settings/', views.settings_view, name='settings'),
    path('help-center/', views.help_center_view, name='help_center'),
    path('terms/', views.terms_view, name='terms'),
    path('privacy-policy/', views.privacy_policy_view, name='privacy_policy'),
    path('feedback/', views.feedback_view, name='feedback'),
    path('api/location/', views.update_location, name='update_location'),
    path('api/check-auth/', views.check_auth, name='check_auth'),
    path('api/submit-rating/', views.submit_rating, name='submit_rating'),
    path('api/station-ratings/', views.get_station_ratings, name='station_ratings'),
    path('api/sign-in/', views.api_sign_in, name='api_sign_in'),
    path('api/sign-up/', views.api_sign_up, name='api_sign_up'),
    path('api/logout/', views.api_logout, name='api_logout'),
    path('api/delete-account/', views.api_delete_account, name='api_delete_account'),
    path('api/delete-rating/', views.api_delete_rating, name='api_delete_rating'),
    path('api/update-profile/', views.api_update_profile, name='api_update_profile'),
    path('api/update-settings/', views.api_update_settings, name='api_update_settings'),
    path('api/arrivals/', views.get_station_arrivals, name='station_arrivals'),
    path('api/chat/', views.api_chat, name='api_chat'),
]
