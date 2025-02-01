from django.contrib import admin
from .models import *


class BlogPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug')
    fields = ('title', 'slug')
    readonly_fields = ('slug',)


admin.site.register(BlogPost, BlogPostAdmin)
