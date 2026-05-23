from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Product, CustomUser, Order, OrderItem, Category, MarketPrice

admin.site.register(Category)

class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'category', 'market_location', 'variety',
        'price', 'quality_grade', 'quality_confidence',
        'stock', 'farmer', 'created_at'
    )
    list_filter = ('category', 'market_location', 'created_at')
    search_fields = ('name', 'market_location', 'variety')

    def get_readonly_fields(self, request, obj=None):
        base_fields = (
            'quality_grade',
            'quality_confidence',
            'priced_at',
            'price_source',
            'created_at',
        )
        # Keep price editable on add form to avoid required-field creation errors.
        if obj is None:
            return base_fields
        return ('price',) + base_fields

    def save_model(self, request, obj, form, change):
        # superuser can still override via backend flags, but fields are read-only in UI
        allow_override = request.user.is_superuser
        obj.save(allow_admin_override=allow_override, enforce_market_rules=not allow_override)

    class Media:
        css = {'all': ('shop/admin_theme.css',)}
admin.site.register(Product, ProductAdmin)


@admin.register(MarketPrice)
class MarketPriceAdmin(admin.ModelAdmin):
    list_display = ('price_date', 'commodity_type', 'variety', 'market_location', 'region', 'unit', 'price', 'source', 'scraped_at')
    list_filter = ('price_date', 'commodity_type', 'market_location', 'region', 'source')
    search_fields = ('commodity_type', 'variety', 'market_location', 'region')

    class Media:
        css = {'all': ('shop/admin_theme.css',)}

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('User Role', {'fields': ('user_type', 'phone_number', 'address')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('User Role', {'fields': ('user_type', 'phone_number', 'address')}),
    )
    list_display = ('username', 'email', 'user_type', 'is_staff')
    list_filter = ('user_type', 'is_staff', 'is_active')

    class Media:
        css = {'all': ('shop/admin_theme.css',)}

admin.site.register(CustomUser, CustomUserAdmin)

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price', 'get_total')

class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'full_name', 'total_items', 'total_amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    list_editable = ('status',)
    inlines = [OrderItemInline]

    def total_items(self, obj):
        if obj.id: # Only call model methods if the object exists in the database
            return obj.get_cart_items
        return 0
    
    def total_amount(self, obj):
        if obj.id:
            return obj.get_cart_total
        return 0

    class Media:
        css = {'all': ('shop/admin_theme.css',)}

admin.site.register(Order, OrderAdmin)
