from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser, Product, Category, Review

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'user_type', 'phone_number', 'address')

    def __init__(self, *args, **kwargs):
        is_admin = kwargs.pop('is_admin', False)
        super().__init__(*args, **kwargs)
        if not is_admin:
            self.fields.pop('user_type', None)
            
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control rounded-pill border-0 shadow-sm px-4 bg-light',
                'placeholder': f'Enter {field.label}',
                'style': 'height: 50px;'
            })

class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control rounded-pill border-0 shadow-sm px-4 bg-light',
                'placeholder': f'Enter {field.label}',
                'style': 'height: 50px;'
            })

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control rounded-pill border-0 shadow-sm px-4 bg-light',
                'placeholder': field.label,
                'style': 'height: 45px;'
            })

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'category', 'variety', 'market_location', 'description', 'stock', 'image']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['market_location'].required = True
        self.fields['stock'].label = 'Stock (kg)'
        for name, field in self.fields.items():
            if name != 'image':
                field.widget.attrs.update({
                    'class': 'form-control rounded-pill border-0 shadow-sm px-4 bg-light',
                    'placeholder': field.label,
                    'style': 'height: 45px;' if name != 'description' else ''
                })
            else:
                field.widget.attrs.update({'class': 'form-control-file ml-3'})

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'comment']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': 'form-control rounded-pill border-0 shadow-sm px-4 bg-light',
            })