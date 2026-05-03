import re

def calculate_rank(qr_count_30d: int):
    if qr_count_30d >= 60:
        return "Элита", 1.0
    elif qr_count_30d >= 30:
        return "Профи", 0.5
    else:
        return "Старт", 0.0

def calculate_volume_points(qr_today: int) -> float:
    if qr_today >= 21: return 5
    elif qr_today >= 11: return 4
    elif qr_today >= 6: return 3
    elif qr_today >= 3: return 2
    elif qr_today >= 1: return 1
    else: return 0

def calculate_regularity_points(active_days_30: int) -> float:
    if active_days_30 >= 30: return 4
    elif active_days_30 >= 26: return 3.5
    elif active_days_30 >= 21: return 3
    elif active_days_30 >= 16: return 2.5
    elif active_days_30 >= 11: return 2
    elif active_days_30 >= 6: return 1.5
    elif active_days_30 >= 1: return 1
    else: return 0

def calculate_priority(volume: float, regularity: float) -> float:
    return volume + regularity

def validate_phone(phone: str) -> bool:
    phone = re.sub(r'\D', '', phone)
    return len(phone) == 11 and phone.startswith('7')

def normalize_phone(phone: str) -> str:
    return re.sub(r'\D', '', phone)