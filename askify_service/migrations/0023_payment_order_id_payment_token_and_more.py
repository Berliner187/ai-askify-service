# Generated by Django 5.1 on 2024-11-21 17:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('askify_service', '0022_tokensused_created_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='order_id',
            field=models.CharField(default='2024-11-10 21:04:42.306526', max_length=100, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='payment',
            name='token',
            field=models.CharField(default='8d0da86470d02296c7ce2e28be614a35b66d8535957021e0551536e5edb0ac22', max_length=100, unique=True),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='availablesubscription',
            name='plan_type',
            field=models.CharField(choices=[('free_plan', 'Free – 7 days'), ('standard_plan', 'Standard Plan – 30 days'), ('premium_plan', 'Premium Plan – 30 days'), ('tokens_plan', 'Tokens Package')], max_length=20),
        ),
        migrations.AlterField(
            model_name='payment',
            name='payment_id',
            field=models.CharField(max_length=100, unique=True),
        ),
    ]