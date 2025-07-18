from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import AuthUser


class AuthUserCreationForm(UserCreationForm):
    class Meta:
        model = AuthUser
        fields = ('email', 'password1', 'password2')


class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = AuthUser
        fields = ('email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].help_text = None
        self.fields['password2'].help_text = None

        if 'id_usable_password' in self.fields:
            del self.fields['id_usable_password']


class PhoneNumberForm(forms.Form):
    phone_number = forms.CharField(required=True)

    def clean_phone_number(self):
        phone_number = self.cleaned_data['phone_number']

        cleaned_number = ''.join(filter(str.isdigit, phone_number))

        if cleaned_number.startswith('8'):
            cleaned_number = '7' + cleaned_number[1:]

        return cleaned_number


class VerificationCodeForm(forms.Form):
    verification_code = forms.CharField(max_length=6, label='Введите код')


class FileUploadForm(forms.Form):
    question_count = forms.IntegerField(min_value=1, max_value=15)
    file = forms.FileField(
        max_length=100,
        allow_empty_file=False,
    )
