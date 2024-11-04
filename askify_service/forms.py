from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import AuthUser


class AuthUserCreationForm(UserCreationForm):
    class Meta:
        model = AuthUser
        fields = ('username', 'email', 'password1', 'password2')


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = AuthUser
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = None
        self.fields['password1'].help_text = None
        self.fields['password2'].help_text = None

        if 'id_usable_password' in self.fields:
            del self.fields['id_usable_password']
