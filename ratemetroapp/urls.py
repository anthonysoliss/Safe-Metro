from django.urls import path
from . import views

app_name = 'ratemetroapp'

urlpatterns = [
    path('', views.map_view, name='map'),
    path('sign-in/', views.sign_in_view, name='sign_in'),
    path('profile/', views.profile_view, name='profile'),
    path('my-ratings/', views.my_ratings_view, name='my_ratings'),
    path('settings/', views.settings_view, name='settings'),
    path('api/location/', views.update_location, name='update_location'),
]
