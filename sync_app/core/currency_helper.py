""" تومان/ریال """

from __future__ import annotations


def is_toman(config: dict) -> bool:
    if config is None:
        return True
    return bool(config.get("WC_CURRENCY_IS_TOMAN", True))


def wc_total_to_erp_amount(total, config: dict) -> float:
    """ مبلغ Woo به ریال ERP """
    value = float(total or 0)
    if is_toman(config):
        return value * 10.0
    return value


def erp_price_divisor(config: dict) -> float:
    """ تقسیم قیمت ERP برای Woo """
    return 10.0 if is_toman(config) else 1.0


def currency_label(config: dict) -> str:
    return "تومان" if is_toman(config) else "ریال"
