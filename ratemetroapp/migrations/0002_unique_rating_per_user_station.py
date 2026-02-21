from django.db import migrations, models


def remove_duplicate_ratings(apps, schema_editor):
    """Keep only the most recent rating per (user, station) pair."""
    Rating = apps.get_model('ratemetroapp', 'Rating')

    # Find all (station_id, user_id) pairs with more than one rating
    from django.db.models import Count, Max
    duplicates = (
        Rating.objects
        .filter(user__isnull=False)
        .values('station_id', 'user_id')
        .annotate(count=Count('id'), latest=Max('created_at'))
        .filter(count__gt=1)
    )

    for dup in duplicates:
        # Get the id of the most recent rating to keep
        latest_rating = (
            Rating.objects
            .filter(station_id=dup['station_id'], user_id=dup['user_id'])
            .order_by('-created_at')
            .first()
        )
        if latest_rating:
            # Delete all others
            Rating.objects.filter(
                station_id=dup['station_id'],
                user_id=dup['user_id'],
            ).exclude(pk=latest_rating.pk).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ratemetroapp', '0001_initial'),
    ]

    operations = [
        # First clean up any existing duplicates
        migrations.RunPython(remove_duplicate_ratings, migrations.RunPython.noop),
        # Then enforce the constraint at DB level (only for authenticated users;
        # NULLs are exempt in SQL so anonymous ratings are unaffected)
        migrations.AlterUniqueTogether(
            name='rating',
            unique_together={('station', 'user')},
        ),
        migrations.AddIndex(
            model_name='rating',
            index=models.Index(fields=['station', 'user'], name='rating_station_user_idx'),
        ),
    ]
