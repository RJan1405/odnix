from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0013_alter_customuser_theme'),
    ]

    operations = [
        migrations.AddField(
            model_name='tweet',
            name='content_type',
            field=models.CharField(default='text', max_length=32),
        ),
        migrations.AddField(
            model_name='tweet',
            name='code_html',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tweet',
            name='code_css',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tweet',
            name='code_js',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tweet',
            name='code_bundle',
            field=models.TextField(blank=True, null=True),
        ),
    ]
