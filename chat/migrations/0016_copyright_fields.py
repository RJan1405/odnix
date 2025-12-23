# Generated migration for copyright fields in PostReport

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0015_customuser_gender'),
    ]

    operations = [
        migrations.AddField(
            model_name='postreport',
            name='copyright_description',
            field=models.TextField(
                blank=True, null=True, help_text='Description of copyright infringement (optional)'),
        ),
        migrations.AddField(
            model_name='postreport',
            name='copyright_type',
            field=models.CharField(
                blank=True,
                choices=[('audio', 'Audio Copyright'),
                         ('content', 'Content Copyright')],
                max_length=10,
                null=True,
                help_text='Whether the copyright is for audio or content'
            ),
        ),
    ]
