from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ratemetroapp', '0002_unique_rating_per_user_station'),
    ]

    operations = [
        migrations.AddField(
            model_name='ratingphoto',
            name='media_type',
            field=models.CharField(
                choices=[('photo', 'Photo'), ('video', 'Video')],
                default='photo',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='ratingphoto',
            name='video',
            field=models.FileField(blank=True, null=True, upload_to='rating_videos/%Y/%m/%d/'),
        ),
        migrations.AlterField(
            model_name='ratingphoto',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to='rating_photos/%Y/%m/%d/'),
        ),
    ]
