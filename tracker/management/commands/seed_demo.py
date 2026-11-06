"""Populate the database with realistic BodaTrack demo data.

Usage:
    python manage.py seed_demo --username admin --password <a-strong-password>
"""
import random
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import Motorcycle, OwnershipAgreement, Payment, Rider
from tracker.services import generate_instalments, record_payment

RIDERS = [
    ("Amina Namusoke", "0771 111 111"),
    ("Joseph Okello", "0772 222 222"),
    ("Sarah Namboozo", "0773 333 333"),
    ("Peter Ssemwanga", "0774 444 444"),
    ("Grace Atim", "0775 555 555"),
    ("Moses Byaruhanga", "0776 666 666"),
    ("Fatuma Nakato", "0777 777 777"),
    ("Robert Kizza", "0778 888 888"),
]

MOTORCYCLES = [
    ("UFA 123A", "TVSHLX125"),
    ("UFB 456B", "Bajaj Boxer BM150"),
    ("UFC 789C", "TVS HLX 150"),
    ("UFD 234D", "Bajaj Boxer BM100"),
    ("UFE 567E", "TVS HLX 150"),
    ("UFF 890F", "Bajaj Boxer BM150"),
    ("UFG 123G", "TVS HLX 125"),
    ("UFH 456H", "Honda Ace 110"),
]


class Command(BaseCommand):
    help = "Create a demo staff user, riders, motorcycles, agreements and payment history."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default="")

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]
        password = options["password"]
        if not password:
            self.stderr.write("Provide --password (cannot leave the staff password blank).")
            return
        if user := User.objects.filter(username=username).first():
            staff = user
            if not staff.is_staff:
                staff.is_staff = True
                staff.save(update_fields=["is_staff"])
        else:
            staff = User.objects.create_superuser(username, "", password)
        self.stdout.write(f"Staff user: {username}")

        riders = [Rider.objects.get_or_create(full_name=name, defaults={"phone_number": phone})[0]
                  for name, phone in RIDERS]
        motorcycles = [Motorcycle.objects.get_or_create(registration_number=plate, defaults={"make_model": model})[0]
                       for plate, model in MOTORCYCLES]

        today = timezone.localdate()
        rng = random.Random(2026)
        receipt_numbers = count(1)
        mm_refs = count(2401)

        for index, (rider, bike) in enumerate(zip(riders, motorcycles)):
            if OwnershipAgreement.objects.filter(motorcycle=bike).exists():
                continue
            total_price = Decimal("3500000") + Decimal(200_000 * index)
            weekly = Decimal("120000")
            start = today - timedelta(weeks=10, days=rng.randint(0, 3))
            agreement = OwnershipAgreement.objects.create(
                rider=rider, motorcycle=bike, total_price=total_price,
                weekly_amount=weekly, start_date=start, weekly_due_day=0,
            )
            generate_instalments(agreement)
            # Pay 4-8 week's worth in weekly steps so arrears look realistic.
            made = rng.randint(4, 8)
            paid = Decimal("0")
            for week in range(made):
                amount = weekly if rng.random() < 0.7 else Decimal("60000")
                amount = min(amount, total_price - paid)
                if amount <= 0:
                    break
                paid += amount
                is_mobile_money = rng.random() < 0.5
                record_payment(
                    agreement=agreement,
                    amount=amount,
                    paid_at=datetime.combine(start + timedelta(weeks=week + 1),
                                             datetime.min.time()).replace(tzinfo=datetime_timezone.utc),
                    method=Payment.Method.MOBILE_MONEY if is_mobile_money else Payment.Method.CASH,
                    receipt_number=f"RB-{next(receipt_numbers):04d}",
                    reference=(f"MP{next(mm_refs)}" if is_mobile_money else ""),
                    created_by=staff,
                )

        self.stdout.write("Demo data seeded.")
        self.stdout.write("Log in at the web app or Django admin with the staff user above.")
