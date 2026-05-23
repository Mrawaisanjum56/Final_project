import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from shop.models import MarketPrice


def _clean_text(value):
    return (value or '').strip()


def _parse_decimal(value):
    cleaned = re.sub(r'[^0-9.\-]', '', (value or '').replace(',', ''))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Scrape daily market prices from amis.pk and upsert into MarketPrice"

    def add_arguments(self, parser):
        parser.add_argument('--url', default=getattr(settings, 'AMIS_PRICE_URL', 'https://amis.pk/'))
        parser.add_argument('--date', help='Price date in YYYY-MM-DD format')

    def _row_to_payload(self, headers, cells):
        if len(cells) < 4:
            return None

        lower_headers = [h.lower() for h in headers]

        def pick(*names, default_index=None, default=''):
            for name in names:
                if name in lower_headers:
                    return _clean_text(cells[lower_headers.index(name)])
            if default_index is not None and default_index < len(cells):
                return _clean_text(cells[default_index])
            return default

        commodity = pick('commodity', 'commodity type', default_index=0)
        variety = pick('variety', default_index=1)
        location = pick('market', 'market location', 'location', 'district', default_index=2)
        region = pick('region', 'province', default='')
        unit = pick('unit', default='')

        raw_price = pick('price', 'average price', default='')
        if not raw_price:
            for cell in reversed(cells):
                raw_price = cell
                if _parse_decimal(raw_price) is not None:
                    break

        price = _parse_decimal(raw_price)
        if not commodity or not location or price is None:
            return None

        return {
            'commodity_type': commodity,
            'variety': variety,
            'market_location': location,
            'region': region,
            'unit': unit,
            'price': price,
        }

    def handle(self, *args, **options):
        target_url = options['url']
        date_arg = options.get('date')
        try:
            price_date = datetime.strptime(date_arg, '%Y-%m-%d').date() if date_arg else timezone.localdate()
        except ValueError as exc:
            raise CommandError(f"Invalid --date value '{date_arg}': {exc}") from exc

        try:
            response = requests.get(
                target_url,
                timeout=45,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; market-price-bot/1.0)'},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(
                f"Failed to fetch AMIS data from {target_url}. Check URL/network connectivity and retry."
            ) from exc

        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        if not tables:
            raise CommandError('No table found on AMIS page. Please verify selectors/source URL.')

        upserted = 0
        skipped = 0

        for table in tables:
            rows = table.find_all('tr')
            headers = [_clean_text(cell.get_text(' ', strip=True)) for cell in rows[0].find_all(['th', 'td'])] if rows else []
            for row in rows[1:]:
                cells = [_clean_text(cell.get_text(' ', strip=True)) for cell in row.find_all('td')]
                payload = self._row_to_payload(headers, cells)
                if not payload:
                    skipped += 1
                    continue

                MarketPrice.objects.update_or_create(
                    price_date=price_date,
                    commodity_type=payload['commodity_type'],
                    variety=payload['variety'],
                    market_location=payload['market_location'],
                    defaults={
                        'region': payload['region'],
                        'unit': payload['unit'],
                        'price': payload['price'],
                        'source': 'amis.pk',
                    },
                )
                upserted += 1

        self.stdout.write(self.style.SUCCESS(
            f"AMIS scrape complete for {price_date}: upserted={upserted}, skipped={skipped}, url={target_url}"
        ))
