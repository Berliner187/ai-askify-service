# Generated by Django 5.1 on 2024-11-10 20:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('askify_service', '0015_alter_blockedusers_id_staff'),
    ]

    operations = [
        migrations.CreateModel(
            name='FeedbackFromAI',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('survey_id', models.UUIDField()),
                ('staff_id', models.UUIDField()),
                ('feedback_data', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]