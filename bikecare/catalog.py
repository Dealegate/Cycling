"""What wears out on a bicycle, how fast, and what makes it wear faster.

Every component kind has a service interval in up to three units - kilometres,
days, riding hours - and whichever runs out first is what the reminder is
about.  Kilometres here are *effective* kilometres: a ride is weighted by what
it did to that particular part (see ``wear.ride_load``), so a wet gravel day
eats a chain faster than the same distance on a trainer, and a trainer hour
does nothing to the brake pads at all.

The weights are deliberately coarse.  They are a rule of thumb from workshop
practice, not a model; the point is to move a reminder by a few rides in the
right direction, not to predict the day a chain snaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    km: float | None = None        # effective kilometres between services
    days: int | None = None        # calendar days between services
    hours: float | None = None     # moving hours between services
    action: str = "replace"        # what "log service" means for it
    # How much each kind of riding counts towards this part, on top of 1.0.
    dirt: float = 0.0              # gravel / MTB surface
    climb: float = 0.0             # per 10 m of climbing per km
    trainer: float = 1.0           # multiplier for indoor rides
    prep: tuple[str, ...] = field(default_factory=tuple)


KINDS: dict[str, Kind] = {k.key: k for k in [
    Kind("chain_lube", "Смазка цепи", km=300, days=21, action="service",
         dirt=0.8, trainer=0.6,
         prep=("Обезжириватель и ветошь", "Смазка (wet для грязи, dry для сухо)",
               "Протереть излишки через 10 минут")),
    Kind("chain", "Цепь", km=3000, dirt=0.5, climb=0.15, trainer=1.0,
         prep=("Калибр износа цепи (0.5 / 0.75)", "Выжимка цепи или замок",
               "Новая цепь нужной скоростности")),
    Kind("cassette", "Кассета", km=9000, dirt=0.4, climb=0.15,
         prep=("Съёмник кассеты и хлыст", "Ключ 40 Нм")),
    Kind("chainrings", "Звёзды системы", km=15000, dirt=0.3, climb=0.1),
    Kind("brake_pads_front", "Колодки передние", km=2000, dirt=0.8, climb=0.4,
         trainer=0.0,
         prep=("Колодки под ваш калипер", "Изопропиловый спирт",
               "Проверить толщину ротора (min 1.5 мм)")),
    Kind("brake_pads_rear", "Колодки задние", km=2000, dirt=0.8, climb=0.3,
         trainer=0.0,
         prep=("Колодки под ваш калипер", "Изопропиловый спирт")),
    Kind("brake_bleed", "Прокачка тормозов", days=365, km=8000, action="service",
         trainer=0.0,
         prep=("Набор для прокачки", "Минералка или DOT - смотрите калипер",
               "Перчатки, ветошь")),
    Kind("rotors", "Роторы", km=12000, dirt=0.5, climb=0.4, trainer=0.0),
    Kind("tire_front", "Покрышка передняя", km=5000, days=1095, dirt=0.5,
         trainer=0.0),
    Kind("tire_rear", "Покрышка задняя", km=3500, days=1095, dirt=0.5,
         climb=0.1, trainer=0.3),
    Kind("sealant", "Герметик", days=90, action="service", trainer=0.0,
         prep=("60-90 мл герметика на колесо", "Шприц или съёмный ниппель",
               "Насос с ресивером на случай отрыва борта")),
    Kind("bar_tape", "Обмотка руля", km=8000, days=365, trainer=1.5),
    Kind("cables", "Тросики и рубашки", km=6000, days=730, dirt=0.5,
         action="replace"),
    Kind("bottom_bracket", "Каретка", km=10000, dirt=0.6, trainer=1.0),
    Kind("headset", "Рулевая колонка", km=10000, days=730, action="service",
         dirt=0.5, trainer=0.0),
    Kind("hubs", "Втулки (обслуживание)", km=8000, days=365, action="service",
         dirt=0.5, trainer=0.5),
    Kind("fork_lowers", "Вилка: нижние ноги", hours=50, action="service",
         dirt=0.5, trainer=0.0),
    Kind("shock", "Амортизатор", hours=50, action="service", dirt=0.5,
         trainer=0.0),
    Kind("dropper", "Дроппер", hours=100, action="service", dirt=0.5,
         trainer=0.0),
    Kind("full_service", "Полное ТО", km=5000, days=365, action="service",
         trainer=0.7,
         prep=("Мойка", "Проверка всех моментов затяжки",
               "Осмотр рамы на трещины")),
    Kind("custom", "Другое", action="replace"),
]}

# What a fresh bike gets when it first appears, by Strava frame type.
DEFAULT_SET = {
    "road": ["chain_lube", "chain", "cassette", "brake_pads_front",
             "brake_pads_rear", "tire_front", "tire_rear", "bar_tape",
             "full_service"],
    "gravel": ["chain_lube", "chain", "cassette", "brake_pads_front",
               "brake_pads_rear", "brake_bleed", "tire_front", "tire_rear",
               "sealant", "bar_tape", "full_service"],
    "mtb": ["chain_lube", "chain", "cassette", "brake_pads_front",
            "brake_pads_rear", "brake_bleed", "tire_front", "tire_rear",
            "sealant", "fork_lowers", "shock", "dropper", "full_service"],
    "city": ["chain_lube", "chain", "brake_pads_front", "brake_pads_rear",
             "tire_front", "tire_rear", "full_service"],
}

# Strava's frame_type numbers, from GET /gear/{id}.
STRAVA_FRAME = {1: "mtb", 2: "city", 3: "road", 4: "city", 5: "gravel",
                "MountainBike": "mtb", "Cross": "city", "Road": "road",
                "TimeTrial": "road", "Gravel": "gravel"}

DIRT_SPORTS = {"GravelRide", "MountainBikeRide", "EMountainBikeRide"}
CYCLING_SPORTS = DIRT_SPORTS | {"Ride", "VirtualRide", "EBikeRide",
                                "Velomobile", "Handcycle"}


def kind(key: str) -> Kind:
    return KINDS.get(key, KINDS["custom"])
