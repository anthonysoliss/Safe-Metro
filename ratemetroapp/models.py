from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator

class MetroLine(models.Model):
    """Metro line information"""
    code = models.CharField(max_length=2, unique=True, primary_key=True)  # A, B, C, etc.
    name = models.CharField(max_length=100)  # A Line (Blue)
    color = models.CharField(max_length=7)  # Hex color code
    text_color = models.CharField(max_length=7, default='#fff')  # Text color for contrast
    
    def __str__(self):
        return f"{self.code} - {self.name}"
    
    class Meta:
        ordering = ['code']


class Station(models.Model):
    """Metro station information"""
    name = models.CharField(max_length=200, unique=True)
    lines = models.ManyToManyField(MetroLine, related_name='stations')
    latitude = models.FloatField()
    longitude = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
        ]


class UserProfile(models.Model):
    """Extended user profile information"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    home_station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True, blank=True, related_name='home_users')
    anonymous_ratings = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username}'s Profile"


class Rating(models.Model):
    """Station rating by a user"""
    STAFF_CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
    ]
    
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='ratings')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ratings')
    session_id = models.CharField(max_length=255, null=True, blank=True)  # For anonymous users
    
    # Rating fields
    safety = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    cleanliness = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    staff_present = models.CharField(max_length=3, choices=STAFF_CHOICES, null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    @property
    def overall_rating(self):
        """Calculate overall rating from safety and cleanliness"""
        if self.safety > 0 and self.cleanliness > 0:
            return round((self.safety + self.cleanliness) / 2)
        return self.safety if self.safety > 0 else self.cleanliness
    
    def __str__(self):
        return f"{self.station.name} - {self.overall_rating}/5 by {self.user.username if self.user else 'Anonymous'}"
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['station', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['session_id', '-created_at']),
        ]


class RatingPhoto(models.Model):
    """Photos attached to ratings"""
    rating = models.ForeignKey(Rating, on_delete=models.CASCADE, related_name='photos')
    photo = models.ImageField(upload_to='rating_photos/%Y/%m/%d/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Photo for {self.rating.station.name} rating"
    
    class Meta:
        ordering = ['-uploaded_at']


class UserLocation(models.Model):
    """Store user location data"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='locations')
    latitude = models.FloatField()
    longitude = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)
    session_id = models.CharField(max_length=255, null=True, blank=True)  # For anonymous users
    accuracy = models.FloatField(null=True, blank=True)  # GPS accuracy in meters
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['session_id', '-timestamp']),
        ]
    
    def __str__(self):
        return f"Location: {self.latitude}, {self.longitude} at {self.timestamp}"


class UserActivity(models.Model):
    """Track user activity for analytics"""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities')
    session_id = models.CharField(max_length=255, null=True, blank=True)
    activity_type = models.CharField(max_length=50)  # 'rating_submitted', 'map_viewed', 'station_searched', etc.
    metadata = models.JSONField(default=dict, blank=True)  # Additional data about the activity
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['activity_type', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.activity_type} at {self.created_at}"
