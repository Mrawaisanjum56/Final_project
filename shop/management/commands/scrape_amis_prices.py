# shop/management/commands/scrape_amis_prices.py
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from shop.models import MarketPrice

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"

# Your known working commodity IDs
COMMODITY_PAGES = {
    "Wheat": {"commodity_id": 1, "search_type": 0},
    "Rice": {"commodity_id": 3, "search_type": 0},
    "Tinda(Desi)": {"commodity_id": 32, "search_type": 0},
    "Potato": {"commodity_id": 21, "search_type": 0},
    "Onion": {"commodity_id": 23, "search_type": 0},
    "Tomato": {"commodity_id": 26, "search_type": 0},
    "Lady Finger": {"commodity_id": 30, "search_type": 0},
    "Mango(Dehsari)": {"commodity_id": 55, "search_type": 0},
}


def _parse_decimal(text: str | None) -> Decimal | None:
    match = re.search(r"(\d[\d,]*\.?\d*)", text or "")
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _detect_unit(text: str | None) -> str:
    normalized = (text or "").lower().replace(" ", "")
    if "100kg" in normalized:
        return "100kg"
    if "quintal" in normalized:
        return "quintal"
    # default (AMIS commonly uses 100kg)
    return "100kg"


def _build_viewprices_url(base_url: str, *, search_type: int, commodity_id: int) -> str:
    base_url = base_url.rstrip("/")
    return f"{base_url}/ViewPrices.aspx?searchType={int(search_type)}&commodityId={int(commodity_id)}"


def _extract_fqp_from_row_text(row_text: str) -> Decimal | None:
    """
    AMIS rows often contain: Min, Max, FQP (3 values).
    We take the 3rd numeric value as FQP like your working script.
    """
    nums = re.findall(r"(\d[\d,]*\.?\d*)", row_text)
    if len(nums) < 3:
        return None
    try:
        return Decimal(nums[2].replace(",", ""))
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Scrape AMIS ViewPrices.aspx for configured commodities and upsert into MarketPrice"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Price date in YYYY-MM-DD format (default: today)")
        parser.add_argument("--market", help="Market filter (default from settings AMIS_MARKET_FILTER)")
        parser.add_argument("--base-url", help="Base URL (default from settings AMIS_BASE_URL)")

    def handle(self, *args, **options):
        date_arg = options.get("date")
        try:
            price_date = (
                datetime.strptime(date_arg, "%Y-%m-%d").date()
                if date_arg
                else timezone.localdate()
            )
        except ValueError as exc:
            raise CommandError(f"Invalid --date value '{date_arg}': {exc}") from exc

        base_url = (
            options.get("base_url")
            or getattr(settings, "AMIS_BASE_URL", "http://www.amis.pk")
        ).rstrip("/")

        market_filter = (
            options.get("market")
            or getattr(settings, "AMIS_MARKET_FILTER", "")
        )
        market_filter_norm = (market_filter or "").lower().replace(" ", "")

        timeout = int(getattr(settings, "AMIS_SCRAPE_TIMEOUT", 45))

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        upserted = 0
        skipped = 0

        for commodity_type, cfg in COMMODITY_PAGES.items():
            url = _build_viewprices_url(
                base_url,
                search_type=cfg.get("search_type", 0),
                commodity_id=cfg["commodity_id"],
            )

            try:
                resp = session.get(url, timeout=timeout)
                resp.raise_for_status()
            except requests.RequestException as exc:
                skipped += 1
                self.stderr.write(self.style.WARNING(f"Fetch failed for {commodity_type}: {url} ({exc})"))
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            picked_price = None
            picked_unit = "100kg"
            picked_market = market_filter.strip() if market_filter else ""

            # Find first row matching market filter and containing 3 numbers
            for tr in soup.select("tr"):
                row_text = tr.get_text(" ", strip=True)
                row_norm = row_text.lower().replace(" ", "")

                if "commodity:" in row_norm or "dated:" in row_norm:
                    continue

                if market_filter_norm and market_filter_norm not in row_norm:
                    continue

                price = _extract_fqp_from_row_text(row_text)
                if price is not None:
                    picked_price = price
                    picked_unit = _detect_unit(row_text)
                    break

            if picked_price is None:
                if commodity_type.lower() == "wheat":
                    fallback_qs = MarketPrice.objects.filter(
                        commodity_type__iexact=commodity_type,
                        price_date__lt=price_date,
                    )
                    if market_filter:
                        fallback_qs = fallback_qs.filter(
                            market_location__iexact=market_filter.strip()
                        )
                    fallback_price = fallback_qs.order_by("-price_date", "-scraped_at").first()
                    if fallback_price:
                        picked_price = fallback_price.price
                        picked_unit = fallback_price.unit or picked_unit
                        picked_market = fallback_price.market_location or picked_market
                        self.stdout.write(
                            self.style.WARNING(
                                f"Wheat price fallback used from {fallback_price.price_date} for {price_date}."
                            )
                        )

            if picked_price is None:
                skipped += 1
                continue

            # Upsert into YOUR current MarketPrice schema
            MarketPrice.objects.update_or_create(
                price_date=price_date,
                commodity_type=commodity_type,
                variety="",  # you can extend later if you parse variety
                market_location=picked_market or "Unknown",
                defaults={
                    "region": "",
                    "unit": picked_unit,
                    "price": picked_price,
                    "source": "amis.pk",
                },
            )
            upserted += 1

        self.stdout.write(self.style.SUCCESS(
            f"AMIS scrape complete for {price_date}: upserted={upserted}, skipped={skipped}, base_url={base_url}, market={market_filter or '(none)'}"
        ))