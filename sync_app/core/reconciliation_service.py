"""مقایسه ERP ↔ ووکامرس و ثبت نگاشت دستی/خودکار."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests

from sync_app.core.article_price import resolve_article_price, resolve_sale_article_price
from sync_app.core.category_resolver import (
    build_code_index_from_slug_map,
    dejavu_category_slug,
    extract_code_from_wc_slug,
    fetch_wc_slug_map,
    load_category_map,
    save_category_map,
)
from sync_app.core.product_woo_map_helper import load_product_woo_map, save_product_woo_map
from sync_app.core.product_woo_map_meta import (
    clear_product_link_meta,
    register_product_link,
)
from sync_app.core.sql_connection_helper import open_sql_connection
from sync_app.core.sync_utils import log
from sync_app.core.wc_sync_helper import (
    apply_network_overrides,
    wc_timeout_pair,
    WC_SYNC_BACKOFF,
    WC_SYNC_BACKOFF_FAST,
    WC_SYNC_RETRIES,
    wc_rest_request,
    wc_http_error_message,
)

RECON_WC_CONNECT_TIMEOUT = 20.0
RECON_WC_READ_TIMEOUT = 60.0
RECON_WC_MAX_ATTEMPTS = 2

_WC_PATH_LABELS = {
    "products": "محصولات",
    "categories": "دسته‌بندی‌ها",
    "products/attributes": "ویژگی‌ها",
}


ENTITY_CATEGORIES = "categories"
ENTITY_PRODUCTS = "products"
ENTITY_VARIATIONS = "variations"
ENTITY_ATTRIBUTES = "attributes"

ENTITY_LABELS = {
    ENTITY_CATEGORIES: "دسته‌بندی",
    ENTITY_PRODUCTS: "محصول",
    ENTITY_VARIATIONS: "متغیر",
    ENTITY_ATTRIBUTES: "ویژگی",
}

_ACTIVE_WC_STATUSES = frozenset({"publish", "draft", "private", "pending"})


@dataclass
class ReconRow:
    key: str
    label: str
    synced: bool
    side: str
    wc_id: int | None = None
    erp_key: str | None = None
    match_key: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class ComparisonResult:
    entity: str
    erp_rows: list[ReconRow]
    wc_rows: list[ReconRow]
    stats: dict[str, int]


_COMPARISON_CACHE: dict[str, tuple[float, ComparisonResult]] = {}
_COMPARISON_CACHE_TTL_SEC = 180.0
_WC_VARIATION_FETCH_WORKERS = 8


def _comparison_cache_key(config: dict, entity: str) -> str:
    sql_db = str((config or {}).get("SQL_DATABASE") or (config or {}).get("DATABASE") or "").strip()
    wc_url = str((config or {}).get("WC_URL") or (config or {}).get("WOOCOMMERCE_URL") or "").strip().rstrip("/")
    return f"{entity}|{sql_db}|{wc_url}"


def invalidate_comparison_cache(entity: str | None = None) -> None:
    if not entity:
        _COMPARISON_CACHE.clear()
        return
    prefix = f"{entity}|"
    for key in list(_COMPARISON_CACHE):
        if key.startswith(prefix):
            del _COMPARISON_CACHE[key]


@dataclass
class LinkPairRisk:
    erp_label: str
    wc_label: str
    erp_name: str
    wc_name: str
    erp_sku: str
    wc_sku: str
    warnings: list[str]


@dataclass
class SuggestedPair:
    erp: ReconRow
    wc: ReconRow
    reason: str


SUGGEST_REASON_MATCH_KEY = "match_key"
SUGGEST_REASON_NAME_EXACT = "name_exact"
SUGGEST_REASON_NAME_SIMILAR = "name_similar"
SUGGEST_REASON_PARENT_PLACEHOLDER = "parent_placeholder"

_LEGACY_SUGGEST_REASONS = {
    "SKU/نامک یکسان": SUGGEST_REASON_MATCH_KEY,
    "نام یکسان": SUGGEST_REASON_NAME_EXACT,
    "نام مشابه": SUGGEST_REASON_NAME_SIMILAR,
}


def normalize_suggestion_reason(reason: str) -> str:
    text = str(reason or "").strip()
    return _LEGACY_SUGGEST_REASONS.get(text, text)


def format_suggestion_tooltip(reason: str, erp: ReconRow, wc: ReconRow, config: dict | None = None) -> str:
    """متن راهنمای فارسی برای hover روی پیشنهاد سیستم — بدون اصطلاح فنی در لیست."""
    from sync_app.core.integrations.erp_provider import erp_provider_label

    erp_label = erp_provider_label(config)
    code = normalize_suggestion_reason(reason)
    match_code = str(erp.match_key or wc.match_key or "").strip()
    if code == SUGGEST_REASON_MATCH_KEY:
        code_line = f"کد محصول «{match_code}» در {erp_label} و فروشگاه یکسان است."
        if not match_code:
            code_line = f"کد محصول در {erp_label} و فروشگاه یکسان است."
        return (
            f"پیشنهاد سیستم: {code_line}\n"
            "برای ثبت «پذیرش» بزنید؛ اگر اشتباه است «رد پیشنهاد»."
        )
    if code == SUGGEST_REASON_NAME_EXACT:
        return (
            f"پیشنهاد سیستم: نام محصول در {erp_label} و فروشگاه دقیقاً یکی است.\n"
            "قبل از پذیرش، کد و جزئیات را هم مقایسه کنید."
        )
    if code == SUGGEST_REASON_NAME_SIMILAR:
        return (
            f"پیشنهاد سیستم: نام محصول در {erp_label} و فروشگاه شبیه هم است.\n"
            "احتمال اشتباه وجود دارد — حتماً بررسی کنید."
        )
    if code == SUGGEST_REASON_PARENT_PLACEHOLDER:
        parent_sku = str((erp.extra or {}).get("parent_sku") or wc.match_key or "").strip()
        return (
            f"پیشنهاد سیستم: محصول والد «{parent_sku}» در سایت هنوز واریانت ندارد؛\n"
            f"با یک متغیر {erp_label} همان کالا جفت می‌شود تا بعداً همگام‌سازی متغیرها اجرا شود.\n"
            "قبل از پذیرش، کد والد و نام را بررسی کنید."
        )
    return "پیشنهاد سیستم — قبل از پذیرش جزئیات را بررسی کنید."


def _normalize_name(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("ي", "ی").replace("ك", "ک")
    return " ".join(text.split())


def _label_prefix(label: str, *separators: str) -> str:
    text = str(label or "").strip()
    for sep in separators:
        if sep in text:
            return text.split(sep, 1)[0].strip()
    if "—" in text:
        return text.split("—", 1)[0].strip()
    return text


def row_display_name(row: ReconRow, entity: str) -> str:
    extra = row.extra or {}
    if entity == ENTITY_PRODUCTS:
        return str(extra.get("name") or _label_prefix(row.label, " — SKU ")).strip()
    if entity == ENTITY_VARIATIONS:
        base = str(extra.get("name") or extra.get("parent_name") or "").strip()
        if not base:
            base = _label_prefix(row.label, " — SKU ", " › ")
        if row.side == "erp":
            parts = [
                str(extra.get("size") or "").strip(),
                str(extra.get("color") or "").strip(),
                str(extra.get("dim3") or "").strip(),
            ]
            parts = [p for p in parts if p]
            if parts:
                return f"{base} — {'/'.join(parts)}".strip(" —/")
        attrs = str(extra.get("attributes") or "").strip()
        if attrs and attrs != "—":
            return f"{base} › {attrs}".strip()
        return base
    if entity == ENTITY_CATEGORIES:
        return _label_prefix(row.label, " — کد ", " — #")
    return _label_prefix(row.label)


def row_match_key(row: ReconRow, entity: str) -> str:
    extra = row.extra or {}
    if entity == ENTITY_VARIATIONS:
        return str(extra.get("variation_sku") or extra.get("parent_sku") or row.match_key or "").strip()
    if entity == ENTITY_CATEGORIES:
        return str(extra.get("slug") or extra.get("code") or row.match_key or "").strip()
    return str(extra.get("sku") or row.match_key or row.erp_key or "").strip()


def _names_seem_incompatible(left: str, right: str) -> bool:
    left_n = _normalize_name(left)
    right_n = _normalize_name(right)
    if not left_n or not right_n:
        return False
    if left_n.casefold() == right_n.casefold():
        return False
    if left_n in right_n or right_n in left_n:
        return False

    left_tokens = set(left_n.split())
    right_tokens = set(right_n.split())
    if left_tokens & right_tokens:
        return False
    return True


def _names_match_well(left: str, right: str) -> bool:
    left_n = _normalize_name(left)
    right_n = _normalize_name(right)
    if not left_n or not right_n:
        return False
    if left_n.casefold() == right_n.casefold():
        return True
    if left_n in right_n or right_n in left_n:
        return True
    return bool(set(left_n.split()) & set(right_n.split()))


def assess_link_pair_risks(entity: str, erp: ReconRow, wc: ReconRow, config: dict | None = None) -> LinkPairRisk:
    from sync_app.core.integrations.erp_provider import erp_provider_label

    erp_name = row_display_name(erp, entity)
    wc_name = row_display_name(wc, entity)
    erp_sku = row_match_key(erp, entity)
    wc_sku = row_match_key(wc, entity)
    warnings: list[str] = []

    if _names_seem_incompatible(erp_name, wc_name):
        warnings.append(
            f"نام‌ها متفاوت به نظر می‌رسند: «{erp_name or '—'}» در برابر «{wc_name or '—'}»"
        )

    if erp_sku and wc_sku and erp_sku.casefold() != wc_sku.casefold():
        warnings.append(f"SKU/کلید یکسان نیست: {erp_provider_label(config)} «{erp_sku}» ↔ Woo «{wc_sku}»")

    return LinkPairRisk(
        erp_label=erp.label,
        wc_label=wc.label,
        erp_name=erp_name,
        wc_name=wc_name,
        erp_sku=erp_sku,
        wc_sku=wc_sku,
        warnings=warnings,
    )


def find_wc_sku_collision(
    erp_sku: str,
    target_wc_id: int,
    wc_rows: list[ReconRow],
) -> ReconRow | None:
    """محصول دیگری در لیست Woo که همان SKU ERP را دارد (غیر از مقصد تطبیق)."""
    sku_key = str(erp_sku or "").strip().casefold()
    target_wc_id = int(target_wc_id or 0)
    if not sku_key or not target_wc_id:
        return None
    for wc in wc_rows:
        wc_id = int(wc.wc_id or 0)
        if not wc_id or wc_id == target_wc_id:
            continue
        wc_sku = str(wc.match_key or wc.erp_key or "").strip().casefold()
        if wc_sku and wc_sku == sku_key:
            return wc
    return None


def assess_commit_link_risks(
    entity: str,
    pairs: list[tuple[ReconRow, ReconRow]],
    wc_rows: list[ReconRow] | None = None,
    config: dict | None = None,
) -> list[LinkPairRisk]:
    """ریسک‌های ثبت نهایی، شامل تضاد SKU در سایت."""
    risks: list[LinkPairRisk] = []
    for erp, wc in pairs:
        risk = assess_link_pair_risks(entity, erp, wc, config)
        if entity == ENTITY_PRODUCTS and wc_rows:
            erp_sku = row_match_key(erp, entity)
            conflict = find_wc_sku_collision(erp_sku, int(wc.wc_id or 0), wc_rows)
            if conflict:
                risk.warnings.append(
                    "تضاد SKU: محصول دیگر سایت "
                    f"«{row_display_name(conflict, entity)}» (#{conflict.wc_id}) "
                    f"همین SKU «{erp_sku}» را دارد — "
                    f"ارسال بعدی فقط به #{wc.wc_id} می‌رود (SKU سایت عوض نمی‌شود)"
                )
        if risk.warnings:
            risks.append(risk)
    return risks


class ReconciliationCancelled(Exception):
    """بارگذاری مقایسه توسط کاربر متوقف شد."""


def _check_recon_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check and cancel_check():
        raise ReconciliationCancelled("بارگذاری مقایسه توسط کاربر متوقف شد.")


def format_recon_load_error(message: str, config: dict | None = None) -> str:
    """پیام خطای بارگذاری مقایسه را برای نمایش در UI فارسی می‌کند."""
    from urllib.parse import urlparse

    from sync_app.core.connectivity_service import (
        classify_network_error,
        network_error_user_hint,
    )

    raw = str(message or "").strip()
    if isinstance(message, ReconciliationCancelled) or "متوقف شد" in raw:
        return raw

    err_text = raw
    prefix = ""
    if raw.startswith("دریافت ") and " ناموفق:" in raw:
        head, _, tail = raw.partition(" ناموفق:")
        path = head.replace("دریافت ", "", 1).strip()
        label = _WC_PATH_LABELS.get(path, path)
        prefix = f"دریافت {label} از ووکامرس ناموفق بود.\n"
        err_text = tail.strip()

    config = config or {}
    host = urlparse(str(config.get("WC_URL") or "")).netloc or "فروشگاه"
    target = f"فروشگاه ({host})" if host != "فروشگاه" else "فروشگاه"
    category = classify_network_error(err_text or raw)
    hint = network_error_user_hint(category, target=target)
    return f"{prefix}{hint}".strip()


def recompute_comparison_stats(result: ComparisonResult) -> None:
    result.stats = _compute_stats(result.erp_rows, result.wc_rows)


def mark_comparison_pairs_synced(
    result: ComparisonResult,
    pairs: list[tuple[ReconRow, ReconRow]],
) -> None:
    erp_keys = {erp.key for erp, _ in pairs}
    wc_keys = {wc.key for _, wc in pairs}
    for row in result.erp_rows:
        if row.key in erp_keys:
            row.synced = True
    for row in result.wc_rows:
        if row.key in wc_keys:
            row.synced = True
    recompute_comparison_stats(result)


def _recon_http_timeout(config: dict) -> tuple[float, float]:
    connect, read = wc_timeout_pair(config)
    return (
        min(connect, RECON_WC_CONNECT_TIMEOUT),
        min(read, RECON_WC_READ_TIMEOUT),
    )


def _wc_get_paginated(
    config: dict,
    path: str,
    *,
    params=None,
    timeout=60,
    cancel_check: Callable[[], bool] | None = None,
) -> list:
    apply_network_overrides(config or {})
    if not (config or {}).get("WC_URL"):
        raise RuntimeError("آدرس ووکامرس تنظیم نشده است.")

    base_params = dict(params or {})
    base_params.setdefault("per_page", 100)
    if cancel_check:
        http_timeout = _recon_http_timeout(config)
        max_attempts = RECON_WC_MAX_ATTEMPTS
        backoff = WC_SYNC_BACKOFF_FAST
    else:
        http_timeout = wc_timeout_pair(config)
        max_attempts = WC_SYNC_RETRIES + 1
        backoff = WC_SYNC_BACKOFF
    all_rows: list = []
    page = 1

    while True:
        _check_recon_cancel(cancel_check)
        last_error = None
        batch = None
        for attempt in range(1, max_attempts + 1):
            _check_recon_cancel(cancel_check)
            try:
                resp = wc_rest_request(
                    config,
                    "GET",
                    path,
                    params={**base_params, "page": page},
                    timeout=http_timeout,
                )
                if int(resp.status_code or 0) >= 400:
                    raise RuntimeError(
                        wc_http_error_message(
                            resp,
                            config,
                            prefix=f"دریافت {path} ناموفق",
                        )
                    )
                batch = resp.json()
                break
            except ReconciliationCancelled:
                raise
            except RuntimeError:
                raise
            except Exception as err:
                if cancel_check and cancel_check():
                    raise ReconciliationCancelled(
                        "بارگذاری مقایسه توسط کاربر متوقف شد."
                    ) from err
                last_error = err
                if attempt < max_attempts:
                    wait = backoff[min(attempt - 1, len(backoff) - 1)]
                    log.warning(
                        f"⚠️ دریافت {path} صفحه {page} — تلاش {attempt}: {err} ({wait:.0f}s)"
                    )
                    import time

                    end = time.monotonic() + wait
                    while time.monotonic() < end:
                        _check_recon_cancel(cancel_check)
                        time.sleep(min(0.1, max(0.0, end - time.monotonic())))
        if batch is None:
            if cancel_check and cancel_check():
                raise ReconciliationCancelled("بارگذاری مقایسه توسط کاربر متوقف شد.")
            raise RuntimeError(
                format_recon_load_error(
                    f"دریافت {path} ناموفق: {last_error}",
                    config,
                )
            )

        if not isinstance(batch, list) or not batch:
            break
        all_rows.extend(batch)
        if len(batch) < int(base_params.get("per_page", 100)):
            break
        page += 1
    return all_rows


def _fetch_erp_categories(config: dict) -> list[ReconRow]:
    conn, _, _ = open_sql_connection(config, timeout=8)
    cursor = conn.cursor()
    cursor.execute("SELECT M_Groupcode, M_GroupName FROM M_Group ORDER BY M_Groupcode")
    main_groups = {str(r[0]).strip(): str(r[1]).strip() for r in cursor.fetchall()}
    cursor.execute(
        "SELECT M_Groupcode, S_Groupcode, S_GroupName FROM S_Group ORDER BY M_Groupcode, S_Groupcode"
    )
    rows: list[ReconRow] = []
    for m_code, m_name in main_groups.items():
        slug = dejavu_category_slug(m_code)
        rows.append(
            ReconRow(
                key=f"erp:{m_code}",
                erp_key=m_code,
                label=f"{m_name} — کد {m_code}",
                synced=False,
                side="erp",
                match_key=slug,
                extra={"level": "main", "slug": slug},
            )
        )

    for m_code, s_code, s_name in cursor.fetchall():
        full_code = f"{m_code}{s_code}"
        slug = dejavu_category_slug(full_code)
        parent_name = main_groups.get(m_code, m_code)
        rows.append(
            ReconRow(
                key=f"erp:{full_code}",
                erp_key=full_code,
                label=f"{parent_name} › {s_name} — کد {full_code}",
                synced=False,
                side="erp",
                match_key=slug,
                extra={"level": "sub", "slug": slug},
            )
        )
    conn.close()
    return rows


def _fetch_wc_categories(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.integrations.commerce_provider import fetch_store_slug_map

    def _raise_if_cancelled() -> None:
        _check_recon_cancel(cancel_check)

    # fetch_store_slug_map پلتفرم رو خودش تشخیص می‌ده (ووکامرس یا پرستاشاپ) —
    # slug دسته‌بندی (cat-XXXX) روی هر دو پلتفرم با همون dejavu_category_slug
    # ساخته می‌شه، پس extract_code_from_wc_slug بدون تغییر کار می‌کنه.
    slug_map = fetch_store_slug_map(
        config,
        timeout=_recon_http_timeout(config),
        cancel_check=_raise_if_cancelled,
    )
    rows: list[ReconRow] = []

    for slug, entry in slug_map.items():
        if not isinstance(entry, dict):
            continue
        wc_id = int(entry.get("id") or 0)
        if not wc_id:
            continue
        code = extract_code_from_wc_slug(slug) or ""
        name = str(entry.get("name") or slug).strip()
        rows.append(
            ReconRow(
                key=f"wc:{wc_id}",
                wc_id=wc_id,
                label=f"{name} — #{wc_id} — نامک {slug}",
                synced=False,
                side="wc",
                match_key=slug,
                erp_key=code or None,
                extra={"slug": slug, "code": code},
            )
        )
    rows.sort(key=lambda r: (bool(r.synced), str(r.label or "")))
    return rows


def _fetch_erp_products(config: dict) -> list[ReconRow]:
    """همه محصولات ERP — بدون فیلتر گروه انتخاب‌شده (برای نگاشت فروشگاه موجود)."""
    price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")
    conn, _, _ = open_sql_connection(config, timeout=8)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5, Exist, A_Code_C
        FROM Article
        ORDER BY A_Code
        """
    )

    rows: list[ReconRow] = []
    for row in cursor.fetchall():
        sku = str(row[0]).strip()
        name = str(row[1]).strip()
        price = resolve_article_price(row, price_col, price_start_index=2)
        sale_price = resolve_sale_article_price(row, config, price_start_index=2)
        stock = int(row[7] or 0)
        manual_code = str(row[8] or "").strip() if len(row) > 8 else ""

        # ترتیب راست‌به‌چپ: نام - کد اتوماتیک - کد دستی - قیمت عادی - قیمت ویژه - موجودی
        # بدون عنوان کلمه‌ای (کد/قیمت/موجودی) — چون با کاراکترهای انگلیسی به‌هم می‌ریخت.
        parts = [name, sku]
        if manual_code:
            parts.append(manual_code)
        parts.append(f"{price:,.0f}")
        if sale_price > 0:
            parts.append(f"{sale_price:,.0f}")
        parts.append(str(stock))
        label = " - ".join(parts)

        rows.append(
            ReconRow(
                key=f"erp:{sku}",
                erp_key=sku,
                label=label,
                synced=False,
                side="erp",
                match_key=sku.lower(),
                extra={"sku": sku, "name": name, "a_code_c": manual_code, "sale_price": sale_price},
            )
        )
    conn.close()
    return rows


