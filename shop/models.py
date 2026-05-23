from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image
from django.utils.text import slugify

# Create your models here.
class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('admin', 'Admin'),
        ('seller', 'Seller'),
        ('buyer', 'Buyer'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='buyer')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.username

    @property
    def is_seller(self):
        return self.user_type == 'seller'

    @property
    def is_admin_user(self):
        return self.user_type == 'admin' or self.is_superuser

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class MarketPrice(models.Model):
    price_date = models.DateField(db_index=True)
    commodity_type = models.CharField(max_length=80, db_index=True)
    variety = models.CharField(max_length=120, blank=True, default='', db_index=True)
    market_location = models.CharField(max_length=120, db_index=True)
    region = models.CharField(max_length=120, blank=True, default='')
    unit = models.CharField(max_length=40, blank=True, default='')
    price = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=120, default='amis.pk')
    scraped_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['price_date', 'commodity_type', 'variety', 'market_location'],
                name='uniq_marketprice_day_commodity_variety_location',
            )
        ]
        ordering = ['-price_date', 'commodity_type', 'variety', 'market_location']

    def __str__(self):
        return f"{self.price_date} | {self.commodity_type} | {self.market_location} | {self.price}"

class Product(models.Model):
    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    name = models.CharField(max_length=100)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    variety = models.CharField(max_length=120, blank=True, default='')
    market_location = models.CharField(max_length=120, blank=True, default='')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    stock = models.IntegerField()
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    quality_grade = models.CharField(max_length=1, choices=[('A', 'Grade A'), ('B', 'Grade B'), ('C', 'Grade C')], null=True, blank=True)
    quality_confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    price_source = models.ForeignKey(MarketPrice, on_delete=models.SET_NULL, null=True, blank=True, related_name='priced_products')
    priced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def commodity_type(self):
        return (self.category.name if self.category else '').strip()

    @property
    def is_wheat_commodity(self):
        return self.commodity_type.lower() == 'wheat'

    def _price_queryset(self, on_date):
        commodity = self.commodity_type
        location = (self.market_location or '').strip()
        variety = (self.variety or '').strip()
        if not commodity or not location:
            return MarketPrice.objects.none()

        qs = MarketPrice.objects.filter(
            price_date=on_date,
            commodity_type__iexact=commodity,
            market_location__iexact=location,
        )
        if variety:
            return qs.filter(variety__iexact=variety)
        return qs.filter(variety='')

    def get_market_price(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return self._price_queryset(on_date).order_by('-scraped_at').first()

    def apply_market_price(self, on_date=None, strict=False):
        market_price = self.get_market_price(on_date=on_date)
        if not market_price:
            if strict:
                raise ValidationError("No market price found for today's commodity, variety, and market location.")
            return None

        self.price = market_price.price
        self.price_source = market_price
        self.priced_at = timezone.now()
        return market_price

    def save(self, *args, **kwargs):
        allow_admin_override = kwargs.pop('allow_admin_override', getattr(self, '_allow_admin_override', False))
        enforce_market_rules = kwargs.pop('enforce_market_rules', True)
        allow_quality_override = kwargs.pop('allow_quality_override', False)

        if self._should_enforce_market_rules(enforce_market_rules, allow_admin_override):
            if not self.is_wheat_commodity:
                self.quality_grade = None
                self.quality_confidence = None
            elif self.pk and not allow_quality_override:
                existing = Product.objects.filter(pk=self.pk).values('quality_grade', 'quality_confidence').first()
                if existing:
                    self.quality_grade = existing['quality_grade']
                    self.quality_confidence = existing['quality_confidence']

            self.apply_market_price(strict=False)

        super().save(*args, **kwargs)

        if self.image:
            img = Image.open(self.image.path)
            # Resizing limit ko 4K tak barha diya gaya hai taake quality kharab na ho
            if img.height > 2160 or img.width > 3840:
                output_size = (3840, 2160)
                img.thumbnail(output_size, Image.LANCZOS)
                img.save(self.image.path, quality=95, optimize=True)

    def _should_enforce_market_rules(self, enforce_market_rules, allow_admin_override):
        return enforce_market_rules and bool(self.farmer_id) and not allow_admin_override

    @property
    def average_rating(self):
        avg = self.reviews.aggregate(models.Avg('rating'))['avg']
        return avg if avg else 0

    def __str__(self):
        return self.name

class Order(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_paid = models.BooleanField(default=False)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    full_name = models.CharField(max_length=100, blank=True, null=True)
    shipping_address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Confirmed', 'Confirmed'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Rejected', 'Rejected'),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')

    def __str__(self):
        return f"Order {self.id} by {self.customer.username}"

    @property
    def get_cart_total(self):
        orderitems = self.items.all()
        total = sum([item.get_total for item in orderitems])
        return total

    @property
    def get_cart_items(self):
        orderitems = self.items.all()
        total = sum([item.quantity for item in orderitems])
        return total

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    @property
    def get_total(self):
        if self.price is None or self.quantity is None:
            return 0
        return self.price * self.quantity

class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(default=5, choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('product', 'user')

    def __str__(self):
        return f"{self.user.username} - {self.product.name} ({self.rating})"
