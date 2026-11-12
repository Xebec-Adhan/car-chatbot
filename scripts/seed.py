
"""Create tables and load 40 sample used cars (Rs 3L-25L).

Usage (from the project root):
    python -m scripts.seed            # seed only if the cars table is empty
    python -m scripts.seed --reset    # drop all tables and reseed
"""
import argparse
import logging
from datetime import date, timedelta

from sqlalchemy import func, select

from app.db import (
    STATUS_AVAILABLE as A,
    STATUS_RESERVED as R,
    STATUS_SOLD as S,
    Base,
    Car,
    engine,
    get_session,
    init_db,
)

log = logging.getLogger("seed")

WARRANTY = "Free 1-year extended warranty"
INSURANCE = "Free insurance transfer"
SERVICE = "Free first service"
TWO_SERVICES = "Free first two services"

# make, model, year, price (Rs), km, fuel, transmission, body, seats, days_in_stock, promo, status
ROWS: list[tuple] = [
    ("Maruti Suzuki", "Alto K10 VXi", 2018, 305_000, 52_000, "petrol", "manual", "hatchback", 5, 120, SERVICE, A),
    ("Maruti Suzuki", "WagonR VXi", 2019, 345_000, 48_000, "petrol", "manual", "hatchback", 5, 45, None, A),
    ("Maruti Suzuki", "Celerio VXi CNG", 2020, 410_000, 62_000, "cng", "manual", "hatchback", 5, 130, "Free 6-month warranty", A),
    ("Renault", "Kwid RXT", 2019, 320_000, 41_000, "petrol", "manual", "hatchback", 5, 22, None, A),
    ("Tata", "Tiago XZ", 2020, 450_000, 38_000, "petrol", "manual", "hatchback", 5, 60, INSURANCE, A),
    ("Hyundai", "Grand i10 Nios Sportz", 2021, 540_000, 29_000, "petrol", "manual", "hatchback", 5, 15, None, A),
    ("Maruti Suzuki", "Swift VXi AMT", 2021, 585_000, 33_000, "petrol", "automatic", "hatchback", 5, 75, "Rs 10,000 off on exchange of your old car", A),
    ("Maruti Suzuki", "Swift ZXi", 2022, 680_000, 21_000, "petrol", "manual", "hatchback", 5, 12, None, S),
    ("Maruti Suzuki", "Baleno Delta", 2020, 595_000, 44_000, "petrol", "manual", "hatchback", 5, 70, None, A),
    ("Hyundai", "i20 Asta", 2021, 760_000, 27_000, "petrol", "manual", "hatchback", 5, 33, WARRANTY, A),
    ("Tata", "Altroz XZ Diesel", 2020, 690_000, 55_000, "diesel", "manual", "hatchback", 5, 105, WARRANTY, A),
    ("Maruti Suzuki", "Dzire ZXi AMT", 2020, 620_000, 46_000, "petrol", "automatic", "sedan", 5, 40, None, A),
    ("Hyundai", "Aura S CNG", 2021, 560_000, 58_000, "cng", "manual", "sedan", 5, 28, None, A),
    ("Honda", "Amaze VX CVT", 2020, 650_000, 42_000, "petrol", "automatic", "sedan", 5, 88, None, A),
    ("Hyundai", "Verna SX Diesel", 2020, 920_000, 47_000, "diesel", "manual", "sedan", 5, 150, "Rs 15,000 off on exchange of your old car", A),
    ("Volkswagen", "Virtus Topline 1.0 TSI AT", 2022, 1_250_000, 24_000, "petrol", "automatic", "sedan", 5, 18, None, A),
    ("Maruti Suzuki", "Brezza VXi", 2020, 790_000, 49_000, "petrol", "manual", "suv", 5, 36, None, A),
    ("Maruti Suzuki", "Brezza ZXi+ AT", 2022, 1_080_000, 26_000, "petrol", "automatic", "suv", 5, 25, WARRANTY, A),
    ("Maruti Suzuki", "Fronx Delta+", 2023, 920_000, 14_000, "petrol", "manual", "suv", 5, 11, None, A),
    ("Tata", "Punch Adventure", 2022, 640_000, 30_000, "petrol", "manual", "suv", 5, 55, None, A),
    ("Tata", "Nexon XZ+ Diesel", 2020, 910_000, 58_000, "diesel", "manual", "suv", 5, 175, "Rs 20,000 off on exchange of your old car", A),
    ("Tata", "Nexon EV Prime", 2021, 1_250_000, 32_000, "electric", "automatic", "suv", 5, 42, "Free home charger installation", A),
    ("Tata", "Tiago EV XZ+", 2023, 810_000, 15_000, "electric", "automatic", "hatchback", 5, 20, None, A),
    ("Hyundai", "Venue SX Diesel", 2021, 1_050_000, 40_000, "diesel", "manual", "suv", 5, 62, None, A),
    ("Kia", "Sonet HTX", 2021, 980_000, 37_000, "petrol", "manual", "suv", 5, 80, INSURANCE, A),
    ("Mahindra", "XUV300 W8 Diesel", 2020, 870_000, 52_000, "diesel", "manual", "suv", 5, 98, WARRANTY, A),
    ("Hyundai", "Creta SX Diesel AT", 2020, 1_380_000, 45_000, "diesel", "automatic", "suv", 5, 48, None, R),
    ("Kia", "Seltos HTX", 2021, 1_450_000, 39_000, "petrol", "manual", "suv", 5, 31, None, A),
    ("Toyota", "Urban Cruiser Hyryder V Hybrid", 2023, 1_480_000, 16_000, "hybrid", "automatic", "suv", 5, 14, SERVICE, A),
    ("Mahindra", "Thar LX Hard Top", 2022, 1_650_000, 28_000, "diesel", "manual", "suv", 4, 21, None, A),
    ("MG", "Hector Sharp Diesel", 2021, 1_420_000, 43_000, "diesel", "manual", "suv", 5, 160, "Rs 25,000 off on exchange of your old car", A),
    ("Tata", "Harrier XZ+", 2021, 1_550_000, 41_000, "diesel", "manual", "suv", 5, 38, None, A),
    ("Mahindra", "XUV700 AX7 Diesel AT", 2022, 2_150_000, 34_000, "diesel", "automatic", "suv", 7, 27, None, A),
    ("Tata", "Safari XZA+", 2022, 2_050_000, 36_000, "diesel", "automatic", "suv", 7, 52, TWO_SERVICES, A),
    ("Maruti Suzuki", "Ertiga VXi", 2020, 810_000, 56_000, "petrol", "manual", "muv", 7, 44, None, S),
    ("Renault", "Triber RXZ", 2021, 640_000, 33_000, "petrol", "manual", "muv", 7, 190, WARRANTY, A),
    ("Kia", "Carens Luxury", 2022, 1_320_000, 29_000, "diesel", "manual", "muv", 7, 35, None, A),
    ("Toyota", "Innova Crysta 2.4 GX", 2018, 1_750_000, 100_000, "diesel", "manual", "muv", 7, 66, None, A),
    ("Toyota", "Innova Hycross ZX Hybrid", 2023, 2_450_000, 18_000, "hybrid", "automatic", "muv", 7, 23, TWO_SERVICES, A),
    ("Skoda", "Slavia Style 1.0 TSI", 2022, 1_180_000, 22_000, "petrol", "manual", "sedan", 5, 30, None, A),
]
assert len(ROWS) == 40


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    init_db()
    today = date.today()

    with get_session() as s:
        if s.scalar(select(func.count(Car.id))):
            log.info("cars table already populated; use --reset to reload")
            return
        for i, row in enumerate(ROWS, start=1):
            make, model, year, price, km, fuel, trans, body, seats, days, promo, status = row
            s.add(
                Car(
                    make=make, model=model, year=year, price=price, km_driven=km,
                    fuel_type=fuel, transmission=trans, body_type=body, seats=seats,
                    date_added=today - timedelta(days=days),
                    promo_offer=promo,
                    image_url=f"https://ik.imagekit.io/forproject/eyes_ctcE5ZJ66.png?updatedAt=1777301578481",  # placeholder
                    status=status,
                )
            )

    aged = sum(1 for r in ROWS if r[9] >= 90 and r[11] == A)
    log.info("seeded %d cars (%d aged 90+ days, %d not available)", len(ROWS), aged,
             sum(1 for r in ROWS if r[11] != A))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop all tables and reseed")
    seed(reset=parser.parse_args().reset)