def _fetch_ps_products(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.ps_sync_helper import ps_list_products, ps_list_categories
    from sync_app.core.ps_variation_helper import ps_list_all_combinations_grouped

    _check_recon_cancel(cancel_check)
    timeout = _recon_http_timeout(config)
    products = ps_list_products(config, timeout=timeout)
    _check_recon_cancel(cancel_check)
    try:
        # برای تشخیص محصول متغیر — پرستاشاپ فیلد type نداره، باید از روی
        # وجود combination تشخیص بدیم. یک واکشی یک‌جا، نه N+1 هر محصول.
        grouped = ps_list_all_combinations_grouped(config, timeout=timeout)
    except Exception:
        grouped = {}
    try:
        # برای فیلترِ دسته‌بندیِ سایت — ps_list_products فقط idِ دسته رو
        # برمی‌گردونه، نامش رو از یک واکشیِ یک‌جای categories می‌گیریم.
        cat_name_by_id = {
            int(c["id"]): str(c.get("name") or "").strip()
            for c in ps_list_categories(config, timeout=timeout)
            if isinstance(c, dict) and c.get("id")
        }
    except Exception:
        cat_name_by_id = {}

    rows: list[ReconRow] = []
    for item in products:
        if not isinstance(item, dict):
            continue
        wc_id = int(item.get("id") or 0)
        if not wc_id:
            continue
        sku = str(item.get("sku") or "").strip()
        name = str(item.get("name") or "").strip()
        # پرستاشاپ زباله‌دان نداره — هر محصولی که برگرده یعنی هنوز روی
        # فروشگاهه (فیلتر _ACTIVE_WC_STATUSES معادلی نداره).
        ptype = "variable" if grouped.get(wc_id) else "simple"
        label = f"{name} — #{wc_id}"
        if sku:
            label += f" — کد {sku}"
        label += f" — {ptype}"
        categories = [
            {"id": int(c["id"]), "name": cat_name_by_id.get(int(c["id"]), "")}
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("id")
        ]
        rows.append(
            ReconRow(
                key=f"wc:{wc_id}",
                wc_id=wc_id,
                label=label,
                synced=False,
                side="wc",
                match_key=sku.lower() if sku else "",
                erp_key=sku or None,
                extra={"sku": sku, "type": ptype, "name": name, "categories": categories},
            )
        )
    rows.sort(key=lambda r: (bool(r.synced), str(r.label or "")))
    return rows


def _fetch_wc_products(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        return _fetch_ps_products(config, cancel_check=cancel_check)

    products = _wc_get_paginated(
        config,
        "products",
        params={
            "status": "any",
            "_fields": "id,sku,name,status,type,categories",
        },
        cancel_check=cancel_check,
    )
    rows: list[ReconRow] = []
    for item in products:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip()
        if status not in _ACTIVE_WC_STATUSES:
            continue
        wc_id = int(item.get("id") or 0)
        if not wc_id:
            continue
        sku = str(item.get("sku") or "").strip()
        name = str(item.get("name") or "").strip()
        ptype = str(item.get("type") or "simple").strip()
        label = f"{name} — #{wc_id}"
        if sku:
            label += f" — کد {sku}"
        label += f" — {ptype}"
        categories = [
            {"id": int(c["id"]), "name": str(c.get("name") or "").strip()}
            for c in (item.get("categories") or [])
            if isinstance(c, dict) and c.get("id")
        ]
        rows.append(
            ReconRow(
                key=f"wc:{wc_id}",
                wc_id=wc_id,
                label=label,
                synced=False,
                side="wc",
                match_key=sku.lower() if sku else "",
                erp_key=sku or None,
                extra={"sku": sku, "type": ptype, "name": name, "categories": categories},
            )
        )
    rows.sort(key=lambda r: (bool(r.synced), str(r.label or "")))
    return rows


def _mark_product_sync_by_map(erp_rows: list[ReconRow], wc_rows: list[ReconRow]) -> None:
    """تیک سبز فقط وقتی SKU در product_woo_map به همان محصول Woo وصل شده باشد."""
    product_map = load_product_woo_map()
    for row in erp_rows:
        row.synced = False
    for row in wc_rows:
        row.synced = False

    wc_by_id = {int(row.wc_id): row for row in wc_rows if row.wc_id}

    for erp in erp_rows:
        sku = str(erp.erp_key or erp.match_key or "").strip()
        if not sku:
            continue
        mapped_id = int(product_map.get(sku) or 0)
        if not mapped_id:
            continue
        wc = wc_by_id.get(mapped_id)
        if not wc:
            continue
        erp.synced = True
        wc.synced = True


def product_pair_in_map(erp: ReconRow, wc: ReconRow) -> bool:
    """آیا این جفت ERP↔Woo در product_woo_map.json ثبت شده؟"""
    sku = str(erp.erp_key or erp.match_key or "").strip()
    if not sku:
        return False
    product_map = load_product_woo_map()
    return int(product_map.get(sku) or 0) == int(wc.wc_id or 0)


def _variation_sku(a_code: str, poshak_id_c) -> str:
    from sync_app.core.variation_query import build_variation_sku

    return build_variation_sku(a_code, poshak_id_c)


def _fetch_erp_variations(config: dict) -> list[ReconRow]:
    """همه متغیرهای ERP — بدون فیلتر گروه (برای نگاشت فروشگاه موجود)."""
    from sync_app.core.variation_query import fetch_variation_rows
    from sync_app.core.variation_rules import _sync_row_indices, resolve_row_dimensions

    conn, _, _ = open_sql_connection(config, timeout=8)
    cursor = conn.cursor()
    sql_rows = fetch_variation_rows(cursor)
    article_names: dict[str, str] = {}
    cursor.execute("SELECT A_Code, A_Name FROM Article WHERE LEN(A_Code) >= 4")
    for code, name in cursor.fetchall():
        article_names[str(code).strip()] = str(name or "").strip()
    cursor.close()
    conn.close()

    rows: list[ReconRow] = []
    for row in sql_rows:
        if isinstance(row, dict):
            a_code = str(row.get("a_code") or "").strip()
            dim_pairs = row.get("dim_pairs") or []
            trait_parts = [str(v) for _, v in dim_pairs if v]
            dim1 = dim_pairs[0][1] if len(dim_pairs) > 0 else ""
            dim2 = dim_pairs[1][1] if len(dim_pairs) > 1 else ""
            dim3 = dim_pairs[2][1] if len(dim_pairs) > 2 else ""
            poshak_id_c = row.get("poshak_id_c")
            try:
                stock = int(row.get("few") or 0)
            except (TypeError, ValueError):
                stock = 0
        else:
            a_code = str(row[0]).strip()
            dim1, dim2, dim3, poshak_id_c, _poshak_id = resolve_row_dimensions(
                row, list_mode=False
            )
            idx = _sync_row_indices(row)
            try:
                stock = int(row[idx["stock"]] or 0) if len(row) > idx["stock"] else 0
            except (TypeError, ValueError):
                stock = 0
            trait_parts = [p for p in (dim1, dim2, dim3) if p]
        name = article_names.get(a_code, a_code)
        var_sku = _variation_sku(a_code, poshak_id_c)
        trait_text = "/".join(trait_parts) if trait_parts else "—"
        label = f"{name} — {trait_text} — کد {var_sku or '—'} — موجودی {stock}"
        rows.append(
            ReconRow(
                key=f"erp:{var_sku or a_code + ':' + str(poshak_id_c)}",
                erp_key=var_sku or a_code,
                label=label,
                synced=False,
                side="erp",
                match_key=(var_sku or "").lower(),
                extra={
                    "parent_sku": a_code,
                    "variation_sku": var_sku,
                    "name": name,
                    "size": dim1,
                    "color": dim2,
                    "dim3": dim3,
                    "poshak_id": poshak_id_c,
                },
            )
        )
    rows.sort(key=lambda r: (bool(r.synced), str(r.label or "")))
    return rows


def _fetch_parent_variations(
    config: dict,
    parent: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    if not isinstance(parent, dict):
        return []
    parent_id = int(parent.get("id") or 0)
    if not parent_id:
        return []
    parent_sku = str(parent.get("sku") or "").strip()
    parent_name = str(parent.get("name") or "").strip()
    product_map = load_product_woo_map()
    mapped_parent_ids = {int(v) for v in product_map.values() if v}
    parent_mapped = parent_id in mapped_parent_ids

    variations = _wc_get_paginated(
        config,
        f"products/{parent_id}/variations",
        params={"_fields": "id,sku,attributes"},
        cancel_check=cancel_check,
    )
    rows: list[ReconRow] = []
    for var in variations:
        _check_recon_cancel(cancel_check)
        if not isinstance(var, dict):
            continue
        vid = int(var.get("id") or 0)
        if not vid:
            continue
        sku = str(var.get("sku") or "").strip()
        attrs = var.get("attributes") or []
        attr_text = " / ".join(
            str(a.get("option") or "").strip()
            for a in attrs
            if isinstance(a, dict) and a.get("option")
        )
        label = f"{parent_name} › {attr_text or '—'}"
        if sku:
            label += f" — کد {sku}"
        label += f" — #{vid} (والد #{parent_id})"
        rows.append(
            ReconRow(
                key=f"wc:{parent_id}:{vid}",
                wc_id=vid,
                label=label,
                synced=False,
                side="wc",
                match_key=sku.lower() if sku else "",
                erp_key=sku or None,
                extra={
                    "parent_id": parent_id,
                    "parent_sku": parent_sku,
                    "parent_name": parent_name,
                    "variation_sku": sku,
                    "attributes": attr_text,
                    "parent_mapped": parent_mapped,
                },
            )
        )
    return rows


def _placeholder_parent_label(
    pname: str,
    psku: str,
    pid: int,
    *,
    parent_mapped: bool,
) -> str:
    """برچسب والد بدون واریانت — جدا از آیکن لیست (✅/⚠️)."""
    base = f"{pname} — کد {psku} — والد #{pid}"
    if parent_mapped:
        return (
            f"{base} — تطبیق والد ثبت شد؛ "
            "واریانت هنوز در سایت نیست (تب «متغیرها» را همگام کنید)"
        )
    return f"{base} — بدون واریانت در سایت — نیاز تطبیق والد"


def _append_empty_parent_variation_rows(
    parents: list[dict],
    rows: list[ReconRow],
    product_map: dict,
) -> None:
    """والدهای variable بدون واریانت — برای تطبیق دستی در تب تطبیق."""
    covered_ids = {int((r.extra or {}).get("parent_id") or 0) for r in rows}
    parent_by_id = {
        int(p.get("id")): p
        for p in parents
        if isinstance(p, dict) and p.get("id")
    }
    seen: set[int] = set()
    for erp_sku, woo_id in (product_map or {}).items():
        pid = int(woo_id or 0)
        if not pid or pid in covered_ids or pid in seen:
            continue
        parent = parent_by_id.get(pid)
        if not parent:
            continue
        psku = str(parent.get("sku") or erp_sku or "").strip()
        pname = str(parent.get("name") or "").strip()
        parent_mapped = int(product_map.get(psku) or product_map.get(erp_sku) or 0) == pid
        label = _placeholder_parent_label(pname, psku, pid, parent_mapped=parent_mapped)
        rows.append(
            ReconRow(
                key=f"wc:parent-empty:{pid}",
                wc_id=pid,
                label=label,
                synced=False,
                side="wc",
                match_key=psku.casefold() if psku else "",
                erp_key=psku or None,
                extra={
                    "parent_id": pid,
                    "parent_sku": psku,
                    "parent_name": pname,
                    "placeholder_empty": True,
                    "parent_mapped": parent_mapped,
                },
            )
        )
        seen.add(pid)

    for parent in parents:
        if not isinstance(parent, dict):
            continue
        pid = int(parent.get("id") or 0)
        if not pid or pid in covered_ids or pid in seen:
            continue
        psku = str(parent.get("sku") or "").strip()
        if not psku:
            continue
        pname = str(parent.get("name") or "").strip()
        parent_mapped = int(product_map.get(psku) or 0) == pid
        label = _placeholder_parent_label(pname, psku, pid, parent_mapped=parent_mapped)
        rows.append(
            ReconRow(
                key=f"wc:parent-empty:{pid}",
                wc_id=pid,
                label=label,
                synced=False,
                side="wc",
                match_key=psku.casefold(),
                erp_key=psku,
                extra={
                    "parent_id": pid,
                    "parent_sku": psku,
                    "parent_name": pname,
                    "placeholder_empty": True,
                    "parent_mapped": parent_mapped,
                },
            )
        )
        seen.add(pid)


def _fetch_ps_variations(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.ps_sync_helper import ps_get_product
    from sync_app.core.ps_variation_helper import (
        ps_list_all_combinations_grouped,
        ps_list_attribute_groups,
        ps_list_attribute_values,
        ps_list_combinations,
    )

    _check_recon_cancel(cancel_check)
    timeout = _recon_http_timeout(config)
    grouped = ps_list_all_combinations_grouped(config, timeout=timeout)
    _check_recon_cancel(cancel_check)

    # نگاشت سراسری value_id → نام مقدار (یک‌بار، نه به‌ازای هر ترکیب) — فقط
    # برای برچسبِ نمایشی؛ تطبیق واقعی فقط با SKU انجام می‌شه.
    value_names: dict[int, str] = {}
    try:
        for group in ps_list_attribute_groups(config, timeout=timeout):
            _check_recon_cancel(cancel_check)
            for value in ps_list_attribute_values(config, group["id"], timeout=timeout):
                value_names[int(value["id"])] = str(value.get("name") or "").strip()
    except ReconciliationCancelled:
        raise
    except Exception as exc:
        log.warning(
            f"⚠️ [تطبیق واریانت‌ها] خواندن نام ویژگی‌ها ناموفق بود ({exc}) — "
            "برچسب‌ها ممکنه ناقص باشن، ولی SKU (ملاک واقعی تطبیق) اثر نمی‌گیره."
        )

    product_map = load_product_woo_map()
    mapped_parent_ids = {int(v) for v in product_map.values() if v}

    parents_meta: dict[int, dict] = {}
    rows: list[ReconRow] = []

    def _parent(pid: int) -> dict | None:
        if pid in parents_meta:
            return parents_meta[pid]
        try:
            p = ps_get_product(config, pid, timeout=timeout)
        except Exception as exc:
            log.warning(f"⚠️ [تطبیق واریانت‌ها] دریافت محصول والد #{pid} ناموفق بود: {exc}")
            p = None
        parents_meta[pid] = p or {}
        return p

    combo_fetch_failures = 0
    for parent_id in grouped:
        _check_recon_cancel(cancel_check)
        parent = _parent(parent_id)
        if not parent:
            continue
        parent_sku = str(parent.get("sku") or "").strip()
        parent_name = str(parent.get("name") or "").strip()
        parent_mapped = parent_id in mapped_parent_ids
        try:
            combos = ps_list_combinations(config, parent_id, timeout=timeout)
        except Exception as exc:
            combo_fetch_failures += 1
            log.warning(
                f"⚠️ [تطبیق واریانت‌ها] دریافت combinationهای محصول #{parent_id} "
                f"({parent_sku or parent_name}) ناموفق بود: {exc}"
            )
            combos = []
        for combo in combos:
            vid = int(combo.get("id") or 0)
            if not vid:
                continue
            sku = str(combo.get("reference") or "").strip()
            option_ids = combo.get("option_value_ids") or []
            attr_text = " / ".join(
                value_names[int(oid)] for oid in option_ids if int(oid) in value_names
            )
            label = f"{parent_name} › {attr_text or '—'}"
            if sku:
                label += f" — کد {sku}"
            label += f" — #{vid} (والد #{parent_id})"
            rows.append(
                ReconRow(
                    key=f"wc:{parent_id}:{vid}",
                    wc_id=vid,
                    label=label,
                    synced=False,
                    side="wc",
                    match_key=sku.lower() if sku else "",
                    erp_key=sku or None,
                    extra={
                        "parent_id": parent_id,
                        "parent_sku": parent_sku,
                        "parent_name": parent_name,
                        "variation_sku": sku,
                        "attributes": attr_text,
                        "parent_mapped": parent_mapped,
                    },
                )
            )

    # والدهای متغیرِ لینک‌شده که هنوز هیچ combination ندارن (تازه لینک شدن، یا
    # هنوز از تب «متغیرها» sync نشدن) — برای پیشنهاد تطبیق دستی والد.
    for wc_id in mapped_parent_ids:
        if wc_id not in parents_meta:
            _parent(wc_id)

    parents_list = [
        {"id": pid, "sku": p.get("sku"), "name": p.get("name")}
        for pid, p in parents_meta.items()
        if p
    ]
    _append_empty_parent_variation_rows(parents_list, rows, product_map)
    rows.sort(key=lambda r: (bool(r.synced), str(r.label or "")))
    if grouped and combo_fetch_failures == len(grouped):
        log.error(
            f"❌ [تطبیق واریانت‌ها] دریافت combination برای هر {len(grouped)} محصول متغیر "
            "ناموفق بود — لیست واریانت‌ها احتمالاً خالی/ناقصه. جزئیات خطا در لاگ‌های بالا."
        )
    return rows


def _fetch_wc_variations(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        return _fetch_ps_variations(config, cancel_check=cancel_check)

    parents = _wc_get_paginated(
        config,
        "products",
        params={
            "type": "variable",
            "status": "any",
            "_fields": "id,sku,name",
        },
        cancel_check=cancel_check,
    )
    rows: list[ReconRow] = []
    workers = min(_WC_VARIATION_FETCH_WORKERS, max(1, len(parents)))
    if workers <= 1:
        for parent in parents:
            _check_recon_cancel(cancel_check)
            rows.extend(_fetch_parent_variations(config, parent, cancel_check=cancel_check))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_fetch_parent_variations, config, parent, cancel_check=cancel_check)
                for parent in parents
                if isinstance(parent, dict)
            ]
            for future in as_completed(futures):
                _check_recon_cancel(cancel_check)
                rows.extend(future.result() or [])
    product_map = load_product_woo_map()
    _append_empty_parent_variation_rows(parents, rows, product_map)
    rows.sort(key=lambda r: (bool(r.synced), str(r.label or "")))
    return rows


def _fetch_erp_attributes(config: dict) -> list[ReconRow]:
    conn, _, _ = open_sql_connection(config, timeout=8)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT P.ID, P.Name, C.Name
        FROM PoshakProperties AS P
        LEFT JOIN PoshakProperties AS C ON C.ParentID = P.ID
        WHERE P.ParentID = 0
        ORDER BY P.ID, C.ID
        """
    )
    grouped: dict[str, set[str]] = {}
    for row in cursor.fetchall():
        attr_name = _normalize_name(row[1])
        term = _normalize_name(row[2]) if row[2] is not None else ""
        if not attr_name:
            continue
        grouped.setdefault(attr_name, set())
        if term and term != attr_name:
            grouped[attr_name].add(term)

    rows: list[ReconRow] = []
    for attr_name, terms in grouped.items():
        term_preview = "، ".join(sorted(terms)[:5])
        if len(terms) > 5:
            term_preview += " ..."
        label = f"{attr_name}"
        if term_preview:
            label += f" — ({term_preview})"
        rows.append(
            ReconRow(
                key=f"erp:{attr_name}",
                erp_key=attr_name,
                label=label,
                synced=False,
                side="erp",
                match_key=_normalize_name(attr_name).lower(),
                extra={"terms": sorted(terms)},
            )
        )
    conn.close()
    return rows


def _fetch_ps_attributes(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.ps_variation_helper import ps_list_attribute_groups

    _check_recon_cancel(cancel_check)
    groups = ps_list_attribute_groups(config, timeout=_recon_http_timeout(config))
    rows: list[ReconRow] = []
    for item in groups:
        if not isinstance(item, dict):
            continue
        wc_id = int(item.get("id") or 0)
        name = _normalize_name(item.get("name"))
        if not wc_id or not name:
            continue
        rows.append(
            ReconRow(
                key=f"wc:{wc_id}",
                wc_id=wc_id,
                label=f"{name} — #{wc_id}",
                synced=False,
                side="wc",
                match_key=name.lower(),
                erp_key=name,
                extra={"slug": name},
            )
        )
    return rows


def _fetch_wc_attributes(
    config: dict,
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ReconRow]:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        return _fetch_ps_attributes(config, cancel_check=cancel_check)

    attrs = _wc_get_paginated(
        config,
        "products/attributes",
        params={"per_page": 100, "_fields": "id,name,slug"},
        cancel_check=cancel_check,
    )
    erp_names: set[str] = set()
    rows: list[ReconRow] = []

    for item in attrs:
        if not isinstance(item, dict):
            continue
        wc_id = int(item.get("id") or 0)
        name = _normalize_name(item.get("name"))
        slug = str(item.get("slug") or "").strip()
        if not wc_id or not name:
            continue
        synced = False
        rows.append(
            ReconRow(
                key=f"wc:{wc_id}",
                wc_id=wc_id,
                label=f"{name} — #{wc_id} — slug {slug}",
                synced=synced,
                side="wc",
                match_key=name.lower(),
                erp_key=name,
                extra={"slug": slug},
            )
        )
    return rows


def _mark_attribute_sync_by_name(erp_rows: list[ReconRow], wc_rows: list[ReconRow]) -> None:
    wc_by_name: dict[str, ReconRow] = {}
    for wc in wc_rows:
        name = _normalize_name(wc.erp_key or wc.label.split("—")[0])
        if name:
            wc_by_name[name.lower()] = wc
    for erp in erp_rows:
        key = _normalize_name(erp.erp_key or "").lower()
        match = wc_by_name.get(key)
        if match:
            erp.synced = True
            match.synced = True


def _compute_stats(erp_rows: list[ReconRow], wc_rows: list[ReconRow]) -> dict[str, int]:
    erp_synced = sum(1 for r in erp_rows if r.synced)
    wc_synced = sum(1 for r in wc_rows if r.synced)
    return {
        "erp_total": len(erp_rows),
        "wc_total": len(wc_rows),
        "erp_synced": erp_synced,
        "erp_unsynced": len(erp_rows) - erp_synced,
        "wc_synced": wc_synced,
        "wc_unsynced": len(wc_rows) - wc_synced,
    }


def _same_variation_parent(left: ReconRow, right: ReconRow) -> bool:
    left_parent = str((left.extra or {}).get("parent_sku") or "").strip()
    right_parent = str((right.extra or {}).get("parent_sku") or "").strip()
    if left_parent and right_parent and left_parent == right_parent:
        return True
    left_pid = int((left.extra or {}).get("parent_id") or 0)
    right_pid = int((right.extra or {}).get("parent_id") or 0)
    product_map = load_product_woo_map()
    if left_parent and right_pid:
        if int(product_map.get(left_parent) or 0) == right_pid:
            return True
    if right_parent and left_pid:
        if int(product_map.get(right_parent) or 0) == left_pid:
            return True
    return False


def _erp_variation_traits(row: ReconRow) -> set[str]:
    extra = row.extra or {}
    traits: set[str] = set()
    for raw in (
        str(extra.get("size") or ""),
        str(extra.get("color") or ""),
        str(extra.get("dim3") or ""),
    ):
        text = _normalize_name(raw.strip().strip("/"))
        if text:
            traits.add(text.casefold())
    return traits


def _wc_variation_traits(row: ReconRow) -> set[str]:
    attrs = str((row.extra or {}).get("attributes") or "").strip()
    if not attrs or attrs == "—":
        return set()
    parts = [part.strip() for part in attrs.replace("،", ",").split(",") if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in attrs.split(" / ") if part.strip()]
    traits: set[str] = set()
    for raw in parts:
        text = _normalize_name(raw)
        if text:
            traits.add(text.casefold())
    return traits


def _variation_traits_match(erp: ReconRow, wc: ReconRow) -> bool:
    erp_traits = _erp_variation_traits(erp)
    wc_traits = _wc_variation_traits(wc)
    if not erp_traits or not wc_traits:
        return False
    return bool(erp_traits & wc_traits)


def _category_row_key(row: ReconRow) -> str:
    if row.side == "erp":
        return str(row.erp_key or "").strip()
    return str(row.erp_key or row.extra.get("code") or extract_code_from_wc_slug(
        str(row.match_key or row.extra.get("slug") or "")
    ) or "").strip()


def _category_slug_key(row: ReconRow) -> str:
    return str(row.match_key or row.extra.get("slug") or "").strip().casefold()


def find_category_counterpart(
    anchor: ReconRow,
    candidates: list[ReconRow],
) -> ReconRow | None:
    """دسته متناظر را از نگاشت ذخیره‌شده یا نامک/کد پیدا می‌کند."""
    if not anchor or not candidates:
        return None

    category_map = load_category_map()

    if anchor.side == "erp":
        code = _category_row_key(anchor)
        wc_id = int(category_map.get(code) or 0) if code else 0
        if wc_id:
            for candidate in candidates:
                if int(candidate.wc_id or 0) == wc_id:
                    return candidate
        slug = _category_slug_key(anchor)
        if slug:
            slug_hits = [
                candidate
                for candidate in candidates
                if _category_slug_key(candidate) == slug
            ]
            if len(slug_hits) == 1:
                return slug_hits[0]
        return None

    wc_id = int(anchor.wc_id or 0)
    if wc_id:
        for code, mapped_id in category_map.items():
            if int(mapped_id) != wc_id:
                continue
            for candidate in candidates:
                if _category_row_key(candidate) == str(code).strip():
                    return candidate

    code = _category_row_key(anchor)
    if code:
        code_hits = [
            candidate for candidate in candidates if _category_row_key(candidate) == code
        ]
        if len(code_hits) == 1:
            return code_hits[0]

    slug = _category_slug_key(anchor)
    if slug:
        slug_hits = [
            candidate for candidate in candidates if _category_slug_key(candidate) == slug
        ]
        if len(slug_hits) == 1:
            return slug_hits[0]
    return None


def _attribute_name_key(row: ReconRow) -> str:
    return _normalize_name(row.erp_key or row_display_name(row, ENTITY_ATTRIBUTES)).casefold()


def find_attribute_counterpart(
    anchor: ReconRow,
    candidates: list[ReconRow],
) -> ReconRow | None:
    """ویژگی متناظر را با نام یکسان یا مشابه پیدا می‌کند."""
    if not anchor or not candidates:
        return None

    key = _attribute_name_key(anchor)
    if not key:
        return None

    exact_hits = [row for row in candidates if _attribute_name_key(row) == key]
    if len(exact_hits) == 1:
        return exact_hits[0]

    similar_hits = [
        row
        for row in candidates
        if _names_match_well(
            row_display_name(anchor, ENTITY_ATTRIBUTES),
            row_display_name(row, ENTITY_ATTRIBUTES),
        )
    ]
    if len(similar_hits) == 1:
        return similar_hits[0]
    return None


def find_product_counterpart(
    anchor: ReconRow,
    candidates: list[ReconRow],
) -> ReconRow | None:
    """محصول متناظر را با SKU یا نگاشت ذخیره‌شده پیدا می‌کند."""
    if not anchor or not candidates:
        return None

    sku = str(anchor.match_key or anchor.erp_key or "").strip().casefold()
    if sku:
        sku_hits = [
            row
            for row in candidates
            if str(row.match_key or row.erp_key or "").strip().casefold() == sku
        ]
        if len(sku_hits) == 1:
            return sku_hits[0]

    product_map = load_product_woo_map()
    if anchor.side == "erp":
        lookup_key = str(anchor.erp_key or "").strip()
        mapped_id = int(product_map.get(lookup_key) or 0)
        if mapped_id:
            for candidate in candidates:
                if int(candidate.wc_id or 0) == mapped_id:
                    return candidate
    else:
        wc_id = int(anchor.wc_id or 0)
        if wc_id:
            for lookup_key, mapped_id in product_map.items():
                if int(mapped_id) != wc_id:
                    continue
                for candidate in candidates:
                    if str(candidate.erp_key or "").strip() == str(lookup_key).strip():
                        return candidate
    return None


def find_entity_counterpart(
    entity: str,
    anchor: ReconRow,
    candidates: list[ReconRow],
) -> ReconRow | None:
    if entity == ENTITY_VARIATIONS:
        return find_variation_counterpart(anchor, candidates)
    if entity == ENTITY_CATEGORIES:
        return find_category_counterpart(anchor, candidates)
    if entity == ENTITY_ATTRIBUTES:
        return find_attribute_counterpart(anchor, candidates)
    if entity == ENTITY_PRODUCTS:
        return find_product_counterpart(anchor, candidates)
    return None


def _mark_category_sync_by_map(erp_rows: list[ReconRow], wc_rows: list[ReconRow]) -> None:
    """تیک سبز فقط وقتی کد ERP به دسته واقعی موجود در ووکامرس وصل شده باشد."""
    category_map = load_category_map()
    for row in erp_rows:
        row.synced = False
    for row in wc_rows:
        row.synced = False

    wc_by_id = {int(row.wc_id): row for row in wc_rows if row.wc_id}
    for erp in erp_rows:
        code = str(erp.erp_key or "").strip()
        wc_id = int(category_map.get(code) or 0)
        if not code or not wc_id:
            continue
        wc = wc_by_id.get(wc_id)
        if not wc:
            continue
        erp.synced = True
        wc.synced = True


def find_variation_counterpart(
    anchor: ReconRow,
    candidates: list[ReconRow],
) -> ReconRow | None:
    """متغیر متناظر را با SKU، ویژگی (سایز/رنگ) یا نام نمایشی پیدا می‌کند."""
    if not anchor or not candidates:
        return None

    from sync_app.core.variation_query import variation_skus_match

    sku = str(anchor.match_key or (anchor.extra or {}).get("variation_sku") or "").strip()
    if sku:
        for candidate in candidates:
            other_sku = str(
                candidate.match_key or (candidate.extra or {}).get("variation_sku") or ""
            ).strip()
            if variation_skus_match(sku, other_sku) and _same_variation_parent(anchor, candidate):
                return candidate

    same_parent = [row for row in candidates if _same_variation_parent(anchor, row)]
    if len(same_parent) == 1 and (same_parent[0].extra or {}).get("placeholder_empty"):
        return same_parent[0]
    trait_hits = [row for row in same_parent if _variation_traits_match(anchor, row)]
    if len(trait_hits) == 1:
        return trait_hits[0]

    anchor_name = row_display_name(anchor, ENTITY_VARIATIONS)
    name_hits = [
        row
        for row in same_parent
        if _names_match_well(anchor_name, row_display_name(row, ENTITY_VARIATIONS))
    ]
    if len(name_hits) == 1:
        return name_hits[0]

    return None


def _mark_variation_sync_by_sku(erp_rows: list[ReconRow], wc_rows: list[ReconRow]) -> None:
    """تیک سبز: SKU واریانت واقعی، یا نگاشت والد ثبت‌شده برای محصول بدون واریانت."""
    from sync_app.core.variation_query import variation_sku_aliases

    for row in erp_rows:
        row.synced = False
    for row in wc_rows:
        row.synced = False

    erp_by_alias: dict[str, ReconRow] = {}
    for erp in erp_rows:
        sku = str(erp.match_key or (erp.extra or {}).get("variation_sku") or "").strip()
        for alias in variation_sku_aliases(sku):
            erp_by_alias.setdefault(alias, erp)

    parents_with_real_variants: set[int] = set()
    for wc in wc_rows:
        if (wc.extra or {}).get("placeholder_empty"):
            continue
        parent_id = int((wc.extra or {}).get("parent_id") or 0)
        if parent_id:
            parents_with_real_variants.add(parent_id)

    for wc in wc_rows:
        if (wc.extra or {}).get("placeholder_empty"):
            continue
        sku = str(wc.match_key or (wc.extra or {}).get("variation_sku") or "").strip()
        if not sku:
            continue
        erp = None
        for alias in variation_sku_aliases(sku):
            erp = erp_by_alias.get(alias)
            if erp:
                break
        if not erp:
            continue
        if not _same_variation_parent(erp, wc):
            continue
        erp.synced = True
        wc.synced = True

    product_map = load_product_woo_map()
    erp_by_parent: dict[str, list[ReconRow]] = {}
    for erp in erp_rows:
        if erp.synced:
            continue
        parent_sku = str((erp.extra or {}).get("parent_sku") or "").strip()
        if parent_sku:
            erp_by_parent.setdefault(parent_sku, []).append(erp)

    for wc in wc_rows:
        if not (wc.extra or {}).get("placeholder_empty"):
            continue
        parent_sku = str((wc.extra or {}).get("parent_sku") or "").strip()
        parent_id = int((wc.extra or {}).get("parent_id") or 0)
        if not parent_sku or not parent_id:
            continue
        if int(product_map.get(parent_sku) or 0) != parent_id:
            continue
        if parent_id in parents_with_real_variants:
            continue
        wc.synced = True
        for erp in erp_by_parent.get(parent_sku, []):
            erp.synced = True
            extra = erp.extra or {}
            extra["parent_mapped_only"] = True
            erp.extra = extra


def load_comparison(
    config: dict,
    entity: str,
    *,
    cancel_check: Callable[[], bool] | None = None,
    use_cache: bool = True,
) -> ComparisonResult:
    entity = str(entity or ENTITY_PRODUCTS).strip()
    _check_recon_cancel(cancel_check)
    cache_key = _comparison_cache_key(config, entity)
    if use_cache:
        cached = _COMPARISON_CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < _COMPARISON_CACHE_TTL_SEC:
            return cached[1]
    if entity == ENTITY_CATEGORIES:
        erp_rows = _fetch_erp_categories(config)
        _check_recon_cancel(cancel_check)
        wc_rows = _fetch_wc_categories(config, cancel_check=cancel_check)
        _mark_category_sync_by_map(erp_rows, wc_rows)
    elif entity == ENTITY_PRODUCTS:
        erp_rows = _fetch_erp_products(config)
        _check_recon_cancel(cancel_check)
        wc_rows = _fetch_wc_products(config, cancel_check=cancel_check)
        _mark_product_sync_by_map(erp_rows, wc_rows)
    elif entity == ENTITY_VARIATIONS:
        erp_rows = _fetch_erp_variations(config)
        _check_recon_cancel(cancel_check)
        wc_rows = _fetch_wc_variations(config, cancel_check=cancel_check)
        _mark_variation_sync_by_sku(erp_rows, wc_rows)
    elif entity == ENTITY_ATTRIBUTES:
        erp_rows = _fetch_erp_attributes(config)
        _check_recon_cancel(cancel_check)
        wc_rows = _fetch_wc_attributes(config, cancel_check=cancel_check)
        _mark_attribute_sync_by_name(erp_rows, wc_rows)
    else:
        raise ValueError(f"نوع نامعتبر: {entity}")

    result = ComparisonResult(
        entity=entity,
        erp_rows=erp_rows,
        wc_rows=wc_rows,
        stats=_compute_stats(erp_rows, wc_rows),
    )
    if use_cache:
        _COMPARISON_CACHE[cache_key] = (time.monotonic(), result)
    return result


def _pair_by_match_key(
    erp_rows: list[ReconRow],
    wc_rows: list[ReconRow],
    *,
    only_unsynced: bool = True,
    entity: str = "",
) -> list[tuple[ReconRow, ReconRow]]:
    from sync_app.core.variation_query import variation_sku_aliases

    wc_index: dict[str, list[ReconRow]] = {}
    for wc in wc_rows:
        mk = str(wc.match_key or "").strip()
        if not mk:
            continue
        if only_unsynced and wc.synced:
            continue
        keys = {mk.casefold()}
        if entity == ENTITY_VARIATIONS:
            keys = variation_sku_aliases(mk)
        for key in keys:
            wc_index.setdefault(key, []).append(wc)

    pairs: list[tuple[ReconRow, ReconRow]] = []
    used_wc: set[str] = set()
    for erp in erp_rows:
        if only_unsynced and erp.synced:
            continue
        mk = str(erp.match_key or "").strip()
        if not mk:
            continue
        lookup_keys = variation_sku_aliases(mk) if entity == ENTITY_VARIATIONS else {mk.casefold()}
        candidates: list[ReconRow] = []
        for key in lookup_keys:
            for wc in wc_index.get(key) or []:
                if wc.key in used_wc:
                    continue
                if entity == ENTITY_VARIATIONS and not _same_variation_parent(erp, wc):
                    continue
                candidates.append(wc)
        if len(candidates) == 1:
            pairs.append((erp, candidates[0]))
            used_wc.add(candidates[0].key)
    return pairs


def suggest_auto_pairs(
    entity: str,
    erp_rows: list[ReconRow],
    wc_rows: list[ReconRow],
    *,
    exclude_erp_keys: set[str] | None = None,
    exclude_wc_keys: set[str] | None = None,
) -> list[SuggestedPair]:
    """پیشنهاد جفت خودکار بر اساس SKU/نامک، نام یکسان، و نام مشابه (۱↔۱)."""
    exclude_erp = set(exclude_erp_keys or ())
    exclude_wc = set(exclude_wc_keys or ())

    erp_pool = [
        row
        for row in erp_rows
        if not row.synced and row.key not in exclude_erp
    ]
    wc_pool = [
        row
        for row in wc_rows
        if not row.synced and row.key not in exclude_wc
    ]

    suggestions: list[SuggestedPair] = []
    used_erp: set[str] = set()
    used_wc: set[str] = set()

    for erp, wc in _pair_by_match_key(
        erp_pool,
        wc_pool,
        only_unsynced=False,
        entity=entity,
    ):
        if erp.key in used_erp or wc.key in used_wc:
            continue
        suggestions.append(SuggestedPair(erp, wc, SUGGEST_REASON_MATCH_KEY))
        used_erp.add(erp.key)
        used_wc.add(wc.key)

    if entity == ENTITY_VARIATIONS:
        wc_parents = {
            str((wc.extra or {}).get("parent_sku") or "").strip(): wc
            for wc in wc_pool
            if wc.key not in used_wc and (wc.extra or {}).get("placeholder_empty")
        }
        seen_parents: set[str] = set()
        for erp in erp_pool:
            if erp.key in used_erp:
                continue
            parent_sku = str((erp.extra or {}).get("parent_sku") or "").strip()
            if not parent_sku or parent_sku in seen_parents:
                continue
            wc = wc_parents.get(parent_sku)
            if not wc or wc.key in used_wc:
                continue
            suggestions.append(SuggestedPair(erp, wc, SUGGEST_REASON_PARENT_PLACEHOLDER))
            used_erp.add(erp.key)
            used_wc.add(wc.key)
            seen_parents.add(parent_sku)

    wc_by_name: dict[str, list[ReconRow]] = {}
    for wc in wc_pool:
        if wc.key in used_wc:
            continue
        name = _normalize_name(row_display_name(wc, entity)).casefold()
        if name:
            wc_by_name.setdefault(name, []).append(wc)

    for erp in erp_pool:
        if erp.key in used_erp:
            continue
        name = _normalize_name(row_display_name(erp, entity)).casefold()
        if not name:
            continue
        candidates = [wc for wc in wc_by_name.get(name, []) if wc.key not in used_wc]
        if len(candidates) != 1:
            continue
        wc = candidates[0]
        suggestions.append(SuggestedPair(erp, wc, SUGGEST_REASON_NAME_EXACT))
        used_erp.add(erp.key)
        used_wc.add(wc.key)

    for erp in erp_pool:
        if erp.key in used_erp:
            continue
        erp_name = row_display_name(erp, entity)
        matches = [
            wc
            for wc in wc_pool
            if wc.key not in used_wc
            and _names_match_well(erp_name, row_display_name(wc, entity))
        ]
        if len(matches) != 1:
            continue
        wc = matches[0]
        suggestions.append(SuggestedPair(erp, wc, SUGGEST_REASON_NAME_SIMILAR))
        used_erp.add(erp.key)
        used_wc.add(wc.key)

    return suggestions


def _save_category_links(pairs: list[tuple[ReconRow, ReconRow]]) -> int:
    category_map = load_category_map()
    saved = 0
    for erp, wc in pairs:
        code = str(erp.erp_key or "").strip()
        wc_id = int(wc.wc_id or 0)
        if not code or not wc_id:
            continue
        category_map[code] = wc_id
        saved += 1
    if saved:
        save_category_map(category_map)
    return saved


def _save_product_links(
    pairs: list[tuple[ReconRow, ReconRow]],
    *,
    wc_rows: list[ReconRow] | None = None,
) -> int:
    product_map = load_product_woo_map()
    saved = 0
    for erp, wc in pairs:
        sku = str(erp.erp_key or "").strip()
        wc_id = int(wc.wc_id or 0)
        if not sku or not wc_id:
            continue
        product_map[sku] = wc_id
        wc_sku = str(wc.match_key or wc.erp_key or "").strip()
        manual = (not wc_sku) or (wc_sku.casefold() != sku.casefold())
        conflict_id = None
        if wc_rows:
            hit = find_wc_sku_collision(sku, wc_id, wc_rows)
            if hit:
                conflict_id = int(hit.wc_id or 0)
        register_product_link(
            sku,
            wc_id,
            wc_label=row_display_name(wc, ENTITY_PRODUCTS) or wc.label,
            manual=manual,
            sku_conflict_wc_id=conflict_id,
        )
        saved += 1
    if saved:
        save_product_woo_map(product_map)
    return saved


def _save_variation_links(pairs: list[tuple[ReconRow, ReconRow]]) -> int:
    """برای واریانت، نگاشت والد محصول را ثبت می‌کند."""
    product_map = load_product_woo_map()
    saved = 0
    for erp, wc in pairs:
        parent_sku = str(erp.extra.get("parent_sku") or "").strip()
        parent_id = int(wc.extra.get("parent_id") or 0)
        if parent_sku and parent_id:
            product_map[parent_sku] = parent_id
            saved += 1
        elif erp.erp_key and wc.extra.get("parent_sku"):
            ps = str(wc.extra.get("parent_sku") or "").strip()
            if ps and parent_id:
                product_map[ps] = parent_id
                saved += 1
    if saved:
        save_product_woo_map(product_map)
    return saved


def resolve_manual_pairs(
    entity: str,
    erp_rows: list[ReconRow],
    wc_rows: list[ReconRow],
    config: dict | None = None,
) -> tuple[list[tuple[ReconRow, ReconRow]], str]:
    if entity == ENTITY_ATTRIBUTES:
        return [], "ویژگی با نام یکسان خودکار تطبیق می‌شود — همگام‌سازی: تب «ویژگی‌ها»."

    if not erp_rows or not wc_rows:
        from sync_app.core.integrations.erp_provider import erp_provider_label

        return [], f"حداقل یک مورد از {erp_provider_label(config)} و یک مورد از ووکامرس را تیک بزنید."

    if len(erp_rows) == 1 and len(wc_rows) == 1:
        pairs = [(erp_rows[0], wc_rows[0])]
    elif len(erp_rows) == len(wc_rows):
        pairs = list(zip(erp_rows, wc_rows))
    else:
        pairs = _pair_by_match_key(erp_rows, wc_rows, only_unsynced=False, entity=entity)
        if not pairs:
            return [], "تعداد یا کد محصول بین موارد انتخابی یکسان نیست."
    return pairs, ""


def save_link_pairs(
    entity: str,
    pairs: list[tuple[ReconRow, ReconRow]],
    *,
    wc_rows: list[ReconRow] | None = None,
) -> int:
    if entity == ENTITY_CATEGORIES:
        count = _save_category_links(pairs)
    elif entity == ENTITY_PRODUCTS:
        count = _save_product_links(pairs, wc_rows=wc_rows)
    elif entity == ENTITY_VARIATIONS:
        count = _save_variation_links(pairs)
    else:
        return 0
    if count:
        invalidate_comparison_cache(entity)
    return count


def find_saved_link_pair(
    entity: str,
    erp_rows: list[ReconRow],
    wc_rows: list[ReconRow],
    *,
    erp_row: ReconRow | None = None,
    wc_row: ReconRow | None = None,
) -> tuple[ReconRow, ReconRow] | None:
    """جفت ثبت‌شده در فایل نگاشت را از یک یا دو طرف انتخاب‌شده پیدا می‌کند."""
    if entity == ENTITY_ATTRIBUTES:
        if erp_row and wc_row and erp_row.synced and wc_row.synced:
            if find_attribute_counterpart(erp_row, [wc_row]) is wc_row:
                return erp_row, wc_row
        anchor = erp_row if erp_row and erp_row.synced else wc_row if wc_row and wc_row.synced else None
        if anchor is None:
            return None
        candidates = wc_rows if anchor.side == "erp" else erp_rows
        hit = find_attribute_counterpart(anchor, candidates)
        if not hit:
            return None
        return (anchor, hit) if anchor.side == "erp" else (hit, anchor)

    if erp_row and wc_row and erp_row.synced and wc_row.synced:
        matched = _resolve_saved_pair(entity, erp_row, wc_row, erp_rows, wc_rows)
        if matched:
            return matched

    anchor = None
    if erp_row and erp_row.synced:
        anchor = erp_row
    elif wc_row and wc_row.synced:
        anchor = wc_row
    if anchor is None:
        return None

    if anchor.side == "erp":
        partner = _find_wc_partner_for_erp(entity, anchor, wc_rows)
        return (anchor, partner) if partner else None

    partner = _find_erp_partner_for_wc(entity, anchor, erp_rows)
    return (partner, anchor) if partner else None


def _resolve_saved_pair(
    entity: str,
    erp: ReconRow,
    wc: ReconRow,
    erp_rows: list[ReconRow],
    wc_rows: list[ReconRow],
) -> tuple[ReconRow, ReconRow] | None:
    from_erp = _find_wc_partner_for_erp(entity, erp, wc_rows)
    if from_erp and from_erp.key == wc.key:
        return erp, wc
    from_wc = _find_erp_partner_for_wc(entity, wc, erp_rows)
    if from_wc and from_wc.key == erp.key:
        return erp, wc
    return None


def _find_wc_partner_for_erp(
    entity: str,
    erp: ReconRow,
    wc_rows: list[ReconRow],
) -> ReconRow | None:
    if entity == ENTITY_CATEGORIES:
        return find_category_counterpart(erp, wc_rows)

    if entity == ENTITY_VARIATIONS:
        return find_variation_counterpart(erp, wc_rows)

    if entity == ENTITY_PRODUCTS:
        return find_product_counterpart(erp, wc_rows)
    return None


def _find_erp_partner_for_wc(
    entity: str,
    wc: ReconRow,
    erp_rows: list[ReconRow],
) -> ReconRow | None:
    if entity == ENTITY_CATEGORIES:
        return find_category_counterpart(wc, erp_rows)

    if entity == ENTITY_VARIATIONS:
        return find_variation_counterpart(wc, erp_rows)

    if entity == ENTITY_ATTRIBUTES:
        return find_attribute_counterpart(wc, erp_rows)

    if entity == ENTITY_PRODUCTS:
        return find_product_counterpart(wc, erp_rows)
    return None


def remove_link_pair(entity: str, erp: ReconRow, wc: ReconRow) -> bool:
    """تطبیق ذخیره‌شده را از فایل نگاشت حذف می‌کند."""
    if entity == ENTITY_CATEGORIES:
        category_map = load_category_map()
        code = str(erp.erp_key or "").strip()
        wc_id = int(wc.wc_id or 0)
        removed = False
        if code and int(category_map.get(code) or 0) == wc_id:
            del category_map[code]
            removed = True
        if removed:
            save_category_map(category_map)
            log.info(f"↩ لغو تطبیق دسته: {code} ↔ Woo #{wc_id}")
        return removed

    if entity == ENTITY_PRODUCTS:
        product_map = load_product_woo_map()
        sku = str(erp.erp_key or erp.match_key or "").strip()
        wc_id = int(wc.wc_id or 0)
        if not sku:
            return False
        mapped_id = int(product_map.get(sku) or 0)
        if not mapped_id:
            return False
        if mapped_id != wc_id and find_product_counterpart(erp, [wc]) is not wc:
            return False
        del product_map[sku]
        save_product_woo_map(product_map)
        clear_product_link_meta(sku)
        if mapped_id != wc_id:
            log.warning(
                f"↩ لغو تطبیق محصول {sku}: نگاشت قدیمی #{mapped_id} "
                f"— انتخاب کاربر #{wc_id}"
            )
        else:
            log.info(f"↩ لغو تطبیق محصول: {sku} ↔ Woo #{wc_id}")
        return True

    if entity == ENTITY_VARIATIONS:
        product_map = load_product_woo_map()
        parent_sku = str(erp.extra.get("parent_sku") or "").strip()
        parent_id = int(wc.extra.get("parent_id") or 0)
        if parent_sku and int(product_map.get(parent_sku) or 0) == parent_id:
            del product_map[parent_sku]
            save_product_woo_map(product_map)
            log.info(f"↩ لغو تطبیق والد متغیر: {parent_sku} ↔ Woo #{parent_id}")
            return True
        return False

    return False


def link_manual_pairs(
    config: dict,
    entity: str,
    erp_rows: list[ReconRow],
    wc_rows: list[ReconRow],
) -> tuple[int, str]:
    pairs, error = resolve_manual_pairs(entity, erp_rows, wc_rows, config)
    if error:
        return 0, error
    if entity not in (ENTITY_CATEGORIES, ENTITY_PRODUCTS, ENTITY_VARIATIONS):
        return 0, "نوع نامعتبر."

    count = save_link_pairs(entity, pairs, wc_rows=wc_rows)
    if count:
        log.info(f"✅ نگاشت {ENTITY_LABELS.get(entity, entity)}: {count} مورد ثبت شد.")
        return count, f"{count} تطبیق با موفقیت ثبت شد."
    return 0, "هیچ تطبیقی ذخیره نشد — کلیدها را بررسی کنید."


def auto_link_all(config: dict, entity: str) -> tuple[int, str]:
    if entity == ENTITY_ATTRIBUTES:
        return 0, "ویژگی خودکار تطبیق می‌شود — همگام‌سازی: تب «ویژگی‌ها»."

    comparison = load_comparison(config, entity)
    pairs = _pair_by_match_key(
        comparison.erp_rows,
        comparison.wc_rows,
        only_unsynced=True,
        entity=entity,
    )
    if not pairs and entity == ENTITY_VARIATIONS:
        wc_parents = {
            str((wc.extra or {}).get("parent_sku") or "").strip(): wc
            for wc in comparison.wc_rows
            if not wc.synced and (wc.extra or {}).get("placeholder_empty")
        }
        seen_parents: set[str] = set()
        for erp in comparison.erp_rows:
            if erp.synced:
                continue
            parent_sku = str((erp.extra or {}).get("parent_sku") or "").strip()
            if not parent_sku or parent_sku in seen_parents:
                continue
            wc = wc_parents.get(parent_sku)
            if wc:
                pairs.append((erp, wc))
                seen_parents.add(parent_sku)
    if not pairs:
        return 0, "مورد جدیدی برای تطبیق خودکار یافت نشد."

    if entity == ENTITY_CATEGORIES:
        count = _save_category_links(pairs)
    elif entity == ENTITY_PRODUCTS:
        count = _save_product_links(pairs, wc_rows=comparison.wc_rows)
    elif entity == ENTITY_VARIATIONS:
        count = _save_variation_links(pairs)
    else:
        return 0, "نوع نامعتبر."

    if count:
        invalidate_comparison_cache(entity)
        log.info(f"🔗 تطبیق خودکار {ENTITY_LABELS.get(entity, entity)}: {count} مورد")
        return count, f"{count} مورد با کد یکسان به‌صورت خودکار تطبیق شد."
    return 0, "تطبیق خودکار انجام نشد."
