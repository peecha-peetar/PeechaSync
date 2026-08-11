import os
import pyodbc
import json

# لود تنظیمات
try:
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log, app_path
    from sync_app.core.currency_helper import erp_price_divisor
    from sync_app.core.article_price import (
        resolve_article_price, resolve_sale_article_price, woo_sale_price_str, apply_price_markup,
    )
    from sync_app.core.sql_connection_helper import open_sql_connection
    from sync_app.core.category_resolver import load_category_map, live_category_ids
    from sync_app.core.category_rules import (
        explain_category_miss,
        prepare_category_context,
        primary_category_id,
        resolve_product_categories,
        resolve_live_product_categories,
        verify_product_categories,
        verify_categories_by_code,
        format_category_verify_miss,
        sku_to_category_codes,
    )
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        wc_call,
        format_wc_network_error,
        wc_parse_json,
    )
    from sync_app.core.integrations.commerce_provider import (
        build_store_api,
        is_prestashop,
        store_platform_label,
        warm_store_connection,
    )
    from sync_app.core.product_woo_map_helper import (
        load_product_woo_map,
        save_product_woo_map,
        resolve_existing_product_id,
        verify_product_saved,
        resolve_wc_product_id,
        clear_trashed_sku_blockers,
        fetch_product_by_id,
    )
    from sync_app.core.product_woo_map_meta import is_manual_product_link
    from sync_app.core.field_sync_config import is_field_enabled
except ImportError:
    class MockLog:
        def info(self, msg): print(f"INFO: {msg}")

        def error(self, msg): print(f"ERROR: {msg}")


    log = MockLog()


    def load_secure_config(_):
        return {}


    def app_path(name):
        return name


    def is_field_enabled(_config, _key):
        return True


def _resolve_article_price(row, price_col):
    return resolve_article_price(row, price_col, price_start_index=2)


def _has_variations(conn, a_code, variable_codes=None):
    if variable_codes is not None:
        return str(a_code).strip() in variable_codes
    from sync_app.core.variation_rules import product_is_variable

    cursor = conn.cursor()
    result = product_is_variable(cursor, a_code)
    cursor.close()
    return result


def _upsert_response_categories_ok(data, categories, sku, slug_map):
    """دسته‌ها با همان PUT/POST اول نشسته‌اند — PUT دوباره لازم نیست."""
    if not categories or not isinstance(data, dict):
        return False
    if verify_product_categories(data, categories):
        return True
    leaf_code = (sku_to_category_codes(sku) or [""])[0]
    if leaf_code and slug_map and verify_categories_by_code(data, leaf_code, slug_map):
        return True
    return False


def _category_id_for_sku(sku, cat_map, slug_map=None):
    """اولین id دسته (برای log) — ترجیح زیرگروه."""
    return primary_category_id(resolve_product_categories(sku, cat_map, slug_map or {}))


def _categories_for_sku(sku, cat_map, slug_map=None, config=None):
    from sync_app.core.product_category_override import get_manual_category_ids

    manual_ids = get_manual_category_ids(sku)
    if manual_ids:
        return [{"id": cid} for cid in manual_ids]
    if bool((config or {}).get("DISABLE_ERP_CATEGORY_SYNC", False)):
        # سینکِ خودکارِ دسته‌بندیِ ERP خاموشه — فقط الصاقِ دستی (تبِ «دسته‌بندی
        # و برند») معتبره؛ بدونِ اون، محصول بدونِ دسته‌بندی ارسال می‌شه.
        return []
    subgroups_only = bool((config or {}).get("CATEGORY_SYNC_SUBGROUPS_ONLY", False))
    return resolve_product_categories(sku, cat_map, slug_map or {}, include_parent=not subgroups_only)


def _load_product_woo_map():
    return load_product_woo_map()


def _save_product_woo_map(product_map):
    save_product_woo_map(product_map)


def _resolve_wc_product_id(wcapi, sku, product_map):
    return resolve_wc_product_id(wcapi, sku, product_map)


def _apply_field_sync_config(payload, config, *, is_create):
    """
    payload را طبق چک‌باکس‌های «فیلدهای همگام‌سازی» (تنظیمات) فیلتر می‌کند.
    فیلد غیرفعال یعنی: در payload ارسال نشود تا مقدار فعلی روی سایت دست‌نخورده بماند.
    نام محصول موقع ساخت محصول جدید همیشه لازم است (Woo بدون نام محصول نمی‌سازد)
    پس اگر «نام» غیرفعال باشد و محصول جدید باشد، SKU جایگزین نام می‌شود.
    """
    cfg = config or {}
    if not is_field_enabled(cfg, "SYNC_FIELD_PRODUCT_NAME"):
        if is_create:
            payload["name"] = payload.get("name") or payload.get("sku") or ""
        else:
            payload.pop("name", None)
    if not is_field_enabled(cfg, "SYNC_FIELD_PRODUCT_DESCRIPTION"):
        payload.pop("description", None)
    if not is_field_enabled(cfg, "SYNC_FIELD_PRODUCT_CATEGORIES"):
        payload.pop("categories", None)
    if not is_field_enabled(cfg, "SYNC_FIELD_PRODUCT_VISIBILITY"):
        payload.pop("catalog_visibility", None)
    # روی ووکامرس، manage_stock=False برای محصول متغیر یک تنظیم فنیِ ثابته
    # (نه دادهٔ انبار)، پس این چک‌باکس روش بی‌اثره. ولی روی پرستاشاپ، سطح
    # محصولِ ترکیبی هم موجودیِ واقعیِ resolve‌شده رو حمل می‌کنه (برای رفع
    # باگ «محصول ترکیبی همیشه موجود می‌موند») — پس اونجا این چک‌باکس باید
    # برای محصول متغیر هم اعمال بشه.
    stock_field_applies = payload.get("type") == "simple" or (
        payload.get("type") == "variable" and is_prestashop(cfg)
    )
    if not is_field_enabled(cfg, "SYNC_FIELD_PRODUCT_STOCK") and stock_field_applies:
        payload.pop("manage_stock", None)
        payload.pop("stock_quantity", None)
    return payload


