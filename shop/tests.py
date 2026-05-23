from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .forms import ProductForm
from .models import Category, CustomUser, MarketPrice, Product


class ProductMarketPricingTests(TestCase):
    def setUp(self):
        self.seller = CustomUser.objects.create_user(
            username='seller1',
            password='pass12345',
            user_type='seller',
        )
        self.wheat = Category.objects.create(name='Wheat')
        self.market_price = MarketPrice.objects.create(
            price_date=timezone.localdate(),
            commodity_type='Wheat',
            variety='A1',
            market_location='Lahore',
            price=Decimal('2750.00'),
        )

    def test_apply_market_price_sets_price_and_source(self):
        product = Product(
            farmer=self.seller,
            name='Sample Wheat',
            category=self.wheat,
            variety='A1',
            market_location='Lahore',
            price=Decimal('1.00'),
            description='desc',
            stock=5,
        )

        matched = product.apply_market_price(strict=True)

        self.assertEqual(matched.pk, self.market_price.pk)
        self.assertEqual(product.price, Decimal('2750.00'))
        self.assertEqual(product.price_source, self.market_price)
        self.assertIsNotNone(product.priced_at)

    def test_apply_market_price_raises_when_missing(self):
        product = Product(
            farmer=self.seller,
            name='Other Wheat',
            category=self.wheat,
            variety='B2',
            market_location='Karachi',
            price=Decimal('1.00'),
            description='desc',
            stock=5,
        )

        with self.assertRaises(ValidationError):
            product.apply_market_price(strict=True)

    def test_seller_tampering_price_and_grade_is_locked_on_save(self):
        product = Product.objects.create(
            farmer=self.seller,
            name='Locked Wheat',
            category=self.wheat,
            variety='A1',
            market_location='Lahore',
            price=Decimal('100.00'),
            description='desc',
            stock=5,
            quality_grade='B',
            quality_confidence=Decimal('65.00'),
        )

        product.price = Decimal('9999.99')
        product.quality_grade = 'A'
        product.quality_confidence = Decimal('99.99')
        product.save()
        product.refresh_from_db()

        self.assertEqual(product.price, Decimal('2750.00'))
        self.assertEqual(product.quality_grade, 'B')
        self.assertEqual(product.quality_confidence, Decimal('65.00'))

    def test_product_form_excludes_price_and_quality_fields(self):
        form = ProductForm()
        self.assertNotIn('price', form.fields)
        self.assertNotIn('quality_grade', form.fields)
        self.assertNotIn('quality_confidence', form.fields)
