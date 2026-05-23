from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

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

    def test_seller_cannot_tamper_with_price_and_grade(self):
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

        self.assertEqual(product.price, Decimal('2337.50'))
        self.assertEqual(product.quality_grade, 'B')
        self.assertEqual(product.quality_confidence, Decimal('65.00'))

    def test_product_form_excludes_price_and_quality_fields(self):
        form = ProductForm()
        self.assertNotIn('price', form.fields)
        self.assertNotIn('quality_grade', form.fields)
        self.assertNotIn('quality_confidence', form.fields)

    def test_existing_product_keeps_previous_price_when_today_market_missing(self):
        product = Product.objects.create(
            farmer=self.seller,
            name='Stored Wheat',
            category=self.wheat,
            variety='A1',
            market_location='Lahore',
            price=Decimal('100.00'),
            description='desc',
            stock=5,
        )
        original_source_id = product.price_source_id
        original_priced_at = product.priced_at
        self.market_price.price_date = self.market_price.price_date - timedelta(days=1)
        self.market_price.save(update_fields=['price_date'])

        product.price = Decimal('9000.00')
        product.save()
        product.refresh_from_db()

        self.assertEqual(product.price, Decimal('2750.00'))
        self.assertEqual(product.price_source_id, original_source_id)
        self.assertEqual(product.priced_at, original_priced_at)

    @patch('shop.views.assess_wheat_quality', return_value=('A', 96.5))
    def test_analyze_product_listing_returns_quality_and_price(self, _mock_quality):
        self.client.login(username='seller1', password='pass12345')
        image = SimpleUploadedFile('wheat.jpg', b'fake-image-content', content_type='image/jpeg')

        response = self.client.post(
            reverse('analyze_product_listing'),
            {
                'category': self.wheat.pk,
                'variety': 'A1',
                'market_location': 'Lahore',
                'image': image,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['quality_grade'], 'A')
        self.assertEqual(payload['quality_confidence'], 96.5)
        self.assertEqual(payload['price'], '2750.00')

    @patch('shop.views.assess_wheat_quality', return_value=('B', 88.2))
    def test_analyze_product_listing_applies_grade_multiplier_for_wheat(self, _mock_quality):
        self.client.login(username='seller1', password='pass12345')
        image = SimpleUploadedFile('wheat.jpg', b'fake-image-content', content_type='image/jpeg')

        response = self.client.post(
            reverse('analyze_product_listing'),
            {
                'category': self.wheat.pk,
                'variety': 'A1',
                'market_location': 'Lahore',
                'image': image,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['quality_grade'], 'B')
        self.assertEqual(payload['quality_confidence'], 88.2)
        self.assertEqual(payload['price'], '2337.50')

    def test_analyze_product_listing_requires_image_for_wheat(self):
        self.client.login(username='seller1', password='pass12345')

        response = self.client.post(
            reverse('analyze_product_listing'),
            {
                'category': self.wheat.pk,
                'variety': 'A1',
                'market_location': 'Lahore',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Please choose an image', response.json()['error'])


class ScraperFallbackTests(TestCase):
    @patch(
        'shop.management.commands.scrape_amis_prices.COMMODITY_PAGES',
        {'Wheat': {'commodity_id': 1, 'search_type': 0}},
    )
    @patch('shop.management.commands.scrape_amis_prices.requests.Session.get')
    def test_scraper_falls_back_to_previous_wheat_price(self, mock_get):
        class FakeResponse:
            text = '<html><body><table><tr><td>No data available</td></tr></table></body></html>'

            @staticmethod
            def raise_for_status():
                return None

        mock_get.return_value = FakeResponse()

        target_date = timezone.localdate()
        MarketPrice.objects.create(
            price_date=target_date - timedelta(days=1),
            commodity_type='Wheat',
            variety='',
            market_location='Lahore',
            price=Decimal('2800.00'),
        )

        call_command(
            'scrape_amis_prices',
            date=target_date.strftime('%Y-%m-%d'),
            market='Lahore',
        )

        today_wheat = MarketPrice.objects.get(
            price_date=target_date,
            commodity_type='Wheat',
            variety='',
            market_location='Lahore',
        )
        self.assertEqual(today_wheat.price, Decimal('2800.00'))