def _upsert_wc_product(wcapi, sku, p_data, has_variants, product_map, *, stock_quantity=None, persist_map=True, config=None):
    """محصول هست update، trash/نیست post جدید."""
    existing_id, product_map = resolve_existing_product_id(wcapi, sku, product_map)
    payload = dict(p_data)
    payload["status"] = "publish"
    payload["catalog_visibility"] = p_data.get("catalog_visibility") or "visible"
    if has_variants:
        payload["type"] = "variable"
        if is_prestashop(config):
            # روی پرستاشاپ، p_data از قبل (تو _sync_one_row) با
            # apply_stock_mode_to_payload بر اساس حالت موجودیِ resolve‌شده
            # ساخته شده — نباید این‌جا بی‌قید و شرط با «همیشه موجود» رونویسی
            # بشه، وگرنه هیچ حالت موجودیِ دیگه‌ای (دیتابیس/دسته‌بندی) روی
            # محصولاتِ ترکیبی اثر نمی‌کنه.
            pass
        else:
            payload.pop("stock_quantity", None)
            payload["manage_stock"] = False

    if existing_id and is_manual_product_link(sku):
        target = fetch_product_by_id(wcapi, int(existing_id))
        if target and str(target.get("sku") or "").strip() != sku:
            payload.pop("sku", None)

    payload = _apply_field_sync_config(payload, config, is_create=not existing_id)

    if existing_id:
        p_id = int(existing_id)
        resp = wcapi.put(f"products/{p_id}", payload)
        data = wc_parse_json(resp, f"PUT محصول {sku}")
        saved_pid = int(data.get("id") or p_id)
        log.info(f"🔄 [{sku}] بروزرسانی → Woo #{saved_pid}")
    else:
        product_map = clear_trashed_sku_blockers(wcapi, sku, product_map)
        resp = wcapi.post("products", payload)
        data = wc_parse_json(resp, f"POST محصول {sku}")
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"POST محصول {sku} بدون id: {data}")
        saved_pid = int(data["id"])
        log.info(f"➕ [{sku}] ایجاد → Woo #{saved_pid}")

    status = str((data or {}).get("status") or "").strip()
    if status not in ("publish", "draft", "private", "pending"):
        verify_product_saved(wcapi, saved_pid, sku)
    mapped_before = int((product_map or {}).get(sku) or 0)
    if is_manual_product_link(sku) and mapped_before and int(saved_pid) != mapped_before:
        raise RuntimeError(
            f"تضاد امنیتی [{sku}]: تطبیق دستی → Woo #{mapped_before} "
            f"اما sync به #{saved_pid} رفت — ارسال لغو شد."
        )
    product_map[sku] = saved_pid
    if persist_map:
        save_product_woo_map(product_map)
    return saved_pid, product_map, data


def _apply_site_variation_override(
    wcapi, config, sku, matched_group, target, raw_price, raw_sale, stock_quantity, price_div,
):
    """این SKU در ERP یه کالایِ سادهٔ مستقله، ولی طبقِ override دستیِ کاربر
    (تبِ «تطبیقِ ساختاری») در واقع یه واریانتِ یه محصولِ متغیرِ سایته — پس
    به‌جایِ ساختن/به‌روزرسانیِ یه محصولِ جدا، فقط قیمت/موجودیِ همون واریانتِ
    شناخته‌شده روی سایت آپدیت می‌شه."""
    parent_id = int(target["parent_product_id"])
    variation_id = int(target["variation_id"])

    if is_prestashop(config):
        from sync_app.core.ps_sync_helper import ps_get_product, ps_set_stock_quantity
        from sync_app.core.ps_variation_helper import ps_update_combination

        parent = ps_get_product(config, parent_id)
        if not parent:
            log.error(
                f"❌ [{sku}] محصولِ والدِ سایت #{parent_id} (طبقِ override) پیدا نشد — "
                "به‌روزرسانی رد شد."
            )
            return
        try:
            base_price = float(parent.get("regular_price") or 0)
        except (TypeError, ValueError):
            base_price = 0.0
        variant_price = float(raw_price or 0) / max(float(price_div or 1), 1.0)
        price_impact = variant_price - base_price
        ps_update_combination(config, variation_id, price_impact=price_impact)
        if is_field_enabled(config, "SYNC_FIELD_VARIATION_STOCK"):
            from sync_app.core.stock_mode import resolve_variation_stock_mode, STOCK_MODE_ALWAYS, STOCK_MODE_DOWNLOAD, STOCK_MODE_OUT_OF_STOCK

            v_mode = resolve_variation_stock_mode(sku, sku, matched_group, config)
            if v_mode == STOCK_MODE_OUT_OF_STOCK:
                qty, out_of_stock = 0, 0
            elif v_mode in (STOCK_MODE_ALWAYS, STOCK_MODE_DOWNLOAD):
                qty, out_of_stock = 9999, 1
            else:
                qty, out_of_stock = max(0, int(stock_quantity or 0)), 0
            ps_set_stock_quantity(config, parent_id, qty, product_attribute_id=variation_id, out_of_stock=out_of_stock)
        log.info(
            f"🔀 [{sku}] بر اساسِ override دستی، به‌عنوانِ ترکیبِ #{variation_id} از محصولِ #{parent_id} "
            "سایت به‌روزرسانی شد (نه محصولِ مستقل)."
        )
        return

    patch = {"regular_price": str(int(raw_price / price_div)) if raw_price > 0 else "0"}
    sale_str = woo_sale_price_str(raw_price, raw_sale, price_div)
    if sale_str:
        patch["sale_price"] = sale_str
    if is_field_enabled(config, "SYNC_FIELD_VARIATION_STOCK"):
        from sync_app.core.stock_mode import resolve_variation_stock_mode, apply_stock_mode_to_payload

        v_mode = resolve_variation_stock_mode(sku, sku, matched_group, config)
        apply_stock_mode_to_payload(patch, v_mode, stock_quantity)
    resp = wcapi.put(f"products/{parent_id}/variations/{variation_id}", patch)
    wc_parse_json(resp, f"بروزرسانیِ واریانتِ سایت برایِ {sku}")
    log.info(
        f"🔀 [{sku}] بر اساسِ override دستی، به‌عنوانِ واریانتِ #{variation_id} از محصولِ #{parent_id} "
        "سایت به‌روزرسانی شد (نه محصولِ مستقل)."
    )


