# Generated migration for reel audio mute feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0017_reel_copyright_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='reel',
            name='is_muted',
            field=models.BooleanField(
                default=False, help_text='If True, audio will be disabled for all users'),
        ),
        migrations.AddField(
            model_name='reelreport',
            name='disable_audio',
            field=models.BooleanField(
                default=False, help_text='If checked, audio will be disabled for this reel'),
        ),
    ]
