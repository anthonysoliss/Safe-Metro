from django.contrib import admin
from .models import (
    MetroLine, Station, UserProfile, Rating, 
    RatingPhoto, UserLocation, UserActivity
)

@admin.register(MetroLine)
class MetroLineAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'color')
    search_fields = ('code', 'name')

@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ('name', 'latitude', 'longitude', 'get_lines', 'rating_count')
    list_filter = ('lines',)
    search_fields = ('name',)
    filter_horizontal = ('lines',)
    
    def get_lines(self, obj):
        return ', '.join([line.code for line in obj.lines.all()])
    get_lines.short_description = 'Lines'
    
    def rating_count(self, obj):
        return obj.ratings.count()
    rating_count.short_description = 'Ratings'

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'home_station', 'anonymous_ratings', 'created_at')
    list_filter = ('anonymous_ratings', 'created_at')
    search_fields = ('user__username', 'user__email')

@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('station', 'user', 'safety', 'cleanliness', 'staff_present', 'overall_rating', 'created_at')
    list_filter = ('created_at', 'safety', 'cleanliness', 'staff_present', 'station')
    search_fields = ('station__name', 'user__username', 'description')
    readonly_fields = ('created_at', 'updated_at', 'overall_rating')
    date_hierarchy = 'created_at'

@admin.register(RatingPhoto)
class RatingPhotoAdmin(admin.ModelAdmin):
    list_display = ('rating', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('rating__station__name',)

@admin.register(UserLocation)
class UserLocationAdmin(admin.ModelAdmin):
    list_display = ('user', 'latitude', 'longitude', 'timestamp', 'session_id')
    list_filter = ('timestamp',)
    search_fields = ('user__username', 'session_id')
    readonly_fields = ('timestamp',)

@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'activity_type', 'created_at')
    list_filter = ('activity_type', 'created_at')
    search_fields = ('user__username', 'activity_type')
    readonly_fields = ('created_at',)