def _sync_product_images_if_needed(wcapi, sku, saved_pid, upsert_data, erp_images, raw_config):
    """
    erp_images: لیستی از (hlo_id, blob, path) — hlo_id شناسه‌ی یکتای همون
    ردیف تو HLOpictures هست. با یه فایل JSON (transferred_erp_images.json)
    چک می‌کنیم کدوم hlo_id ها قبلاً منتقل شدن — نه صرفاً «تعداد» که با
    حذف/اضافه‌شدن تصاویر قدیمی/جدید به‌هم می‌ریخت.
    """
    from sync_app.core.erp_image_helper import load_transferred_image_ids, mark_images_transferred

    already_transferred = set(load_transferred_image_ids().get(str(sku).strip(), []))
    new_erp_images = [(hlo_id, blob, path) for hlo_id, blob, path in erp_images if hlo_id not in already_transferred]
    if not new_erp_images:
        return  # همه‌ی تصاویر ERP قبلاً منتقل شدن — چیز جدیدی نیست

    existing_images = (upsert_data or {}).get("images") or []

    try:
        from sync_app.core.erp_image_helper import stage_erp_images
        from sync_app.core.smart_publish import apply_default_pipeline
        from sync_app.core.wc_sync_helper import wp_upload_media_ex

        # هر تصویرِ جدید رو با اسم مبتنی بر hlo_id ذخیره می‌کنیم — تا اگه
        # این تابع چندبار اجرا بشه، فایل‌های محلیِ قبلی رو خراب نکنه.
        rel_by_hlo_id: dict[int, str] = {}
        for hlo_id, blob, path in new_erp_images:
            rels = stage_erp_images(f"{sku}_hlo{hlo_id}", blob, path, raw_config)
            if rels:
                rel_by_hlo_id[hlo_id] = rels[0]

        if not rel_by_hlo_id:
            return

        site_url = str(raw_config.get("WC_URL") or "").strip().rstrip("/")
        product_url = f"{site_url}/?p={int(saved_pid)}" if site_url else ""

        uploaded_ids = []
        transferred_hlo_ids = []
        for hlo_id, rel in rel_by_hlo_id.items():
            abs_path = app_path_from_rel(rel)
            if not os.path.isfile(abs_path):
                continue
            # روشِ پردازشِ تصویرِ پیش‌فرض (اگه در تنظیمات ست شده باشه) — همون
            # نقطه‌ی مشترکی که همه‌ی روش‌هایِ انتقالِ تصویر (دیتابیس/دستی/
            # گروهی/دسته‌بندی) ازش استفاده می‌کنن؛ اگه پیش‌فرضی نباشه، همون
            # تصویرِ خام/اصلی برمی‌گرده.
            final_path = apply_default_pipeline(abs_path, raw_config, code=sku, product_url=product_url)

            with open(final_path, "rb") as f:
                img_data = f.read()
            ok, media_id, _url, err = wp_upload_media_ex(
                raw_config, img_data, os.path.basename(final_path), fallback_stem=sku, label=f"تصویر {sku}"
            )
            if ok and media_id:
                uploaded_ids.append(media_id)
                transferred_hlo_ids.append(hlo_id)
            else:
                log.warning(f"⚠️ آپلود تصویر {sku} (hlo_id={hlo_id}) ناموفق: {err}")

        if uploaded_ids:
            existing_ids = [img.get("id") for img in existing_images if img.get("id")]
            payload = {"images": [{"id": i} for i in existing_ids] + [{"id": mid} for mid in uploaded_ids]}
            resp = wcapi.put(f"products/{int(saved_pid)}", payload)
            wc_parse_json(resp, f"اتصال تصویر به محصول {sku}")
            # فقط تصاویری که واقعاً آپلود موفق بودن رو ثبت می‌کنیم — اگه
            # یکی fail بشه، دفعه‌ی بعد دوباره امتحان می‌شه (نه گم می‌شه).
            mark_images_transferred(sku, transferred_hlo_ids)
            from sync_app.core.integrations.erp_provider import erp_provider_label

            log.info(
                f"🖼️ [{sku}] {len(uploaded_ids)} تصویر جدید از {erp_provider_label(raw_config)} "
                f"اضافه شد (مجموع: {len(payload['images'])})."
            )
    except Exception as exc:
        log.warning(f"⚠️ انتقال تصویر محصول {sku} با خطا مواجه شد: {exc}")


def _sync_product_images_if_needed_ps(config, sku, product_id, erp_images):
    """معادل _sync_product_images_if_needed برای پرستاشاپ.

    برخلاف ووکامرس (آپلود به کتابخانه‌ی رسانه‌ی وردپرس + PUT یک‌جای آرایه‌ی
    id تصاویر)، پرستاشاپ آرایه‌ی «ست‌کردن یک‌جا» گالری نداره — هر تصویر با
    یک POST جدا مستقیماً به گالری محصول اضافه می‌شه (ps_upload_product_image).
    """
    from sync_app.core.erp_image_helper import load_transferred_image_ids, mark_images_transferred, stage_erp_images
    from sync_app.core.ps_sync_helper import ps_upload_product_image

    if not erp_images:
        from sync_app.core.integrations.erp_provider import erp_provider_label

        log.info(f"ℹ️ [{sku}] هیچ تصویری در HLOpictures ({erp_provider_label(config)}) برای این کد کالا پیدا نشد.")
        return

    already_transferred = set(load_transferred_image_ids("prestashop").get(str(sku).strip(), []))
    new_erp_images = [(hlo_id, blob, path) for hlo_id, blob, path in erp_images if hlo_id not in already_transferred]
    if not new_erp_images:
        log.info(
            f"ℹ️ [{sku}] {len(erp_images)} تصویر ERP پیدا شد ولی همه قبلاً به پرستاشاپ منتقل شده — رد شد."
        )
        return

    log.info(f"🖼️ [{sku}] {len(new_erp_images)} تصویر جدید از ERP برای انتقال به پرستاشاپ پیدا شد...")

    try:
        from sync_app.core.smart_publish import apply_default_pipeline

        rel_by_hlo_id: dict[int, str] = {}
        for hlo_id, blob, path in new_erp_images:
            rels = stage_erp_images(f"{sku}_hlo{hlo_id}", blob, path, config)
            if rels:
                rel_by_hlo_id[hlo_id] = rels[0]

        if not rel_by_hlo_id:
            log.warning(
                f"⚠️ [{sku}] {len(new_erp_images)} تصویر ERP پیدا شد ولی هیچ‌کدام روی دیسک ذخیره/staged نشدند."
            )
            return

        site_url = str(config.get("PS_URL") or "").strip().rstrip("/")
        product_url = f"{site_url}/index.php?id_product={int(product_id)}&controller=product" if site_url else ""

        uploaded_count = 0
        transferred_hlo_ids = []
        for hlo_id, rel in rel_by_hlo_id.items():
            abs_path = app_path_from_rel(rel)
            if not os.path.isfile(abs_path):
                continue
            final_path = apply_default_pipeline(abs_path, config, code=sku, product_url=product_url)

            try:
                with open(final_path, "rb") as f:
                    img_data = f.read()
                ps_upload_product_image(config, int(product_id), img_data, os.path.basename(final_path))
                uploaded_count += 1
                transferred_hlo_ids.append(hlo_id)
            except Exception as exc:
                log.warning(f"⚠️ آپلود تصویر {sku} (hlo_id={hlo_id}) روی پرستاشاپ ناموفق: {exc}")

        if uploaded_count:
            mark_images_transferred(sku, transferred_hlo_ids, "prestashop")
            from sync_app.core.integrations.erp_provider import erp_provider_label

            log.info(
                f"🖼️ [{sku}] {uploaded_count} تصویر جدید از {erp_provider_label(config)} "
                "به گالری پرستاشاپ اضافه شد."
            )
    except Exception as exc:
        log.warning(f"⚠️ انتقال تصویر محصول {sku} با خطا مواجه شد: {exc}")


def app_path_from_rel(rel: str) -> str:
    from sync_app.core.sync_utils import app_path as _real_app_path
    return _real_app_path(*rel.split("/"))


