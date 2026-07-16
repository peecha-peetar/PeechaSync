<?php

if (!defined('ABSPATH')) {
    exit;
}

class Peecha_LM_DB
{
    const TABLE = 'peecha_licenses';

    public static function table_name()
    {
        global $wpdb;
        return $wpdb->prefix . self::TABLE;
    }

    public static function activate()
    {
        self::create_tables();
        self::upgrade_schema();
        self::seed_defaults();
    }

    public static function upgrade_schema()
    {
        global $wpdb;
        $table = self::table_name();
        if ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table)) !== $table) {
            return;
        }

        $col = $wpdb->get_row("SHOW COLUMNS FROM {$table} LIKE 'license_key'", ARRAY_A);
        if (is_array($col) && isset($col['Type']) && stripos($col['Type'], 'varchar(512)') === false) {
            $wpdb->query("ALTER TABLE {$table} MODIFY license_key VARCHAR(512) NOT NULL");
        }

        $site_col = $wpdb->get_row("SHOW COLUMNS FROM {$table} LIKE 'site_url'", ARRAY_A);
        if (!$site_col) {
            $wpdb->query("ALTER TABLE {$table} ADD COLUMN site_url VARCHAR(255) NULL DEFAULT NULL");
        }
    }

    public static function deactivate()
    {
        return;
    }

    public static function create_tables()
    {
        global $wpdb;

        $table = self::table_name();
        $charset = $wpdb->get_charset_collate();

        $sql = "CREATE TABLE {$table} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            license_key VARCHAR(512) NOT NULL,
            customer_name VARCHAR(191) NOT NULL DEFAULT '',
            customer_email VARCHAR(191) NOT NULL DEFAULT '',
            hwid VARCHAR(191) NULL DEFAULT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            license_expires DATE NULL DEFAULT NULL,
            updates_until DATE NULL DEFAULT NULL,
            notes TEXT NULL,
            last_seen_at DATETIME NULL DEFAULT NULL,
            last_app_version VARCHAR(32) NULL DEFAULT NULL,
            site_url VARCHAR(255) NULL DEFAULT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY license_key (license_key(191)),
            KEY status (status),
            KEY hwid (hwid)
        ) {$charset};";

        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        dbDelta($sql);
    }

    public static function seed_defaults()
    {
        if (get_option('peecha_lm_api_key')) {
            return;
        }

        update_option('peecha_lm_api_key', wp_generate_password(32, false, false));
        update_option('peecha_lm_github_repo', PEECHA_LM_DEFAULT_GITHUB_REPO);
        update_option('peecha_lm_latest_version', '1.0.37');
        update_option('peecha_lm_mirror_attachment_id', 0);
        update_option('peecha_lm_mirror_path', '');
        update_option('peecha_lm_mirror_filename', '');
        update_option('peecha_lm_offline_grace_days', 7);
    }

    public static function ensure_runtime_options()
    {
        if (!defined('PEECHA_LM_DEFAULT_GITHUB_REPO')) {
            return;
        }

        $repo = Peecha_LM_Update::normalize_repo(get_option('peecha_lm_github_repo', ''));
        // فقط اگه خالیه یا دقیقاً یکی از مقادیرِ قدیمیِ شناخته‌شده‌ی اشتباهه،
        // خودکار با پیش‌فرضِ درست جایگزین می‌شه — نه با هر مقداری که فرق کنه؛
        // اگه ادمین خودش یه ریپوی سفارشی تنظیم کرده باشه، دست‌نخورده می‌مونه.
        $known_wrong = array('shehnm/peechasync', 'shehniv/peechasync');
        if ($repo === '' || in_array(strtolower($repo), $known_wrong, true)) {
            update_option('peecha_lm_github_repo', PEECHA_LM_DEFAULT_GITHUB_REPO);
        }

        // دیگر کلیدِ HMAC لورفته رو به‌عنوانِ پیش‌فرض seed نمی‌کنیم — این کلید
        // چون در تاریخچه‌ی مخزنِ عمومی بوده، بازنشسته شده (به Ed25519 نگاه کنید).
    }

    public static function get_license_by_key($license_key)
    {
        global $wpdb;
        $table = self::table_name();
        return $wpdb->get_row(
            $wpdb->prepare("SELECT * FROM {$table} WHERE license_key = %s LIMIT 1", $license_key),
            ARRAY_A
        );
    }

    public static function get_license_by_hwid($hwid)
    {
        global $wpdb;
        $hwid = trim((string) $hwid);
        if ($hwid === '') {
            return null;
        }
        $table = self::table_name();
        return $wpdb->get_row(
            $wpdb->prepare(
                "SELECT * FROM {$table} WHERE hwid = %s ORDER BY id DESC LIMIT 1",
                $hwid
            ),
            ARRAY_A
        );
    }

    public static function get_license($id)
    {
        global $wpdb;
        $table = self::table_name();
        return $wpdb->get_row(
            $wpdb->prepare("SELECT * FROM {$table} WHERE id = %d LIMIT 1", (int) $id),
            ARRAY_A
        );
    }

    public static function list_licenses($search = '')
    {
        global $wpdb;
        $table = self::table_name();

        if ($search !== '') {
            $like = '%' . $wpdb->esc_like($search) . '%';
            return $wpdb->get_results(
                $wpdb->prepare(
                    "SELECT * FROM {$table}
                     WHERE license_key LIKE %s OR customer_name LIKE %s OR customer_email LIKE %s OR hwid LIKE %s OR site_url LIKE %s
                     ORDER BY id DESC",
                    $like,
                    $like,
                    $like,
                    $like,
                    $like
                ),
                ARRAY_A
            );
        }

        return $wpdb->get_results("SELECT * FROM {$table} ORDER BY id DESC", ARRAY_A);
    }

    public static function insert_license($data)
    {
        global $wpdb;
        $now = current_time('mysql');
        $row = array(
            'license_key' => $data['license_key'],
            'customer_name' => $data['customer_name'] ?? '',
            'customer_email' => $data['customer_email'] ?? '',
            'hwid' => $data['hwid'] ?? null,
            'status' => $data['status'] ?? 'active',
            'license_expires' => $data['license_expires'] ?? null,
            'updates_until' => $data['updates_until'] ?? null,
            'notes' => $data['notes'] ?? '',
            'created_at' => $now,
            'updated_at' => $now,
        );

        $wpdb->insert(self::table_name(), $row);
        return (int) $wpdb->insert_id;
    }

    public static function update_license($id, $data)
    {
        global $wpdb;
        $data['updated_at'] = current_time('mysql');
        return $wpdb->update(self::table_name(), $data, array('id' => (int) $id));
    }

    public static function delete_license($id)
    {
        global $wpdb;
        return $wpdb->delete(self::table_name(), array('id' => (int) $id));
    }

    public static function blocked_hwids()
    {
        $raw = get_option('peecha_lm_blocked_hwids', array());
        if (!is_array($raw)) {
            return array();
        }
        $out = array();
        foreach ($raw as $hwid) {
            $hwid = trim((string) $hwid);
            if ($hwid !== '') {
                $out[] = $hwid;
            }
        }
        return $out;
    }

    public static function is_hwid_blocked($hwid)
    {
        $hwid = trim((string) $hwid);
        if ($hwid === '') {
            return false;
        }
        foreach (self::blocked_hwids() as $blocked) {
            if (strcasecmp($blocked, $hwid) === 0) {
                return true;
            }
        }
        return false;
    }

    public static function block_hwid($hwid)
    {
        $hwid = trim((string) $hwid);
        if ($hwid === '' || self::is_hwid_blocked($hwid)) {
            return;
        }
        $list = self::blocked_hwids();
        $list[] = $hwid;
        update_option('peecha_lm_blocked_hwids', $list);
    }

    public static function unblock_hwid($hwid)
    {
        $hwid = trim((string) $hwid);
        if ($hwid === '') {
            return;
        }
        $list = array();
        foreach (self::blocked_hwids() as $blocked) {
            if (strcasecmp($blocked, $hwid) !== 0) {
                $list[] = $blocked;
            }
        }
        update_option('peecha_lm_blocked_hwids', $list);
    }

    public static function touch_seen($id, $hwid, $app_version, $site_url = '')
    {
        self::upgrade_schema();
        $data = array(
            'hwid' => $hwid,
            'last_seen_at' => current_time('mysql'),
            'last_app_version' => $app_version,
        );
        $site_url = trim((string) $site_url);
        if ($site_url !== '') {
            $data['site_url'] = $site_url;
        }
        return self::update_license($id, $data);
    }

    public static function upsert_license_row($data)
    {
        $license_key = trim((string) ($data['license_key'] ?? ''));
        if ($license_key === '') {
            return 0;
        }

        $existing = self::get_license_by_key($license_key);
        if (!$existing) {
            $hwid = trim((string) ($data['hwid'] ?? ''));
            if ($hwid !== '') {
                $existing = self::get_license_by_hwid($hwid);
            }
        }

        if ($existing) {
            $id = (int) $existing['id'];
            $patch = array();
            foreach (array('customer_name', 'customer_email', 'hwid', 'status', 'license_expires', 'updates_until') as $field) {
                if (!empty($data[$field]) && empty($existing[$field])) {
                    $patch[$field] = $data[$field];
                }
            }
            if ($patch) {
                self::update_license($id, $patch);
            }
            return $id;
        }

        return self::insert_license($data);
    }
}
