"""انتخاب محصول/واریانت — هماهنگ با DISABLED_* در config."""


def enabled_product_skus(config) -> set[str] | None:
    """SKUهای فعال؛ None یعنی همه (بدون لیست غیرفعال)."""
    disabled = {
        str(s).strip()
        for s in (config or {}).get("DISABLED_PRODUCT_SKUS", []) or []
        if str(s).strip()
    }
    if not disabled:
        return None
    return disabled


def is_product_enabled(sku: str, config) -> bool:
    return str(sku or "").strip() not in set(
        (config or {}).get("DISABLED_PRODUCT_SKUS", []) or []
    )


def is_variation_enabled(variant_sku: str, config) -> bool:
    return str(variant_sku or "").strip() not in set(
        (config or {}).get("DISABLED_VARIATION_SKUS", []) or []
    )


def product_matches_groups(sku: str, selected_groups: list[str]) -> bool:
    code = str(sku or "").strip()
    groups = [str(g).strip() for g in (selected_groups or []) if str(g).strip()]
    if not groups:
        return False
    return any(code.startswith(g) for g in groups)