def _apply_product_categories(
    wcapi,
    product_id,
    sku,
    categories,
    config,
    *,
    cat_map=None,
    slug_map=None,
):
    """PUT دسته + تأیید سهل‌گیر روی Woo.

    منطق: ابتدا دسته‌های ورودی (resolve از map+slug) ارسال می‌شود، سپس نسخهٔ
    زندهٔ slug. تأیید سهل‌گیر است: کافی است زیرگروه با «کد ERP» یا «ID» روی محصول
    دیده شود — تا دسته‌های تکراری/والد-تنها باعث خطای کاذب نشوند.
    """
    if not slug_map:
        try:
            ctx = prepare_category_context(config, fetch_live=True)
            slug_map = ctx.get("slug_map") or {}
            if cat_map is None:
                cat_map = ctx.get("category_map")
        except Exception:
            slug_map = slug_map or {}

    leaf_code = (sku_to_category_codes(sku) or [""])[0]
    live_cats, live_leaf = resolve_live_product_categories(sku, slug_map)
    if live_leaf:
        leaf_code = live_leaf

    def _put(cats):
        resp = wcapi.put(f"products/{product_id}", {"categories": cats})
        return wc_parse_json(resp, f"PUT دسته {sku}")

    def _read():
        resp = wcapi.get(
            f"products/{product_id}", params={"_fields": "id,categories"}
        )
        return wc_parse_json(resp, f"GET دسته {sku}")

    def _ok(data, cats):
        """تأیید سهل‌گیر: زیرگروه با کد ERP یا با ID روی محصول باشد."""
        if not isinstance(data, dict):
            return False
        if leaf_code and slug_map and verify_categories_by_code(data, leaf_code, slug_map):
            return True
        # ID زیرگروه (آخرین مورد) روی محصول باشد
        got_ids = {
            int(c.get("id"))
            for c in (data.get("categories") or [])
            if isinstance(c, dict) and c.get("id")
        }
        if cats and int(cats[-1].get("id") or 0) in got_ids:
            return True
        # دست‌کم یکی از دسته‌های خواسته‌شده اعمال شده باشد
        want = {int(c.get("id") or 0) for c in (cats or []) if c.get("id")}
        return bool(want & got_ids)

    def _try_apply(cats):
        if not cats:
            return None
        put_data = wc_call(
            wcapi, f"اعمال دسته به محصول {sku}", lambda: _put(cats), retries=1
        )
        if _ok(put_data, cats):
            return cats
        got = wc_call(wcapi, f"خواندن دسته محصول {sku}", _read, retries=1)
        if _ok(got, cats):
            return cats
        # لاگ تشخیصی دقیق برای رفع ریشه‌ای
        has_leaf_slug = bool(slug_map and f"cat-{leaf_code}" in (slug_map or {}))
        log.warning(
            f"⚠️ دسته [{sku}] ننشست — {format_category_verify_miss(got, cats)} "
            f"| کد زیرگروه={leaf_code} | slug 'cat-{leaf_code}' روی Woo؟ {has_leaf_slug}"
        )
        return None

    tried: list = []
    for cats in (categories, live_cats):
        if not cats or cats in tried:
            continue
        tried.append(cats)
        applied = _try_apply(cats)
        if applied:
            return applied

    if not tried:
        log.error(
            f"❌ دسته [{sku}] resolve نشد — کد زیرگروه={leaf_code}؛ "
            "اول تب «دسته‌بندی‌ها» را همگام‌سازی کنید."
        )
    return None


def patch_product_categories(config=None):
    """دسته محصولات را با map زنده Woo روی محصولات اعمال کن."""
    config = config or load_secure_config(None) or {}
    if bool(config.get("DISABLE_ERP_CATEGORY_SYNC", False)):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        log.info(
            f"ℹ️ سینکِ خودکارِ دسته‌بندیِ {erp_provider_label(config)} خاموشه — اعمالِ دسته‌بندی رویِ "
            "محصولات رد شد (دسته‌بندیِ سایت رو از تبِ «دسته‌بندی و برند» الصاق کنید)."
        )
        return {"ok": 0, "skipped": 0, "failed": 0, "failed_skus": []}
    if not is_prestashop(config):
        apply_network_overrides(config)
    wcapi = build_store_api(config)
    warm_store_connection(wcapi, config)

    ctx = prepare_category_context(config, fetch_live=True)
    cat_map = ctx["category_map"]
    slug_map = ctx["slug_map"]
    if ctx.get("stale_updates"):
        log.info(f"🔄 category_map به‌روز شد: {', '.join(ctx['stale_updates'][:5])}")

    from sync_app.core.category_rules import product_skus_for_selected_groups

    groups = [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
    stats = {"ok": 0, "skipped": 0, "failed": 0, "failed_skus": []}
    if not cat_map and not slug_map:
        log.error("❌ category_map.json خالی است — دسته‌ها در Woo ساخته نشده‌اند.")
        return stats
    if not groups:
        log.warning("⚠️ هیچ زیرگروهی انتخاب نشده — دسته به محصولات اعمال نشد.")
        return stats

    skus = product_skus_for_selected_groups(config)

    product_map = _load_product_woo_map()
    from sync_app.core.sync_cancel import check_cancelled

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    from sync_app.core.wc_sync_helper import wc_is_slow_connection

    log.info(f"▶️ اعمال دسته Woo روی {len(skus)} محصول...")
    stats_lock = threading.Lock()

    def _apply_one(sku):
        check_cancelled()
        categories = _categories_for_sku(sku, cat_map, slug_map, config)
        if not categories:
            log.warning(f"⚠️ {explain_category_miss(sku, cat_map, slug_map)}")
            with stats_lock:
                stats["skipped"] += 1
            return
        try:
            p_id = _resolve_wc_product_id(wcapi, sku, product_map)
            if not p_id:
                log.warning(f"⚠️ محصول {sku} در Woo نیست — رد شد.")
                with stats_lock:
                    stats["skipped"] += 1
                return

            applied = _apply_product_categories(
                wcapi, p_id, sku, categories, config,
                cat_map=cat_map, slug_map=slug_map,
            )
            if applied:
                cat_ids = ", ".join(str(c["id"]) for c in applied)
                log.info(f"✅ دسته [{cat_ids}] → محصول {sku} (ID:{p_id})")
                with stats_lock:
                    stats["ok"] += 1
            else:
                log.error(f"❌ دسته روی محصول {sku} اعمال نشد — IDها را بررسی کنید.")
                with stats_lock:
                    stats["failed"] += 1
                    stats["failed_skus"].append(sku)
        except Exception as exc:
            log.error(f"❌ اعمال دسته به {sku}: {exc}")
            with stats_lock:
                stats["failed"] += 1
                stats["failed_skus"].append(sku)

    # شبکه کند → تک‌تک؛ سریع → موازی برای سرعت بیشتر.
    if wc_is_slow_connection(config) or len(skus) <= 1:
        for sku in skus:
            _apply_one(sku)
    else:
        try:
            workers = min(10, max(2, int(config.get("WC_PARALLEL_WORKERS", 10) or 10)))  # سقف دفاعی: جلوگیری از تشخیص DDoS توسط هاست
        except Exception:
            workers = 10
        workers = min(workers, len(skus))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_apply_one, sku) for sku in skus]
            for future in as_completed(futures):
                future.result()

    log.info(
        f"📊 اعمال دسته محصولات: {stats['ok']} موفق، "
        f"{stats['failed']} خطا، {stats['skipped']} رد/بدون محصول"
    )
    return stats


