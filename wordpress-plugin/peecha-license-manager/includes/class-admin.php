<?php

if (!defined('ABSPATH')) {
    exit;
}

class Peecha_LM_Admin
{
    const TD = 'peecha-license-manager';

    /** @var array<string, string> */
    private static $field_errors = array();

    public static function init()
    {
        add_action('admin_menu', array(__CLASS__, 'menu'));
        add_action('admin_init', array(__CLASS__, 'handle_actions'));
        add_action('admin_enqueue_scripts', array(__CLASS__, 'enqueue_assets'));
        add_action('admin_notices', array(__CLASS__, 'notice_wrong_folders'));
        add_action('admin_notices', array(__CLASS__, 'notice_plugin_version'));
    }

    public static function notice_plugin_version()
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        $screen = function_exists('get_current_screen') ? get_current_screen() : null;
        if (!$screen || !in_array($screen->id, array('plugins', 'toplevel_page_peecha-licenses'), true)) {
            return;
        }
        $count = count(Peecha_LM_DB::list_licenses(''));
        echo '<div class="notice notice-success is-dismissible"><p><strong>Peecha License Manager '
            . esc_html(PEECHA_LM_VERSION)
            . '</strong> — '
            . esc_html(self::t(
                $count . ' license(s) in database. Health: ',
                $count . ' لایسنس در پایگاه. سلامت: '
            ))
            . '<code>' . esc_html(rest_url('peecha/v1/health')) . '</code></p></div>';
    }

    public static function is_fa()
    {
        $locale = function_exists('get_user_locale') ? get_user_locale() : get_locale();
        return strpos((string) $locale, 'fa') === 0;
    }

    public static function vendor_ok()
    {
        $base = PEECHA_LM_PLUGIN_DIR . 'assets/vendor/';
        return is_file($base . 'persian-date.min.js')
            && is_file($base . 'persian-datepicker.min.js')
            && is_file($base . 'persian-datepicker.min.css');
    }

    public static function enqueue_assets($hook)
    {
        if (strpos((string) $hook, 'peecha-licenses') === false) {
            return;
        }

        wp_enqueue_style(
            'peecha-lm-admin',
            plugins_url('assets/css/admin.css', PEECHA_LM_PLUGIN_FILE),
            array(),
            PEECHA_LM_VERSION
        );

        $use_jalali = self::is_fa() && self::vendor_ok();
        if (self::is_fa() && !self::vendor_ok()) {
            add_action('admin_notices', array(__CLASS__, 'notice_missing_vendor'));
        }
        if (self::is_fa()) {
            wp_enqueue_script(
                'persian-date',
                plugins_url('assets/vendor/persian-date.min.js', PEECHA_LM_PLUGIN_FILE),
                array('jquery'),
                '1.1.0',
                true
            );
        }
        if ($use_jalali) {
            wp_enqueue_style(
                'persian-datepicker',
                plugins_url('assets/vendor/persian-datepicker.min.css', PEECHA_LM_PLUGIN_FILE),
                array(),
                '1.2.0'
            );
            wp_enqueue_script(
                'persian-datepicker',
                plugins_url('assets/vendor/persian-datepicker.min.js', PEECHA_LM_PLUGIN_FILE),
                array('jquery', 'persian-date'),
                '1.2.0',
                true
            );
        }

        $admin_deps = array('jquery');
        if (self::is_fa()) {
            $admin_deps[] = 'persian-date';
        }
        if ($use_jalali) {
            $admin_deps[] = 'persian-datepicker';
        }

        wp_enqueue_script(
            'peecha-lm-admin',
            plugins_url('assets/js/admin.js', PEECHA_LM_PLUGIN_FILE),
            $admin_deps,
            PEECHA_LM_VERSION,
            true
        );
        wp_localize_script('peecha-lm-admin', 'peechaLmAdmin', array(
            'isFa' => self::is_fa(),
            'jalaliReady' => $use_jalali,
            'copyLabel' => self::t('Copy', 'کپی'),
            'copiedLabel' => self::t('Copied', 'کپی شد'),
            'copyFailed' => self::t(
                'Copy failed — select the key and press Ctrl+C.',
                'کپی نشد — متن را انتخاب کنید و Ctrl+C بزنید.'
            ),
            'datepickerMissing' => self::t(
                'Datepicker files missing. Upload assets/vendor/ from the plugin package.',
                'فایل‌های تقویم نیست. پوشه assets/vendor/ را از بسته افزونه آپلود کنید.'
            ),
            'datePlaceholder' => self::t('1404/03/25', '1404/03/25'),
            'dateRequired' => self::t('Required. Example: 1404/03/25', 'الزامی است. مثال: 1404/03/25'),
            'dateInvalid' => self::t('Invalid format. Example: 1404/03/25', 'فرمت اشتباه است. مثال: 1404/03/25'),
        ));
    }

    public static function notice_wrong_folders()
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        $screen = function_exists('get_current_screen') ? get_current_screen() : null;
        if (!$screen || !in_array($screen->id, array('plugins', 'toplevel_page_peecha-licenses'), true)) {
            return;
        }
        $wrong = Peecha_LM_Updater::wrong_plugin_folders();
        if (!$wrong) {
            return;
        }
        $names = array();
        foreach ($wrong as $path) {
            $names[] = basename($path);
        }
        echo '<div class="notice notice-warning"><p>' . esc_html(self::t(
            'Wrong plugin folder(s) found: ' . implode(', ', $names) . '. Delete them in File Manager. Keep only peecha-license-manager.',
            'پوشه اشتباه افزونه پیدا شد: ' . implode('، ', $names) . '. از File Manager حذفش کن. فقط peecha-license-manager بماند.'
        )) . '</p></div>';
    }

    public static function notice_missing_vendor()
    {
        $screen = function_exists('get_current_screen') ? get_current_screen() : null;
        if (!$screen || strpos((string) $screen->id, 'peecha-licenses') === false) {
            return;
        }
        echo '<div class="notice notice-error"><p>' . esc_html(self::t(
            'Jalali datepicker files are missing in assets/vendor/. Re-upload them via File Manager.',
            'فایل‌های تقویم شمسی در assets/vendor/ نیست. دوباره از لپ‌تاپ آپلود کنید.'
        )) . '</p></div>';
    }

    public static function hint($en, $fa)
    {
        echo '<p class="description">' . esc_html(self::t($en, $fa)) . '</p>';
    }

    public static function set_field_error($field, $message)
    {
        self::$field_errors[sanitize_key((string) $field)] = (string) $message;
    }

    public static function field_error($field)
    {
        $key = sanitize_key((string) $field);
        return self::$field_errors[$key] ?? '';
    }

    public static function render_settings_notices()
    {
        $errors = get_settings_errors('peecha_lm');
        if (!$errors) {
            return;
        }
        foreach ($errors as $err) {
            if (($err['code'] ?? '') === 'bad_date') {
                continue;
            }
            $type = 'notice-info';
            if (($err['type'] ?? '') === 'error') {
                $type = 'notice-error';
            } elseif (($err['type'] ?? '') === 'updated' || ($err['type'] ?? '') === 'success') {
                $type = 'notice-success';
            }
            echo '<div class="notice ' . esc_attr($type) . ' is-dismissible"><p>' . esc_html($err['message'] ?? '') . '</p></div>';
        }
    }

    public static function render_date_field($name, $value, $required = false)
    {
        if (self::field_error($name) && isset($_POST[$name])) {
            $value = sanitize_text_field((string) $_POST[$name]);
        }
        $value = esc_attr((string) $value);
        $req = $required ? ' required' : '';
        $inline_err = self::field_error($name);
        $has_err = $inline_err !== '';
        if (self::is_fa()) {
            $field_id = 'peecha_jalali_' . sanitize_key($name);
            $placeholder = self::t('1404/03/25', '1404/03/25');
            $use_jalali = self::vendor_ok();
            $err_id = esc_attr($field_id . '_error');
            ?>
            <div class="peecha-jalali-wrap<?php echo $has_err ? ' peecha-jalali-wrap--invalid' : ''; ?>"
                data-jalali-picker="<?php echo $use_jalali ? '1' : '0'; ?>"
                data-required="<?php echo $required ? '1' : '0'; ?>"
                data-field="<?php echo esc_attr($name); ?>">
                <div class="peecha-jalali-row">
                    <input type="text"
                        id="<?php echo esc_attr($field_id); ?>_display"
                        class="peecha-jalali-display regular-text<?php echo $has_err ? ' peecha-jalali-invalid' : ''; ?>"
                        dir="ltr"
                        inputmode="numeric"
                        placeholder="<?php echo esc_attr($placeholder); ?>"
                        autocomplete="off"
                        aria-invalid="<?php echo $has_err ? 'true' : 'false'; ?>"
                        <?php if ($has_err) : ?>aria-describedby="<?php echo $err_id; ?>"<?php endif; ?>
                        pattern="[0-9۰-۹]{4}[/\-][0-9۰-۹]{1,2}[/\-][0-9۰-۹]{1,2}" />
                <?php if ($use_jalali) : ?>
                    <button type="button" class="button peecha-jalali-open" title="<?php echo esc_attr(self::t('Open calendar', 'باز کردن تقویم')); ?>">
                        <span class="dashicons dashicons-calendar-alt"></span>
                    </button>
                <?php endif; ?>
                </div>
                <input type="hidden"
                    id="<?php echo esc_attr($field_id); ?>_value"
                    name="<?php echo esc_attr($name); ?>"
                    class="peecha-jalali-value"
                    value="<?php echo $value; ?>"<?php echo $req; ?> />
                <p id="<?php echo $err_id; ?>" class="peecha-jalali-error" role="alert"<?php echo $has_err ? '' : ' style="display:none;"'; ?>><?php echo esc_html($inline_err); ?></p>
            </div>
            <?php
            self::hint(
                'Jalali YYYY/MM/DD — type manually or use the calendar button.',
                'تاریخ شمسی YYYY/MM/DD — دستی تایپ کنید یا دکمه تقویم را بزنید.'
            );
            return;
        }
        ?>
        <input type="date" name="<?php echo esc_attr($name); ?>" value="<?php echo $value; ?>" class="regular-text"<?php echo $req; ?> />
        <?php
    }

    /** fa_IR admin -> Persian, otherwise English */
    public static function t($en, $fa)
    {
        $locale = function_exists('get_user_locale') ? get_user_locale() : get_locale();
        if (strpos((string) $locale, 'fa') === 0) {
            return $fa;
        }
        return $en;
    }

    public static function status_label($status)
    {
        $labels = array(
            'active' => self::t('Active', 'فعال'),
            'revoked' => self::t('Revoked', 'باطل شده'),
        );
        return $labels[$status] ?? $status;
    }

    public static function menu()
    {
        $title = self::t('Peecha Licenses', 'لایسنس‌های پیچا');
        add_menu_page(
            $title,
            $title,
            'manage_options',
            'peecha-licenses',
            array(__CLASS__, 'render_page'),
            'dashicons-admin-network',
            58
        );
    }

    public static function handle_actions()
    {
        if (!is_admin() || !current_user_can('manage_options')) {
            return;
        }
        if (empty($_GET['page']) || $_GET['page'] !== 'peecha-licenses') {
            return;
        }
        if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
            return;
        }

        check_admin_referer('peecha_lm_action');

        $action = sanitize_text_field((string) ($_POST['peecha_action'] ?? ''));

        if ($action === 'save_settings') {
            update_option('peecha_lm_api_key', sanitize_text_field((string) ($_POST['api_key'] ?? '')));
            update_option('peecha_lm_hmac_secret', sanitize_text_field((string) ($_POST['hmac_secret'] ?? '')));
            update_option('peecha_lm_ed25519_private_key', sanitize_text_field((string) ($_POST['ed25519_private_key'] ?? '')));
            $github_repo = Peecha_LM_Update::normalize_repo((string) ($_POST['github_repo'] ?? ''));
            if ($github_repo === '' && defined('PEECHA_LM_DEFAULT_GITHUB_REPO')) {
                $github_repo = PEECHA_LM_DEFAULT_GITHUB_REPO;
            }
            update_option('peecha_lm_github_repo', $github_repo);
            update_option('peecha_lm_github_token', sanitize_text_field((string) ($_POST['github_token'] ?? '')));
            update_option('peecha_lm_latest_version', sanitize_text_field((string) ($_POST['latest_version'] ?? '')));
            update_option('peecha_lm_changelog', sanitize_textarea_field((string) ($_POST['changelog'] ?? '')));
            update_option('peecha_lm_offline_grace_days', max(1, (int) ($_POST['offline_grace_days'] ?? 7)));
            $mirror_id = (int) ($_POST['mirror_attachment_id'] ?? 0);
            update_option('peecha_lm_mirror_attachment_id', $mirror_id);
            update_option('peecha_lm_mirror_path', sanitize_text_field((string) ($_POST['mirror_path'] ?? '')));
            add_settings_error('peecha_lm', 'settings_saved', self::t('Settings saved.', 'تنظیمات ذخیره شد.'), 'updated');
            return;
        }

        if ($action === 'upload_client_mirror') {
            if (empty($_FILES['client_zip']['tmp_name']) || !is_uploaded_file($_FILES['client_zip']['tmp_name'])) {
                add_settings_error('peecha_lm', 'client_zip_missing', self::t('Choose a ZIP file first.', 'اول فایل ZIP را انتخاب کن.'), 'error');
                return;
            }
            $name = basename((string) ($_FILES['client_zip']['name'] ?? ''));
            if (!preg_match('/\.zip$/i', $name)) {
                add_settings_error('peecha_lm', 'client_zip_bad', self::t('File must be .zip', 'فقط ZIP'), 'error');
                return;
            }

            $dir = Peecha_LM_Update::client_mirror_dir();
            if ($dir === '') {
                add_settings_error('peecha_lm', 'client_zip_dir', self::t('Cannot create uploads folder.', 'پوشه آپلود ساخته نشد.'), 'error');
                return;
            }

            $version = '';
            if (preg_match('/PeechaSync[-_]?v?(\d+\.\d+(?:\.\d+)?)/i', $name, $matches)) {
                $version = (string) $matches[1];
            }
            if ($version === '') {
                $version = sanitize_text_field((string) ($_POST['mirror_version'] ?? ''));
            }
            if ($version === '') {
                $version = trim((string) get_option('peecha_lm_latest_version', ''));
            }

            $dest_name = $version !== '' ? 'PeechaSync-' . $version . '.zip' : 'latest.zip';
            $dest = $dir . '/' . $dest_name;

            foreach (glob($dir . '/*.zip') ?: array() as $old) {
                if (is_file($old)) {
                    @unlink($old);
                }
            }

            if (!move_uploaded_file($_FILES['client_zip']['tmp_name'], $dest)) {
                add_settings_error('peecha_lm', 'client_zip_move', self::t('Upload failed.', 'آپلود ناموفق بود.'), 'error');
                return;
            }

            update_option('peecha_lm_mirror_filename', $dest_name);
            if ($version !== '') {
                update_option('peecha_lm_latest_version', $version);
            }

            $size_kb = (int) round(filesize($dest) / 1024);
            add_settings_error(
                'peecha_lm',
                'client_zip_ok',
                self::t(
                    "Desktop update saved: {$dest_name} ({$size_kb} KB).",
                    "آپدیت دسکتاپ ذخیره شد: {$dest_name} ({$size_kb} کیلوبایت)."
                ),
                'updated'
            );
            return;
        }

        if ($action === 'apply_plugin_zip') {
            if (empty($_FILES['update_zip']['tmp_name']) || !is_uploaded_file($_FILES['update_zip']['tmp_name'])) {
                add_settings_error('peecha_lm', 'zip_missing', self::t('Choose a ZIP file first.', 'اول فایل ZIP را انتخاب کن.'), 'error');
                return;
            }
            $name = (string) ($_FILES['update_zip']['name'] ?? '');
            if (!preg_match('/\.zip$/i', $name)) {
                add_settings_error('peecha_lm', 'zip_bad', self::t('File must be .zip', 'فقط ZIP'), 'error');
                return;
            }

            $result = Peecha_LM_Updater::apply_zip($_FILES['update_zip']['tmp_name'], PEECHA_LM_PLUGIN_DIR);
            if (is_wp_error($result)) {
                add_settings_error('peecha_lm', 'zip_failed', $result->get_error_message(), 'error');
                return;
            }

            $version = (string) ($result['version'] ?? PEECHA_LM_VERSION);
            add_settings_error(
                'peecha_lm',
                'zip_ok',
                self::t("Plugin updated to v{$version}.", "افزونه به نسخه {$version} به‌روز شد."),
                'updated'
            );
            return;
        }

        if ($action === 'create_license') {
            $hwid = sanitize_text_field((string) ($_POST['hwid'] ?? ''));
            $raw_expires = trim((string) ($_POST['license_expires'] ?? ''));
            $raw_updates = trim((string) ($_POST['updates_until'] ?? ''));
            $license_expires = Peecha_LM_License::normalize_date_input($raw_expires);
            $updates_until = Peecha_LM_License::normalize_date_input($raw_updates);

            if (!$license_expires) {
                $msg = $raw_expires === ''
                    ? self::t('Required. Example: 1404/03/25', 'الزامی است. مثال: 1404/03/25')
                    : self::t('Invalid format. Example: 1404/03/25', 'فرمت اشتباه است. مثال: 1404/03/25');
                self::set_field_error('license_expires', $msg);
                return;
            }
            if ($raw_updates !== '' && !$updates_until) {
                self::set_field_error('updates_until', self::t(
                    'Invalid format. Example: 1404/06/01',
                    'فرمت اشتباه است. مثال: 1404/06/01'
                ));
                return;
            }
            $updates_until = Peecha_LM_License::cap_updates_until($license_expires, $updates_until);
            $max_sites = Peecha_LM_License::normalize_max_sites($_POST['max_sites'] ?? 0);
            $platform_scope = Peecha_LM_License::normalize_platform_scope($_POST['platform_scope'] ?? 'both');

            if ($hwid !== '') {
                $license_key = Peecha_LM_License::generate_key($hwid, $license_expires, $updates_until, $max_sites, $platform_scope);
                if (is_wp_error($license_key)) {
                    add_settings_error('peecha_lm', 'license_sign_failed', $license_key->get_error_message(), 'error');
                    return;
                }
            } else {
                $license_key = 'PLM-' . strtoupper(wp_generate_password(20, false, false));
            }

            Peecha_LM_DB::insert_license(array(
                'license_key' => $license_key,
                'customer_name' => sanitize_text_field((string) ($_POST['customer_name'] ?? '')),
                'customer_email' => sanitize_email((string) ($_POST['customer_email'] ?? '')),
                'hwid' => $hwid !== '' ? $hwid : null,
                'status' => 'active',
                'license_expires' => $license_expires,
                'updates_until' => $updates_until ?: $license_expires,
                'notes' => sanitize_textarea_field((string) ($_POST['notes'] ?? '')),
                'max_sites' => $max_sites,
                'platform_scope' => $platform_scope,
            ));
            if ($hwid !== '') {
                Peecha_LM_DB::unblock_hwid($hwid);
            }
            add_settings_error('peecha_lm', 'license_created', self::t('License created.', 'لایسنس ساخته شد.'), 'updated');
            return;
        }

        if ($action === 'update_license') {
            $id = (int) ($_POST['license_id'] ?? 0);
            if ($id <= 0) {
                return;
            }

            $license_expires = Peecha_LM_License::normalize_date_input($_POST['license_expires'] ?? '');
            $updates_until = Peecha_LM_License::normalize_date_input($_POST['updates_until'] ?? '');
            if (!$license_expires) {
                self::set_field_error('license_expires', self::t(
                    'Invalid format. Example: 1404/03/25',
                    'فرمت اشتباه است. مثال: 1404/03/25'
                ));
                return;
            }
            if (!empty($_POST['updates_until']) && !$updates_until) {
                self::set_field_error('updates_until', self::t(
                    'Invalid format. Example: 1404/06/01',
                    'فرمت اشتباه است. مثال: 1404/06/01'
                ));
                return;
            }

            $new_hwid = sanitize_text_field((string) ($_POST['hwid'] ?? '')) ?: null;
            $new_status = sanitize_text_field((string) ($_POST['status'] ?? 'active'));
            Peecha_LM_DB::update_license($id, array(
                'customer_name' => sanitize_text_field((string) ($_POST['customer_name'] ?? '')),
                'customer_email' => sanitize_email((string) ($_POST['customer_email'] ?? '')),
                'hwid' => $new_hwid,
                'status' => $new_status,
                'license_expires' => $license_expires,
                'updates_until' => Peecha_LM_License::cap_updates_until($license_expires, $updates_until),
                'notes' => sanitize_textarea_field((string) ($_POST['notes'] ?? '')),
            ));
            if ($new_status === 'active') {
                $unblock_hwid = $new_hwid;
                if ($unblock_hwid === null || $unblock_hwid === '') {
                    $saved = Peecha_LM_DB::get_license($id);
                    $unblock_hwid = trim((string) ($saved['hwid'] ?? ''));
                }
                if ($unblock_hwid !== '') {
                    Peecha_LM_DB::unblock_hwid($unblock_hwid);
                }
            }
            add_settings_error('peecha_lm', 'license_updated', self::t('License updated.', 'لایسنس به‌روز شد.'), 'updated');
            return;
        }

        if ($action === 'revoke_license') {
            $id = (int) ($_POST['license_id'] ?? 0);
            $row = $id > 0 ? Peecha_LM_DB::get_license($id) : null;
            if ($row) {
                Peecha_LM_DB::update_license($id, array('status' => 'revoked'));
                add_settings_error('peecha_lm', 'license_revoked', self::t('License revoked.', 'لایسنس باطل شد.'), 'updated');
            }
            return;
        }

        if ($action === 'delete_license') {
            $id = (int) ($_POST['license_id'] ?? 0);
            $row = $id > 0 ? Peecha_LM_DB::get_license($id) : null;
            if ($row) {
                if (($row['status'] ?? '') !== 'revoked') {
                    add_settings_error('peecha_lm', 'delete_active', self::t(
                        'Revoke the license first, then delete it from the list.',
                        'اول لایسنس را باطل کنید، بعد از لیست حذفش کنید.'
                    ), 'error');
                    return;
                }
                $hwid = trim((string) ($row['hwid'] ?? ''));
                if ($hwid !== '') {
                    Peecha_LM_DB::block_hwid($hwid);
                }
                Peecha_LM_DB::delete_license($id);
                add_settings_error('peecha_lm', 'license_deleted', self::t('License removed from list.', 'لایسنس از لیست حذف شد.'), 'updated');
            }
            return;
        }

        if ($action === 'import_signed_license') {
            $raw_key = (string) ($_POST['import_license_key'] ?? '');
            $raw_key = preg_replace('/[\r\n\t\0]/', '', trim($raw_key));
            $hwid = sanitize_text_field((string) ($_POST['import_hwid'] ?? ''));
            if ($raw_key === '') {
                add_settings_error('peecha_lm', 'import_empty', self::t('Paste the signed license key.', 'کلید امضا‌شده را بچسبانید.'), 'error');
                return;
            }
            $result = Peecha_LM_License::import_signed_key($raw_key, $hwid);
            if (is_wp_error($result)) {
                add_settings_error('peecha_lm', 'import_failed', $result->get_error_message(), 'error');
                return;
            }
            $shown_hwid = (string) ($result['hwid'] ?? $hwid);
            if ($shown_hwid !== '') {
                Peecha_LM_DB::unblock_hwid($shown_hwid);
            }
            add_settings_error(
                'peecha_lm',
                'import_ok',
                self::t(
                    'License imported. HWID: ' . $shown_hwid,
                    'لایسنس وارد شد. HWID: ' . $shown_hwid
                ),
                'updated'
            );
            return;
        }

        if ($action === 'regenerate_key') {
            $id = (int) ($_POST['license_id'] ?? 0);
            $row = Peecha_LM_DB::get_license($id);
            if (!$row) {
                return;
            }
            $hwid = sanitize_text_field((string) ($row['hwid'] ?? ''));
            if ($hwid === '') {
                add_settings_error('peecha_lm', 'no_hwid', self::t('Set HWID before regenerating signed key.', 'قبل از ساخت کلید، HWID را ثبت کنید.'), 'error');
                return;
            }
            $new_key = Peecha_LM_License::generate_key(
                $hwid,
                $row['license_expires'],
                $row['updates_until'],
                (int) ($row['max_sites'] ?? 0),
                (string) ($row['platform_scope'] ?? 'both')
            );
            if (is_wp_error($new_key)) {
                add_settings_error('peecha_lm', 'license_sign_failed', $new_key->get_error_message(), 'error');
                return;
            }
            Peecha_LM_DB::update_license($id, array('license_key' => $new_key));
            add_settings_error('peecha_lm', 'key_regenerated', self::t('License key regenerated.', 'کلید لایسنس دوباره ساخته شد.'), 'updated');
        }
    }

    public static function render_page()
    {
        if (!current_user_can('manage_options')) {
            return;
        }

        Peecha_LM_Update::sync_latest_version_from_mirror();

        $search = sanitize_text_field((string) ($_GET['s'] ?? ''));
        $licenses = Peecha_LM_DB::list_licenses($search);
        $all_count = count(Peecha_LM_DB::list_licenses(''));
        $edit_id = (int) ($_GET['edit'] ?? 0);
        $edit_row = $edit_id > 0 ? Peecha_LM_DB::get_license($edit_id) : null;

        self::render_settings_notices();
        ?>
        <div class="wrap peecha-lm-wrap">
            <div class="peecha-lm-hero">
                <h1><?php echo esc_html(self::t('Peecha License Manager', 'مدیریت لایسنس پیچا')); ?></h1>
                <p style="margin:12px 0;">
                    <span style="display:inline-block;background:#15803d;color:#fff;font-weight:700;padding:6px 14px;border-radius:6px;font-size:15px;">
                        <?php echo esc_html(self::t('Plugin', 'افزونه')); ?> <?php echo esc_html(PEECHA_LM_VERSION); ?>
                    </span>
                    <span style="margin-right:10px;color:#334155;">
                        <?php echo esc_html(self::t(
                            $all_count . ' license(s) registered',
                            $all_count . ' لایسنس ثبت‌شده'
                        )); ?>
                    </span>
                </p>
                <p>
                    <?php echo esc_html(self::t('REST base:', 'آدرس پایه REST:')); ?>
                    <code><?php echo esc_html(rest_url('peecha/v1/')); ?></code>
                </p>
                <?php if (version_compare(PEECHA_LM_VERSION, '1.0.29', '>=')) : ?>
                    <p class="description" style="color:#15803d;font-weight:600;">
                        <?php echo esc_html(self::t(
                            'Auto-import: clients with old signed keys appear in the list after first online connect.',
                            'ثبت خودکار: لایسنس‌های قدیمی بعد از اولین اتصال آنلاین کلاینت در لیست می‌آیند.'
                        )); ?>
                    </p>
                <?php endif; ?>
            </div>

            <div class="peecha-lm-card">
                <h2><?php echo esc_html(self::t('Settings', 'تنظیمات')); ?></h2>
                <form method="post">
                    <?php wp_nonce_field('peecha_lm_action'); ?>
                    <input type="hidden" name="peecha_action" value="save_settings" />
                    <div class="peecha-lm-grid">
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label for="api_key"><?php echo esc_html(self::t('API Key', 'کلید API')); ?></label>
                            <div class="peecha-lm-search">
                                <input name="api_key" id="api_key" class="regular-text" value="<?php echo esc_attr(get_option('peecha_lm_api_key', '')); ?>" />
                                <button type="button" class="button" id="peecha-copy-api-key" data-default-label="<?php echo esc_attr(self::t('Copy', 'کپی')); ?>" data-copied-label="<?php echo esc_attr(self::t('Copied', 'کپی شد')); ?>"><?php echo esc_html(self::t('Copy', 'کپی')); ?></button>
                            </div>
                            <p class="description"><?php echo esc_html(self::t('Put the same key in PeechaSync Settings -> License API Key.', 'همین کلید را در PeechaSync -> تنظیمات -> کلید API لایسنس بگذارید.')); ?></p>
                        </div>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label for="ed25519_private_key"><?php echo esc_html(self::t('Ed25519 Private Key (v3 signing)', 'کلید خصوصی Ed25519 (امضای نسخه ۳)')); ?></label>
                            <input name="ed25519_private_key" id="ed25519_private_key" class="regular-text" autocomplete="off" value="<?php echo esc_attr(get_option('peecha_lm_ed25519_private_key', '')); ?>" />
                            <?php self::hint(
                                'SECRET — used only here to sign new licenses. Never share, never commit to git. Generate once and paste the 32-byte base64 seed.',
                                'محرمانه — فقط همین‌جا برای امضای لایسنس‌های جدید استفاده می‌شود. هیچ‌جا به‌اشتراک نگذارید و در گیت قرار ندهید. یک‌بار تولید و مقدارِ base64 سیدِ ۳۲بایتی را این‌جا جای‌گذاری کنید.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label><?php echo esc_html(self::t('HMAC Secret (legacy v2 — retired)', 'کلید HMAC (نسخه‌ی قدیمیِ ۲ — بازنشسته)')); ?></label>
                            <input name="hmac_secret" id="hmac_secret" class="regular-text" value="<?php echo esc_attr(get_option('peecha_lm_hmac_secret', '')); ?>" readonly />
                            <?php self::hint(
                                'No longer used to verify licenses (this key leaked in the public repo history). Kept only for historical reference.',
                                'دیگر برای تأییدِ لایسنس استفاده نمی‌شود (این کلید در تاریخچه‌ی مخزنِ عمومی لو رفته بود). فقط برای مرجعِ تاریخی نگه داشته شده.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label for="github_repo"><?php echo esc_html(self::t('GitHub repo', 'ریپوی GitHub')); ?></label>
                            <input name="github_repo" id="github_repo" class="regular-text" value="<?php echo esc_attr(Peecha_LM_Update::github_repo() ?: (defined('PEECHA_LM_DEFAULT_GITHUB_REPO') ? PEECHA_LM_DEFAULT_GITHUB_REPO : 'peecha-peetar/PeechaSync')); ?>" />
                            <?php self::hint(
                                'Repo for updates (owner/name). Server downloads latest release ZIP from here.',
                                'مسیر ریپو برای بروزرسانی (owner/name). سرور آخرین ZIP ریلیز را از همینجا می‌گیرد.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label for="github_token"><?php echo esc_html(self::t('GitHub token', 'توکن GitHub')); ?></label>
                            <input name="github_token" id="github_token" type="password" class="regular-text" value="<?php echo esc_attr(get_option('peecha_lm_github_token', '')); ?>" autocomplete="off" />
                            <?php self::hint(
                                'Personal access token for private repos or higher API limits. Stored on this server only.',
                                'توکن دسترسی GitHub برای ریپوی خصوصی یا محدودیت API. فقط روی همین سرور ذخیره می‌شود.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label for="latest_version"><?php echo esc_html(self::t('Latest app version', 'آخرین نسخه برنامه')); ?></label>
                            <?php
                            $mirror_version = Peecha_LM_Update::newest_mirror_version();
                            $saved_version = get_option('peecha_lm_latest_version', '');
                            ?>
                            <input name="latest_version" id="latest_version" class="regular-text" value="<?php echo esc_attr($saved_version); ?>" />
                            <?php if ($mirror_version !== '') : ?>
                                <p class="description">
                                    <?php echo esc_html(self::t(
                                        'Auto from mirror ZIP: ' . $mirror_version,
                                        'از روی ZIP آینه: ' . $mirror_version
                                    )); ?>
                                </p>
                            <?php endif; ?>
                            <?php self::hint(
                                'Synced from PeechaSync-*.zip on the server when you deploy. Manual edit only if needed.',
                                'با آپلود ZIP روی سرور خودکار پر می‌شود. فقط در صورت نیاز دستی عوض کنید.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label for="mirror_path"><?php echo esc_html(self::t('Local mirror path (optional)', 'مسیر ZIP روی سرور (اختیاری)')); ?></label>
                            <input name="mirror_path" id="mirror_path" class="large-text" value="<?php echo esc_attr(get_option('peecha_lm_mirror_path', '')); ?>" placeholder="<?php echo esc_attr(self::t('e.g. peecha-sync-updates/latest.zip or full path from DirectAdmin', 'مثلا peecha-sync-updates/latest.zip یا مسیر کامل از File Manager')); ?>" />
                            <?php self::hint(
                                'Fallback when GitHub is blocked. Relative to site root or absolute path. Checked before media attachment ID.',
                                'وقتی GitHub در دسترس نیست. نسبت به ریشه سایت یا مسیر کامل. قبل از شناسه مدیا بررسی می‌شود.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label for="mirror_attachment_id"><?php echo esc_html(self::t('Mirror ZIP attachment ID', 'شناسه ZIP آینه (مدیا)')); ?></label>
                            <input name="mirror_attachment_id" id="mirror_attachment_id" type="number" value="<?php echo esc_attr((string) get_option('peecha_lm_mirror_attachment_id', 0)); ?>" />
                            <?php self::hint(
                                'Legacy fallback. Prefer upload below or mirror path.',
                                'روش قدیمی. بهتر است از آپلود پایین یا مسیر سرور استفاده کنید.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label for="offline_grace_days"><?php echo esc_html(self::t('Offline grace days', 'روزهای مجاز آفلاین')); ?></label>
                            <input name="offline_grace_days" id="offline_grace_days" type="number" min="1" value="<?php echo esc_attr((string) get_option('peecha_lm_offline_grace_days', 7)); ?>" />
                            <?php self::hint(
                                'How many days PeechaSync works without server check after last OK validation.',
                                'اگر مشتری چند روز به سرور وصل نشود، برنامه با آخرین تأیید معتبر کار می‌کند. مثلا ۷ یعنی یک هفته آفلاین.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label for="changelog"><?php echo esc_html(self::t('Changelog', 'تغییرات نسخه')); ?></label>
                            <textarea name="changelog" id="changelog" rows="4"><?php echo esc_textarea(get_option('peecha_lm_changelog', '')); ?></textarea>
                            <?php self::hint(
                                'Shown in PeechaSync update dialog.',
                                'متن تغییرات نسخه جدید — در پنجره بروزرسانی برنامه نشان داده می‌شود.'
                            ); ?>
                        </div>
                    </div>
                    <div class="peecha-lm-actions">
                        <?php submit_button(self::t('Save settings', 'ذخیره تنظیمات'), 'primary', 'submit', false); ?>
                    </div>
                </form>
            </div>

            <div class="peecha-lm-card">
                <h2><?php echo esc_html(self::t('Desktop app update mirror', 'آینه بروزرسانی PeechaSync')); ?></h2>
                <p><?php echo esc_html(self::t(
                    'Upload the client ZIP here so customers download from peecha.ir when GitHub is slow or blocked. The app never talks to GitHub directly.',
                    'ZIP کلاینت را اینجا بگذارید تا مشتری از peecha.ir دانلود کند وقتی GitHub کند یا قطع است. برنامه مستقیم به GitHub وصل نمی‌شود.'
                )); ?></p>
                <?php
                $mirror_dir = Peecha_LM_Update::client_mirror_dir();
                if ($mirror_dir !== '') :
                    ?>
                    <p class="description"><?php echo esc_html(self::t(
                        'Server folder (DirectAdmin / File Manager) — NOT inside plugins:',
                        'پوشه روی سرور (DirectAdmin) — داخل plugins نیست:'
                    )); ?>
                        <code><?php echo esc_html($mirror_dir); ?></code></p>
                <?php endif; ?>
                <?php
                $mirror_file = Peecha_LM_Update::mirror_path();
                if ($mirror_file !== '') :
                    $mirror_kb = (int) round(filesize($mirror_file) / 1024);
                    ?>
                    <p><strong><?php echo esc_html(self::t('Active mirror:', 'آینه فعال:')); ?></strong>
                        <code><?php echo esc_html($mirror_file); ?></code>
                        (<?php echo esc_html((string) $mirror_kb); ?> KB)</p>
                <?php else : ?>
                    <p><?php echo esc_html(self::t('No local mirror yet — download will try GitHub from the server.', 'هنوز ZIP روی سرور نیست — دانلود از GitHub روی سرور امتحان می‌شود.')); ?></p>
                <?php endif; ?>
                <form method="post" enctype="multipart/form-data">
                    <?php wp_nonce_field('peecha_lm_action'); ?>
                    <input type="hidden" name="peecha_action" value="upload_client_mirror" />
                    <div class="peecha-lm-grid">
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label for="client_zip"><?php echo esc_html(self::t('PeechaSync ZIP', 'فایل ZIP کلاینت')); ?></label>
                            <input type="file" name="client_zip" id="client_zip" accept=".zip,application/zip" required />
                            <?php self::hint(
                                'Name like PeechaSync-1.0.30.zip — version is read from the filename.',
                                'نام مثل PeechaSync-1.0.30.zip — نسخه از نام فایل خوانده می‌شود.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label for="mirror_version"><?php echo esc_html(self::t('Version override', 'نسخه (اختیاری)')); ?></label>
                            <input name="mirror_version" id="mirror_version" class="regular-text" placeholder="1.0.30" />
                            <?php self::hint(
                                'Only if the ZIP name has no version.',
                                'فقط وقتی نام ZIP نسخه ندارد.'
                            ); ?>
                        </div>
                    </div>
                    <div class="peecha-lm-actions">
                        <?php submit_button(self::t('Upload mirror', 'آپلود آینه'), 'primary', 'submit', false); ?>
                    </div>
                </form>
                <p class="description"><?php echo esc_html(self::t(
                    'DirectAdmin: you can also upload to public_html/peecha-sync-updates/latest.zip and set the path above.',
                    'DirectAdmin: می‌توانید در public_html/peecha-sync-updates/latest.zip بگذارید و مسیر را در تنظیمات بالا وارد کنید.'
                )); ?></p>
            </div>

            <div class="peecha-lm-card">
                <h2><?php echo esc_html(self::t('Update plugin', 'بروزرسانی افزونه')); ?></h2>
                <p><?php echo esc_html(self::t(
                    'Use this when wp-admin says it cannot delete the old plugin. Upload update.zip from tools/wp-license-deploy/.',
                    'وقتی wp-admin می‌گوید افزونه قدیمی پاک نمی‌شود، از اینجا update.zip را آپلود کن (از tools/wp-license-deploy/).'
                )); ?></p>
                <form method="post" enctype="multipart/form-data">
                    <?php wp_nonce_field('peecha_lm_action'); ?>
                    <input type="hidden" name="peecha_action" value="apply_plugin_zip" />
                    <div class="peecha-lm-field peecha-lm-field--full">
                        <label for="update_zip"><?php echo esc_html(self::t('Update ZIP', 'فایل ZIP')); ?></label>
                        <input type="file" name="update_zip" id="update_zip" accept=".zip,application/zip" required />
                        <?php self::hint(
                            'Works with update.zip or peecha-license-manager.zip. No need to deactivate or delete the plugin.',
                            'update.zip یا peecha-license-manager.zip — بدون غیرفعال کردن یا حذف افزونه.'
                        ); ?>
                    </div>
                    <div class="peecha-lm-actions">
                        <?php submit_button(self::t('Apply update', 'اعمال بروزرسانی'), 'primary', 'submit', false); ?>
                    </div>
                </form>
            </div>

            <div class="peecha-lm-card">
                <h2><?php echo esc_html($edit_row ? self::t('Edit license', 'ویرایش لایسنس') : self::t('New license', 'لایسنس جدید')); ?></h2>
                <form method="post">
                    <?php wp_nonce_field('peecha_lm_action'); ?>
                    <input type="hidden" name="peecha_action" value="<?php echo $edit_row ? 'update_license' : 'create_license'; ?>" />
                    <?php if ($edit_row) : ?>
                        <input type="hidden" name="license_id" value="<?php echo esc_attr((string) $edit_row['id']); ?>" />
                    <?php endif; ?>
                    <div class="peecha-lm-grid">
                        <div class="peecha-lm-field">
                            <label><?php echo esc_html(self::t('Customer name', 'نام مشتری')); ?></label>
                            <input name="customer_name" class="regular-text" value="<?php echo esc_attr($edit_row['customer_name'] ?? ''); ?>" />
                            <?php self::hint(
                                'Display name for your records.',
                                'نام مشتری برای پیگیری در پنل.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label><?php echo esc_html(self::t('Customer email', 'ایمیل مشتری')); ?></label>
                            <input name="customer_email" type="email" class="regular-text" value="<?php echo esc_attr($edit_row['customer_email'] ?? ''); ?>" />
                            <?php self::hint(
                                'Optional contact email.',
                                'ایمیل مشتری — اختیاری ولی برای پیگیری مفید است.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label><?php echo esc_html(self::t('HWID', 'شناسه دستگاه (HWID)')); ?></label>
                            <input name="hwid" class="regular-text" value="<?php echo esc_attr($edit_row['hwid'] ?? ''); ?>" placeholder="<?php echo esc_attr(self::t('Optional on create', 'اختیاری هنگام ساخت')); ?>" />
                            <p class="description"><?php echo esc_html(self::t('Leave empty to bind on first activation from PeechaSync.', 'خالی بگذارید تا مشتری از برنامه اولین بار فعال کند.')); ?></p>
                        </div>
                        <div class="peecha-lm-field">
                            <label><?php echo esc_html(self::t('Status', 'وضعیت')); ?></label>
                            <select name="status">
                                <?php foreach (array('active', 'revoked') as $status) : ?>
                                    <option value="<?php echo esc_attr($status); ?>" <?php selected(($edit_row['status'] ?? 'active'), $status); ?>><?php echo esc_html(self::status_label($status)); ?></option>
                                <?php endforeach; ?>
                            </select>
                            <?php self::hint(
                                'Active = allowed. Revoked = blocked immediately.',
                                'فعال = مجاز؛ لغو شده = دسترسی فورا قطع می‌شود.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label><?php echo esc_html(self::t('License expires', 'تاریخ انقضای لایسنس')); ?></label>
                            <?php self::render_date_field('license_expires', $edit_row['license_expires'] ?? '', true); ?>
                            <?php self::hint(
                                'After this date the app will not run.',
                                'بعد از این تاریخ برنامه باز نمی‌شود.'
                            ); ?>
                        </div>
                        <div class="peecha-lm-field">
                            <label><?php echo esc_html(self::t('Updates until', 'بروزرسانی تا')); ?></label>
                            <?php self::render_date_field('updates_until', $edit_row['updates_until'] ?? '', false); ?>
                            <?php self::hint(
                                'Updates allowed until this date (cannot exceed license expiry).',
                                'بروزرسانی تا این تاریخ مجاز است. نمی‌تواند از تاریخ انقضای لایسنس بیشتر باشد.'
                            ); ?>
                        </div>
                        <?php if (!$edit_row) : ?>
                            <div class="peecha-lm-field">
                                <label><?php echo esc_html(self::t('Sites allowed', 'تعداد سایت مجاز')); ?></label>
                                <select name="max_sites">
                                    <option value="1"><?php echo esc_html(self::t('Single site', 'تک‌سایتی')); ?></option>
                                    <option value="0"><?php echo esc_html(self::t('Unlimited sites', 'چندسایتی (نامحدود)')); ?></option>
                                </select>
                                <?php self::hint(
                                    'Single-site: license locks to the first store URL the app connects to. Unlimited: no site limit.',
                                    'تک‌سایتی: لایسنس با اولین آدرسِ فروشگاهی که برنامه به آن وصل شود قفل می‌شود. نامحدود: هیچ محدودیتی روی تعداد سایت نیست.'
                                ); ?>
                            </div>
                            <div class="peecha-lm-field">
                                <label><?php echo esc_html(self::t('Platform', 'پلتفرم')); ?></label>
                                <select name="platform_scope">
                                    <option value="both"><?php echo esc_html(self::t('WooCommerce + PrestaShop', 'ووکامرس + پرستاشاپ')); ?></option>
                                    <option value="wc"><?php echo esc_html(self::t('WooCommerce only', 'فقط ووکامرس')); ?></option>
                                    <option value="ps"><?php echo esc_html(self::t('PrestaShop only', 'فقط پرستاشاپ')); ?></option>
                                </select>
                                <?php self::hint(
                                    'Which store platform(s) this license may be used with.',
                                    'این لایسنس روی کدام پلتفرمِ فروشگاهی قابلِ استفاده باشد.'
                                ); ?>
                            </div>
                        <?php else : ?>
                            <div class="peecha-lm-field peecha-lm-field--full">
                                <label><?php echo esc_html(self::t('Sites / Platform scope', 'محدودیتِ سایت / پلتفرم')); ?></label>
                                <p class="description">
                                    <?php
                                    $scope_sites = ((int) ($edit_row['max_sites'] ?? 0)) > 0
                                        ? self::t('Single site', 'تک‌سایتی')
                                        : self::t('Unlimited sites', 'چندسایتی (نامحدود)');
                                    $scope_platform_map = array(
                                        'wc' => self::t('WooCommerce only', 'فقط ووکامرس'),
                                        'ps' => self::t('PrestaShop only', 'فقط پرستاشاپ'),
                                        'both' => self::t('WooCommerce + PrestaShop', 'ووکامرس + پرستاشاپ'),
                                    );
                                    $scope_platform = $scope_platform_map[$edit_row['platform_scope'] ?? 'both'] ?? $scope_platform_map['both'];
                                    echo esc_html($scope_sites . ' — ' . $scope_platform);
                                    ?>
                                </p>
                                <?php self::hint(
                                    'Baked into the signed key at creation — cannot be changed by editing. Issue a new license to change it.',
                                    'این مقدار داخلِ کلیدِ امضاشده در لحظه‌ی ساخت ثبت شده — با ویرایش تغییر نمی‌کند؛ برای تغییرش باید لایسنسِ جدید صادر شود.'
                                ); ?>
                            </div>
                        <?php endif; ?>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label><?php echo esc_html(self::t('Notes', 'یادداشت')); ?></label>
                            <textarea name="notes" rows="3"><?php echo esc_textarea($edit_row['notes'] ?? ''); ?></textarea>
                            <?php self::hint(
                                'Internal note — not shown to customer.',
                                'یادداشت داخلی برای خودتان — به مشتری نشان داده نمی‌شود.'
                            ); ?>
                        </div>
                        <?php if ($edit_row) : ?>
                            <div class="peecha-lm-field peecha-lm-field--full">
                                <label><?php echo esc_html(self::t('Website', 'وب‌سایت مشتری')); ?></label>
                                <?php $edit_site = trim((string) ($edit_row['site_url'] ?? '')); ?>
                                <?php if ($edit_site !== '') : ?>
                                    <p><a href="<?php echo esc_url($edit_site); ?>" target="_blank" rel="noopener"><?php echo esc_html($edit_site); ?></a></p>
                                <?php else : ?>
                                    <p class="description"><?php echo esc_html(self::t('Filled when client connects with WooCommerce URL in settings.', 'با اتصال کلاینت و آدرس ووکامرس در تنظیمات پر می‌شود.')); ?></p>
                                <?php endif; ?>
                            </div>
                            <div class="peecha-lm-field peecha-lm-field--full">
                                <label><?php echo esc_html(self::t('License key', 'کلید لایسنس')); ?></label>
                                <div class="peecha-lm-key-box"><?php echo esc_html($edit_row['license_key']); ?></div>
                            </div>
                        <?php endif; ?>
                    </div>
                    <div class="peecha-lm-actions">
                        <?php submit_button($edit_row ? self::t('Update license', 'به‌روزرسانی لایسنس') : self::t('Create license', 'ساخت لایسنس'), 'primary', 'submit', false); ?>
                    </div>
                </form>
                <?php if ($edit_row && !empty($edit_row['hwid'])) : ?>
                    <form method="post" class="peecha-lm-actions">
                        <?php wp_nonce_field('peecha_lm_action'); ?>
                        <input type="hidden" name="peecha_action" value="regenerate_key" />
                        <input type="hidden" name="license_id" value="<?php echo esc_attr((string) $edit_row['id']); ?>" />
                        <?php submit_button(self::t('Regenerate signed key', 'ساخت مجدد کلید امضا‌شده'), 'secondary', 'submit', false); ?>
                    </form>
                <?php endif; ?>
            </div>

            <div class="peecha-lm-card">
                <h2><?php echo esc_html(self::t('Import existing signed license', 'وارد کردن لایسنس قدیمی (امضا‌شده)')); ?></h2>
                <p><?php echo esc_html(self::t(
                    'If the customer already has a v2 key but does not appear in the list, paste the full key here (from license.json on their PC).',
                    'اگر مشتری کلید v2 دارد ولی در لیست نیست، کلید کامل را از license.json روی ویندوز بچسبانید.'
                )); ?></p>
                <form method="post">
                    <?php wp_nonce_field('peecha_lm_action'); ?>
                    <input type="hidden" name="peecha_action" value="import_signed_license" />
                    <div class="peecha-lm-grid">
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label><?php echo esc_html(self::t('Signed license key', 'کلید لایسنس (امضا‌شده)')); ?></label>
                            <textarea name="import_license_key" rows="4" class="large-text code" dir="ltr" placeholder="eyJ..."></textarea>
                        </div>
                        <div class="peecha-lm-field peecha-lm-field--full">
                            <label><?php echo esc_html(self::t('HWID (optional)', 'شناسه دستگاه (اختیاری)')); ?></label>
                            <input name="import_hwid" class="regular-text" dir="ltr" placeholder="PGWJF00WBCA026" />
                            <?php self::hint(
                                'Usually read from the key payload; fill only if import fails.',
                                'معمولاً از خود کلید خوانده می‌شود؛ فقط اگر خطا داد پر کنید.'
                            ); ?>
                        </div>
                    </div>
                    <div class="peecha-lm-actions">
                        <?php submit_button(self::t('Import to list', 'ثبت در لیست'), 'secondary', 'submit', false); ?>
                    </div>
                </form>
            </div>

            <div class="peecha-lm-card">
                <h2><?php echo esc_html(self::t('Licenses', 'لایسنس‌ها')); ?></h2>
                <form method="get" class="peecha-lm-search">
                    <input type="hidden" name="page" value="peecha-licenses" />
                    <input type="search" name="s" value="<?php echo esc_attr($search); ?>" placeholder="<?php echo esc_attr(self::t('Search customer, email, HWID, key...', 'جستجو: مشتری، ایمیل، HWID، کلید...')); ?>" />
                    <?php submit_button(self::t('Search', 'جستجو'), 'secondary', '', false); ?>
                </form>

                <div class="peecha-lm-table-wrap">
                    <table class="peecha-lm-table">
                        <thead>
                            <tr>
                                <th><?php echo esc_html(self::t('ID', 'شناسه')); ?></th>
                                <th><?php echo esc_html(self::t('Customer', 'مشتری')); ?></th>
                                <th><?php echo esc_html(self::t('HWID', 'HWID')); ?></th>
                                <th><?php echo esc_html(self::t('Status', 'وضعیت')); ?></th>
                                <th><?php echo esc_html(self::t('Expires', 'انقضا')); ?></th>
                                <th><?php echo esc_html(self::t('Updates until', 'بروزرسانی تا')); ?></th>
                                <th><?php echo esc_html(self::t('Last seen', 'آخرین اتصال')); ?></th>
                                <th><?php echo esc_html(self::t('Website', 'وب‌سایت')); ?></th>
                                <th><?php echo esc_html(self::t('Actions', 'عملیات')); ?></th>
                            </tr>
                        </thead>
                        <tbody>
                        <?php if (!$licenses) : ?>
                            <tr><td colspan="9" class="peecha-lm-empty"><?php echo esc_html(self::t('No licenses yet.', 'هنوز لایسنسی ثبت نشده.')); ?></td></tr>
                        <?php else : ?>
                            <?php foreach ($licenses as $row) : ?>
                                <tr>
                                    <td><?php echo esc_html((string) $row['id']); ?></td>
                                    <td>
                                        <strong><?php echo esc_html($row['customer_name']); ?></strong><br />
                                        <small><?php echo esc_html($row['customer_email']); ?></small>
                                    </td>
                                    <td><code><?php echo esc_html($row['hwid'] ?: '—'); ?></code></td>
                                    <td>
                                        <span class="peecha-lm-badge peecha-lm-badge--<?php echo esc_attr($row['status'] === 'revoked' ? 'revoked' : 'active'); ?>">
                                            <?php echo esc_html(self::status_label($row['status'])); ?>
                                        </span>
                                    </td>
                                    <td class="peecha-gdate" data-gdate="<?php echo esc_attr($row['license_expires']); ?>"><?php echo esc_html($row['license_expires']); ?></td>
                                    <td class="peecha-gdate" data-gdate="<?php echo esc_attr($row['updates_until']); ?>"><?php echo esc_html($row['updates_until']); ?></td>
                                    <td><?php echo esc_html($row['last_seen_at'] ?: '—'); ?></td>
                                    <td>
                                        <?php $site = trim((string) ($row['site_url'] ?? '')); ?>
                                        <?php if ($site !== '') : ?>
                                            <a href="<?php echo esc_url($site); ?>" target="_blank" rel="noopener"><?php echo esc_html(preg_replace('#^https?://#i', '', untrailingslashit($site))); ?></a>
                                        <?php else : ?>
                                            —
                                        <?php endif; ?>
                                    </td>
                                    <td>
                                        <a class="button button-small" href="<?php echo esc_url(admin_url('admin.php?page=peecha-licenses&edit=' . (int) $row['id'])); ?>"><?php echo esc_html(self::t('Edit', 'ویرایش')); ?></a>
                                        <?php if (($row['status'] ?? '') !== 'revoked') : ?>
                                            <form method="post" style="display:inline;" onsubmit="return confirm('<?php echo esc_js(self::t('Revoke this license? The client will lose access on next online check.', 'این لایسنس باطل شود؟ برنامه در اتصال بعدی دسترسی را می‌بندد.')); ?>');">
                                                <?php wp_nonce_field('peecha_lm_action'); ?>
                                                <input type="hidden" name="peecha_action" value="revoke_license" />
                                                <input type="hidden" name="license_id" value="<?php echo esc_attr((string) $row['id']); ?>" />
                                                <button type="submit" class="button button-small"><?php echo esc_html(self::t('Revoke', 'باطل کردن')); ?></button>
                                            </form>
                                        <?php else : ?>
                                            <form method="post" style="display:inline;" onsubmit="return confirm('<?php echo esc_js(self::t('Remove from list permanently?', 'از لیست برای همیشه حذف شود؟')); ?>');">
                                                <?php wp_nonce_field('peecha_lm_action'); ?>
                                                <input type="hidden" name="peecha_action" value="delete_license" />
                                                <input type="hidden" name="license_id" value="<?php echo esc_attr((string) $row['id']); ?>" />
                                                <button type="submit" class="button button-small button-link-delete"><?php echo esc_html(self::t('Remove', 'حذف از لیست')); ?></button>
                                            </form>
                                        <?php endif; ?>
                                    </td>
                                </tr>
                            <?php endforeach; ?>
                        <?php endif; ?>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        <?php
    }
}