def main():
    raw_config = load_secure_config(None) or {}
    ps_mode = is_prestashop(raw_config)
    if not ps_mode:
        apply_network_overrides(raw_config)
    wcapi = build_store_api(raw_config)
    warm_store_connection(wcapi, raw_config)

    conn, _, _ = open_sql_connection(raw_config, timeout=10)
    price_div = erp_price_divisor(raw_config)
    GROUPS = raw_config.get("SELECTED_SUB_GROUPS", [])
    DISABLED_PRODUCT_SKUS = set(raw_config.get("DISABLED_PRODUCT_SKUS", []))

    stats = {"ok": 0, "failed": 0, "failed_skus": [], "last_error": None}

    ctx = prepare_category_context(raw_config, fetch_live=True)
    cat_map = ctx["category_map"]
    slug_map = ctx["slug_map"]
    if ctx.get("stale_updates"):
        log.info(f"🔄 category_map به‌روز شد: {', '.join(ctx['stale_updates'][:5])}")
    if not cat_map and not slug_map:
        log.warning("⚠️ category_map.json یافت نشد — محصولات بدون دسته ارسال می‌شوند.")

    product_map = _load_product_woo_map()
    attr_labels = None
    global_ids = None
    term_lookup = None

    from sync_app.core.variation_query import load_variable_a_codes
    from sync_app.core.wc_attr_cache import load_wc_attr_cache, save_wc_attr_cache
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    from sync_app.core.wc_sync_helper import wc_is_slow_connection

    # هر Thread یه Connection SQL جدا نگه می‌داره و برای همه‌ی محصولاتِ
    # متغیری که همون Thread پردازش می‌کنه دوباره استفاده می‌شه — به‌جای باز/
    # بسته‌کردنِ یک Connection کاملاً جدید به‌ازای هر محصول (که با تعداد
    # زیادِ محصولِ متغیر، هزینه‌ی handshake زیادی داشت).
    _conn_pool_lock = threading.Lock()
    _conn_pool = []
    _thread_local = threading.local()

    def _get_thread_local_conn():
        local_conn = getattr(_thread_local, "conn", None)
        if local_conn is None:
            local_conn, _, _ = open_sql_connection(raw_config, timeout=10)
            _thread_local.conn = local_conn
            with _conn_pool_lock:
                _conn_pool.append(local_conn)
        return local_conn

    map_dirty = False
    cursor = conn.cursor()
    variable_codes = load_variable_a_codes(cursor)

    # پیش‌واکشیِ یک‌باره‌ی همه‌ی تصاویر ERP (از HLOpictures، نه Article که
    # ملاک نیست) برای همه‌ی محصولات این دور سینک — تا داخل حلقه‌ی موازی
    # مجبور نباشیم به‌ازای هر محصول یه کوئری SQL جدا بزنیم. شناسه‌ی یکتای
    # ردیف (ID) هم می‌گیریم — چون این تنها راه مطمئنِ تشخیص «این تصویر
    # قبلاً منتقل شده یا نه»ست (شمارش تعداد با حذف/اضافه‌شدن تصویر خراب می‌شه).
    erp_images_by_sku: dict[str, list[tuple[int, bytes, str]]] = {}
    try:
        pic_like = " OR ".join(["Code LIKE ?" for _ in GROUPS])
        cursor.execute(
            f"SELECT ID, Code, Picture, PicturePath FROM HLOpictures WHERE Type = 1 AND ({pic_like})",
            [f"{g}%" for g in GROUPS],
        )
        for prow in cursor.fetchall():
            hlo_id = int(prow[0])
            code = str(prow[1]).strip()
            blob = bytes(prow[2]) if prow[2] else b""
            path = str(prow[3] or "").strip()
            if blob or path:
                erp_images_by_sku.setdefault(code, []).append((hlo_id, blob, path))
    except Exception as exc:
        log.warning(f"⚠️ واکشی تصاویر HLOpictures ناموفق بود — تصاویر این دور منتقل نمی‌شن: {exc}")
    from sync_app.core.integrations.erp_provider import erp_provider_label

    erp_label = erp_provider_label(raw_config)
    total_erp_images = sum(len(v) for v in erp_images_by_sku.values())
    if total_erp_images:
        log.info(
            f"🖼️ پیش‌واکشی تصاویر {erp_label}: {total_erp_images} تصویر برای {len(erp_images_by_sku)} کد کالا در HLOpictures پیدا شد."
        )
    else:
        log.info(
            f"ℹ️ پیش‌واکشی تصاویر {erp_label}: هیچ تصویری در HLOpictures برای زیرگروه‌های انتخاب‌شده پیدا نشد "
            f"(Code LIKE {[f'{g}%' for g in GROUPS]}, Type=1)."
        )

    def _attribute_labels():
        nonlocal attr_labels
        if attr_labels is not None:
            return attr_labels
        from sync_app.core.scripts.update_variations import _fetch_attribute_labels_list

        attr_labels = _fetch_attribute_labels_list(conn)
        return attr_labels

    def _ensure_wc_attr_cache():
        nonlocal global_ids, term_lookup
        if global_ids is not None and term_lookup is not None:
            return global_ids, term_lookup
        dim_labels = _attribute_labels()
        cached_ids, cached_terms = load_wc_attr_cache(dim_labels)
        if cached_ids and cached_terms:
            global_ids, term_lookup = cached_ids, cached_terms
            log.info("▸ cache ویژگی Woo (سریع)")
            return global_ids, term_lookup
        from sync_app.core.scripts.update_variations import (
            _fetch_global_attribute_ids,
            _fetch_term_lookup,
        )

        log.info("▸ دریافت attributes و terms از Woo...")
        global_ids = _fetch_global_attribute_ids(wcapi)
        term_lookup = _fetch_term_lookup(wcapi, global_ids, only_names=list(dim_labels))
        save_wc_attr_cache(global_ids, term_lookup, dim_labels)
        return global_ids, term_lookup

    cursor.execute(
        "SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5, "
        "Exist, Attribute FROM Article WHERE LEN(A_Code) >= 4"
    )
    db_rows = cursor.fetchall()
    rows_by_sku = {str(r[0]).strip(): r for r in db_rows}

    from sync_app.core.stock_group import is_secondary, combined_stock_for_primary

    rows_to_process = [
        row for row in db_rows
        if str(row[0]).strip() not in DISABLED_PRODUCT_SKUS
        and any(str(row[0]).strip().startswith(g) for g in GROUPS)
        # محصولات «فرعی» (که فقط موجودی‌شون به یه محصول اصلی دیگه اضافه
        # می‌شه) اصلاً نباید مستقل به ووکامرس ارسال بشن.
        and not is_secondary(raw_config, str(row[0]).strip())
    ]

    _total_to_process = len(rows_to_process)

    def _stock_lookup(sku: str) -> int:
        row = rows_by_sku.get(str(sku).strip())
        return int(row[7] or 0) if row else 0

    # اگه بین این محصولات، محصول متغیر هم هست، کش‌های attribute رو همین‌جا
    # (قبل از اجرای هم‌زمان) یه‌بار گرم می‌کنیم — چون این کش‌ها lazy-init
    # هستن و اگه چندتا Thread هم‌زمان اولین‌بار بخوان پرشون کنن، race
    # می‌شه (نتیجه خراب نمی‌شه، ولی چندبار الکی API/DB صدا زده می‌شه).
    if any(str(row[0]).strip() in variable_codes for row in rows_to_process):
        _attribute_labels()
        if not ps_mode:
            _ensure_wc_attr_cache()

    stats_lock = threading.Lock()
    map_lock = threading.Lock()
    _processed_count = 0
    progress_lock = threading.Lock()

    # تشخیصِ تغییر: هر SKU (ساده یا متغیر) که از آخرین سینکِ موفق دقیقاً
    # هیچی توش عوض نشده (نه فیلدهای محصول، نه دسته/تصاویر، نه ردیف‌های
    # واریانت) رد می‌شه — بدون هیچ فراخوانیِ API.
    from sync_app.core.sync_change_cache import load_hash_cache, save_hash_cache, should_skip_unchanged
    from sync_app.core.field_sync_config import all_field_keys, is_force_full_sync

    sync_hash_cache = load_hash_cache("products", raw_config)
    hash_lock = threading.Lock()
    settings_fingerprint = {k: is_field_enabled(raw_config, k) for k in all_field_keys()}
    skipped_unchanged = {"count": 0}
    force_full_sync = is_force_full_sync(raw_config, "FORCE_FULL_SYNC_PRODUCTS")
    if force_full_sync:
        log.info("⚡ «همیشه همه‌ی محصولات دوباره ارسال شود» فعاله — تشخیصِ تغییر این دور نادیده گرفته می‌شه.")

    def _sync_one_row(row):
        nonlocal _processed_count
        sku = str(row[0]).strip()
        matched_group = next((g for g in GROUPS if sku.startswith(g)), "")

        with progress_lock:
            _processed_count += 1
            current_num = _processed_count

        from sync_app.core.category_price_list import resolve_article_price_column

        price_col = resolve_article_price_column(sku, matched_group, raw_config)
        raw_price = _resolve_article_price(row, price_col)
        raw_price = apply_price_markup(raw_price, raw_config, is_sale=False, sku=sku)
        price = str(int(raw_price / price_div)) if raw_price > 0 else "0"
        raw_sale = resolve_sale_article_price(row, raw_config, sku=sku)
        raw_sale = apply_price_markup(raw_sale, raw_config, is_sale=True, sku=sku)
        sale_price = woo_sale_price_str(raw_price, raw_sale, price_div)

        from sync_app.core.structure_mismatch_override import get_site_variation_target

        site_variation_target = get_site_variation_target(sku)
        if site_variation_target:
            # این SKU در ERP یه کالایِ سادهٔ مستقله، ولی طبقِ تطبیقِ دستیِ
            # کاربر، در واقع یه واریانتِ یه محصولِ متغیرِ سایته — نه محصولِ
            # جدا. کاملاً از مسیرِ عادیِ ساخت/به‌روزرسانیِ محصول رد می‌شیم.
            try:
                stock_quantity = combined_stock_for_primary(sku, int(row[7] or 0), raw_config, _stock_lookup)
                _apply_site_variation_override(
                    wcapi, raw_config, sku, matched_group, site_variation_target,
                    raw_price, raw_sale, stock_quantity, price_div,
                )
                with stats_lock:
                    stats["ok"] += 1
            except Exception as e:
                with stats_lock:
                    stats["failed"] += 1
                    stats["failed_skus"].append(sku)
                    stats["last_error"] = e
                log.error(f"❌ خطا در به‌روزرسانیِ واریانتِ سایت برایِ {sku}: {e}")
            return

        has_variants = _has_variations(conn, sku, variable_codes)
        stock_quantity = combined_stock_for_primary(sku, int(row[7] or 0), raw_config, _stock_lookup)

        if has_variants:
            from sync_app.core.structure_mismatch_override import get_force_simple_source

            forced_source_sku = get_force_simple_source(sku)
            if forced_source_sku:
                # طبقِ دیتابیس این محصول متغیره، ولی طبقِ تطبیقِ دستیِ کاربر
                # رویِ سایت محصولِ ساده‌ست — به‌جایِ سینک به‌عنوانِ محصولِ
                # متغیر، فقط دادهٔ همین یه زیرواریانتِ انتخاب‌شده رو به‌عنوانِ
                # قیمت/موجودیِ محصولِ سادهٔ سایت استفاده می‌کنیم.
                try:
                    from sync_app.core.scripts.update_variations import fetch_variations_from_db

                    local_conn_fs = _get_thread_local_conn()
                    dim_labels_fs = _attribute_labels()
                    erp_vars_fs, _attr_map_fs = fetch_variations_from_db(
                        local_conn_fs, sku, raw_price,
                        dim_labels_fs[0] if dim_labels_fs else "سایز",
                        dim_labels_fs[1] if len(dim_labels_fs) > 1 else "",
                        dim_labels_fs[2] if len(dim_labels_fs) > 2 else "",
                        config=raw_config,
                    )
                    chosen = next(
                        (v for v in erp_vars_fs if str(v.get("sku") or "").strip() == forced_source_sku), None,
                    )
                    if chosen:
                        has_variants = False
                        raw_price = float(chosen.get("regular_price") or 0) or raw_price
                        price = str(int(raw_price / price_div)) if raw_price > 0 else "0"
                        chosen_sale = chosen.get("sale_price")
                        try:
                            raw_sale = float(chosen_sale or 0)
                        except (TypeError, ValueError):
                            raw_sale = 0.0
                        sale_price = woo_sale_price_str(raw_price, raw_sale, price_div)
                        stock_quantity = int(chosen.get("stock_quantity") or 0)
                        log.info(
                            f"🔀 [{sku}] طبقِ تطبیقِ دستی، به‌جایِ محصولِ متغیر، به‌عنوانِ محصولِ سادهٔ سایت "
                            f"با دادهٔ زیرواریانتِ «{forced_source_sku}» سینک می‌شه."
                        )
                    else:
                        from sync_app.core.integrations.erp_provider import erp_provider_label

                        log.warning(
                            f"⚠️ [{sku}] تطبیقِ «سینک به‌عنوانِ محصولِ ساده» ست شده ولی زیرواریانتِ "
                            f"«{forced_source_sku}» در {erp_provider_label(raw_config)} پیدا نشد — "
                            "طبقِ حالتِ متغیرِ عادی ادامه می‌ده."
                        )
                except Exception as exc:
                    log.warning(
                        f"⚠️ [{sku}] بررسیِ تطبیقِ «سینک به‌عنوانِ محصولِ ساده» با خطا مواجه شد: {exc} — "
                        "طبقِ حالتِ متغیرِ عادی ادامه می‌ده."
                    )

        description = str(row[8] or "").strip()

        disable_erp_categories = bool((raw_config or {}).get("DISABLE_ERP_CATEGORY_SYNC", False))
        # وقتی سینکِ خودکارِ دسته‌بندیِ ERP خاموشه، cat_id هم نباید fallback
        # بشه — وگرنه همون دسته‌بندیِ خودکار از یه راهِ دیگه (این‌بار بدونِ
        # اطلاعِ کاربر) دوباره اعمال می‌شد.
        cat_id = None if disable_erp_categories else _category_id_for_sku(sku, cat_map, slug_map)
        categories = _categories_for_sku(sku, cat_map, slug_map, raw_config)

        p_data = {
            "name": str(row[1]).strip(),
            "sku": sku,
            "regular_price": price,
            "status": "publish",
            "catalog_visibility": "hidden" if sku in DISABLED_PRODUCT_SKUS else "visible",
        }
        if description:
            p_data["description"] = description
        if sale_price:
            p_data["sale_price"] = sale_price
        if categories:
            p_data["categories"] = categories
        elif cat_id:
            p_data["categories"] = [{"id": int(cat_id)}]
        elif disable_erp_categories:
            from sync_app.core.integrations.erp_provider import erp_provider_label

            log.info(
                f"ℹ️ [{sku}] سینکِ خودکارِ دسته‌بندیِ {erp_provider_label(raw_config)} خاموشه — بدونِ "
                "دسته‌بندی ارسال می‌شه (بعداً از تبِ «دسته‌بندی و برند» الصاق کنید)."
            )
        else:
            log.warning(f"⚠️ {explain_category_miss(sku, cat_map, slug_map)}")
        if has_variants:
            p_data["type"] = "variable"
            if ps_mode:
                # روی پرستاشاپ (برخلاف ووکامرس)، رکورد موجودیِ خودِ محصولِ
                # ترکیبی (id_product_attribute=0) روی برخی نصب‌ها همچنان در
                # تعیین قابل‌خریدبودن مؤثره — اگه این‌جا همیشه «همیشه موجود»
                # هاردکد بشه، هیچ حالت موجودیِ دیگه‌ای (دیتابیس/دسته‌بندی) اثر
                # نمی‌کنه، صرف‌نظر از چیزی که روی هر ترکیب جدا تنظیم بشه —
                # دقیقاً همون رفتار گزارش‌شده («هر تنظیمی بذارم بازم موجوده»).
                from sync_app.core.stock_mode import (
                    resolve_stock_mode, apply_stock_mode_to_payload, get_product_stock_mode_override,
                )
                stock_mode = resolve_stock_mode(sku, matched_group, raw_config)
                override = get_product_stock_mode_override(raw_config, sku)
                source = "override محصول" if override else f"دسته‌بندی «{matched_group}»"
                log.info(f"📦 [{sku}] حالت موجودی (سطح محصولِ ترکیبی) resolve شد: {stock_mode} (منبع: {source})")
                apply_stock_mode_to_payload(p_data, stock_mode, stock_quantity)
            else:
                p_data["manage_stock"] = False
        else:
            p_data["type"] = "simple"
            from sync_app.core.stock_mode import (
                resolve_stock_mode, apply_stock_mode_to_payload, get_product_stock_mode_override,
            )
            stock_mode = resolve_stock_mode(sku, matched_group, raw_config)
            override = get_product_stock_mode_override(raw_config, sku)
            source = "override محصول" if override else f"دسته‌بندی «{matched_group}»"
            log.info(f"📦 [{sku}] حالت موجودی resolve شد: {stock_mode} (منبع: {source})")
            apply_stock_mode_to_payload(p_data, stock_mode, stock_quantity)

        # هر Thread یه کپی محلی از نگاشت محصول می‌گیره — تا خواندن/نوشتن
        # هم‌زمان روی همون دیکشنری مشترک (که ممکنه فایل رو خراب کنه) رخ نده.
        # نتیجه‌ی نهایی بعد از اتمام همه‌ی Threadها با هم merge می‌شه.
        with map_lock:
            local_map = dict(product_map)

        # برای محصول متغیر، به یه Connection SQL جدا نیاز داریم — چون
        # Connection اصلی (conn) بین Threadها مشترکه و pyodbc معمولاً برای
        # استفاده‌ی هم‌زمان از چند Thread امن نیست. زودتر از قبل باز می‌شه
        # (نه فقط بعد از تصمیمِ سینک) چون برای تشخیصِ تغییرِ واریانت‌ها هم
        # لازمه ردیف‌های واریانت رو زودتر بخونیم. Connection به‌ازای هر
        # Thread یک‌بار باز و برای بقیه‌ی محصولاتِ همون Thread دوباره
        # استفاده می‌شه (_get_thread_local_conn) — نه به‌ازای هر محصول.
        local_conn = None
        erp_variations = None
        attr_map = None
        dim_labels = None
        if has_variants:
            local_conn = _get_thread_local_conn()
            from sync_app.core.scripts.update_variations import fetch_variations_from_db

            dim_labels = _attribute_labels()
            erp_variations, attr_map = fetch_variations_from_db(
                local_conn,
                sku,
                raw_price,
                dim_labels[0] if dim_labels else "سایز",
                dim_labels[1] if len(dim_labels) > 1 else "",
                dim_labels[2] if len(dim_labels) > 2 else "",
                config=raw_config,
            )

        # تشخیصِ تغییر: اگه همون داده‌ای که الان می‌خوایم بفرستیم (شاملِ
        # ردیف‌های واریانت، برای محصولِ متغیر) دقیقاً با آخرین باری که این
        # SKU با موفقیت سینک شده یکی باشه (و از قبل روی فروشگاه ساخته شده)،
        # نیازی به فراخوانیِ API نیست — رد می‌شیم و می‌ریم سراغ محصول بعدی.
        image_ids = sorted(hlo_id for hlo_id, _, _ in erp_images_by_sku.get(sku, []))
        hash_payload = {
            "p_data": p_data, "categories": categories,
            "image_ids": image_ids, "settings": settings_fingerprint,
        }
        if has_variants:
            hash_payload["variants"] = erp_variations
            hash_payload["attr_map"] = attr_map
        skip, cache_entry, changed_parts = should_skip_unchanged(
            sku, hash_payload, sync_hash_cache, local_map.get(sku)
        )
        if force_full_sync:
            skip = False
        if skip:
            with progress_lock:
                skipped_unchanged["count"] += 1
            with stats_lock:
                stats["ok"] += 1
            return

        if local_map.get(sku) and changed_parts:
            log.info(f"🔍 [{sku}] این بخش‌ها عوض شده — دوباره سینک می‌شه: {', '.join(changed_parts)}")

        log.info(f"⏳ محصول {current_num}/{_total_to_process}: {sku}")

        try:
            def _sync_one(pmap=local_map):
                return _upsert_wc_product(
                    wcapi,
                    sku,
                    p_data,
                    has_variants,
                    pmap,
                    stock_quantity=stock_quantity,
                    persist_map=False,
                    config=raw_config,
                )

            saved_pid, local_map, upsert_data = wc_call(
                wcapi, f"همگام‌سازی محصول {sku}", _sync_one
            )

            if not saved_pid:
                raise RuntimeError(f"محصول {sku} ذخیره نشد — id خالی")

            if categories:
                if _upsert_response_categories_ok(upsert_data, categories, sku, slug_map):
                    applied_cats = categories
                else:
                    applied_cats = _apply_product_categories(
                        wcapi,
                        saved_pid,
                        sku,
                        categories,
                        raw_config,
                        cat_map=cat_map,
                        slug_map=slug_map,
                    )
                if not applied_cats:
                    log.warning(
                        f"⚠️ دسته محصول {sku} روی Woo ننشست — "
                        "تب دسته‌بندی‌ها را دوباره همگام کنید."
                    )
                elif applied_cats != categories:
                    categories = applied_cats
                    cat_id = primary_category_id(categories)

            if ps_mode:
                _sync_product_images_if_needed_ps(
                    raw_config, sku, saved_pid, erp_images_by_sku.get(sku, [])
                )
            else:
                _sync_product_images_if_needed(
                    wcapi, sku, saved_pid, upsert_data, erp_images_by_sku.get(sku, []), raw_config
                )

            kind = "متغیر" if has_variants else "ساده"
            cat_note = f"دسته={cat_id}" if cat_id else "بدون دسته"
            if has_variants:
                log.info(
                    f"✅ محصول {kind} {sku} → Woo #{saved_pid}. "
                    f"قیمت پایه={price} (نمایش سایت از واریانت‌ها) | {cat_note}"
                )
                # erp_variations/attr_map/dim_labels از قبل (قبل از تصمیمِ
                # سینک/رد، برای تشخیصِ تغییر) واکشی شدن — دوباره واکشی نمی‌شن.
                if ps_mode:
                    from sync_app.core.ps_variation_helper import ps_sync_product_variations

                    var_ok = ps_sync_product_variations(
                        raw_config, saved_pid, erp_variations, attr_map, price, a_code=sku,
                    )
                    if not var_ok:
                        log.warning(
                            f"⚠️ واریانت‌های {sku} روی پرستاشاپ کامل ارسال نشد — لاگ بالا را ببینید."
                        )
                else:
                    from sync_app.core.scripts.update_variations import (
                        sync_variation_prices_quick,
                        sync_product_variations,
                        should_skip_full_variation_sync,
                    )

                    quick_saved = sync_variation_prices_quick(
                        wcapi,
                        local_conn,
                        raw_config,
                        sku,
                        raw_price,
                        local_map,
                        size_label=dim_labels[0] if dim_labels else None,
                        color_label=dim_labels[1] if len(dim_labels) > 1 else None,
                        variations=erp_variations,
                    )
                    if quick_saved >= len(erp_variations) and erp_variations:
                        skip_full = True
                    elif (
                        quick_saved > 0
                        and saved_pid
                        and erp_variations
                    ):
                        skip_full = should_skip_full_variation_sync(
                            wcapi,
                            saved_pid,
                            erp_variations,
                            attr_map,
                            a_code=sku,
                        )
                    else:
                        skip_full = False
                    if not skip_full:
                        log.info(f"▸ [{sku}] مسیر کامل واریانت (ساخت/به‌روز)...")
                        product_name = str(row[1]).strip()
                        gids, terms = _ensure_wc_attr_cache()
                        var_ok = sync_product_variations(
                            wcapi,
                            local_conn,
                            raw_config,
                            sku,
                            product_name,
                            raw_price,
                            gids,
                            local_map,
                            terms,
                            dim_labels[0] if dim_labels else None,
                            dim_labels[1] if len(dim_labels) > 1 else None,
                        )
                        if not var_ok:
                            log.warning(
                                f"⚠️ قیمت واریانت‌های {sku} ارسال نشد — "
                                "تب «ویژگی‌ها» و «متغیرها» را بررسی کنید."
                            )
            else:
                log.info(
                    f"✅ محصول {kind} {sku} → Woo #{saved_pid}. "
                    f"قیمت={price} | {cat_note}"
                )

            with map_lock:
                product_map.update(local_map)
            with stats_lock:
                stats["ok"] += 1
            with hash_lock:
                sync_hash_cache[sku] = cache_entry

        except Exception as e:
            with stats_lock:
                stats["failed"] += 1
                stats["failed_skus"].append(sku)
                stats["last_error"] = e
            log.error(f"❌ خطا در {sku}: {e}")

    # شبکه کند یا تعداد کم → مثل قبل تک‌تک (رفتار قبلی کاملاً حفظ می‌شه).
    # شبکه سریع → موازی، دقیقاً با همون الگوی امنی که برای اعمال دسته
    # دسته‌بندی محصولات از قبل تو همین فایل استفاده و امتحان شده.
    if wc_is_slow_connection(raw_config) or len(rows_to_process) <= 1:
        for row in rows_to_process:
            _sync_one_row(row)
    else:
        try:
            workers = min(10, max(2, int(raw_config.get("WC_PARALLEL_WORKERS", 10) or 10)))  # سقف دفاعی: جلوگیری از تشخیص DDoS توسط هاست
        except Exception:
            workers = 10
        workers = min(workers, len(rows_to_process))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_sync_one_row, row) for row in rows_to_process]
            for future in as_completed(futures):
                future.result()

    map_dirty = True

    conn.close()
    for _pooled_conn in _conn_pool:
        try:
            _pooled_conn.close()
        except Exception:
            pass

    if map_dirty:
        _save_product_woo_map(product_map)
    save_hash_cache("products", sync_hash_cache, raw_config)

    ok_count = stats["ok"]
    fail_count = stats["failed"]
    if skipped_unchanged["count"]:
        log.info(
            f"⏭️ {skipped_unchanged['count']} محصول بدون تغییر بودن — رد شدن "
            "(هیچ درخواستی به فروشگاه ارسال نشد)."
        )
    log.info(f"📊 پایان همگام‌سازی محصولات: {ok_count} موفق، {fail_count} ناموفق")

    if fail_count > 0:
        sku_list = "، ".join(stats["failed_skus"][:8])
        if ok_count == 0:
            hint = format_wc_network_error(stats["last_error"]) if stats.get("last_error") else (
                "اتصال Woo آنلاین، VPN و تنظیمات API را بررسی کنید."
            )
            raise RuntimeError(
                f"هیچ محصولی به ووکامرس ارسال نشد ({fail_count} خطا).\n"
                f"SKU: {sku_list}\n\n{hint}"
            )
        raise RuntimeError(
            f"همگام‌سازی ناقص: {ok_count} موفق، {fail_count} ناموفق.\n"
            f"SKUهای خطادار: {sku_list}"
        )

    if ok_count == 0:
        log.warning("ℹ️ محصولی برای همگام‌سازی یافت نشد (گروه انتخابی یا تیک محصولات را بررسی کنید).")

    return stats


if __name__ == "__main__":
    main()
