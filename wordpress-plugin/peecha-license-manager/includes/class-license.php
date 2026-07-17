<?php

if (!defined('ABSPATH')) {
    exit;
}

class Peecha_LM_License
{
    public static function normalize_customer_site_url($raw)
    {
        $raw = trim((string) $raw);
        if ($raw === '') {
            return '';
        }
        $url = esc_url_raw($raw);
        if ($url !== '') {
            return untrailingslashit($url);
        }
        if (preg_match('#^https?://#i', $raw)) {
            $url = esc_url_raw(untrailingslashit($raw) . '/');
            if ($url !== '') {
                return untrailingslashit($url);
            }
        }
        return '';
    }

    /**
     * دیگر استفاده نشود — کلید HMAC مشترک (V2) چون داخل سورس عمومی PeechaSync
     * هاردکد بود، لو رفت (هر کسی که کد را می‌دید می‌توانست خودش لایسنس بسازد).
     * جایگزین شد با امضای نامتقارن Ed25519 (V3) — ببینید ed25519_private_seed()
     * و generate_key(). این متد فقط برای مستندسازیِ تاریخچه نگه داشته شده.
     */
    public static function hmac_secret()
    {
        $secret = get_option('peecha_lm_hmac_secret', '');
        return is_string($secret) ? $secret : '';
    }

    /**
     * seed خصوصیِ ۳۲بایتیِ Ed25519 (base64) — فقط سمتِ سرور، هرگز در سورسِ
     * توزیع‌شده یا مخزنِ گیت قرار نمی‌گیرد. باید یک‌بار در تنظیمات پلاگین
     * ست شود (Peecha License → Ed25519 Private Key).
     */
    public static function ed25519_private_seed()
    {
        $b64 = get_option('peecha_lm_ed25519_private_key', '');
        if (!is_string($b64) || $b64 === '') {
            return '';
        }
        $seed = base64_decode(trim($b64), true);
        if ($seed === false || strlen($seed) !== SODIUM_CRYPTO_SIGN_SEEDBYTES) {
            return '';
        }
        return $seed;
    }

    public static function ed25519_public_key_b64()
    {
        $seed = self::ed25519_private_seed();
        if ($seed === '' || !function_exists('sodium_crypto_sign_seed_keypair')) {
            return '';
        }
        $kp = sodium_crypto_sign_seed_keypair($seed);
        return base64_encode(sodium_crypto_sign_publickey($kp));
    }

    /** 'wc' | 'ps' | 'both' — پلتفرمِ مجاز برای این لایسنس. */
    public static function normalize_platform_scope($value)
    {
        $value = strtolower(trim((string) $value));
        return in_array($value, array('wc', 'ps'), true) ? $value : 'both';
    }

    /** 0 = نامحدود، وگرنه حداکثر تعدادِ سایتِ مجاز. */
    public static function normalize_max_sites($value)
    {
        $n = (int) $value;
        return $n > 0 ? $n : 0;
    }

    public static function generate_key($hwid, $license_expires, $updates_until = null, $max_sites = 0, $platform = 'both')
    {
        $hwid = sanitize_text_field($hwid);
        $license_expires = self::normalize_date($license_expires);
        if (!$license_expires) {
            return new WP_Error('invalid_date', 'license_expires is required');
        }

        if (!function_exists('sodium_crypto_sign_detached')) {
            return new WP_Error('sodium_missing', 'PHP sodium extension is required to sign licenses (PHP 7.2+).');
        }
        $seed = self::ed25519_private_seed();
        if ($seed === '') {
            return new WP_Error(
                'signing_key_missing',
                'Ed25519 private key not configured — Peecha License settings → Ed25519 Private Key.'
            );
        }

        $updates_until = self::normalize_date($updates_until ?: $license_expires);
        $issued = gmdate('Y-m-d');

        $payload = array(
            'v' => 3,
            'h' => $hwid,
            'e' => $license_expires,
            'u' => $updates_until,
            'i' => $issued,
            's' => self::normalize_max_sites($max_sites),
            'p' => self::normalize_platform_scope($platform),
        );

        $payload_json = wp_json_encode($payload, JSON_UNESCAPED_UNICODE);
        $payload_b64 = rtrim(strtr(base64_encode($payload_json), '+/', '-_'), '=');

        $kp = sodium_crypto_sign_seed_keypair($seed);
        $secret_key = sodium_crypto_sign_secretkey($kp);
        $signature = sodium_crypto_sign_detached($payload_b64, $secret_key);
        $signature_b64 = rtrim(strtr(base64_encode($signature), '+/', '-_'), '=');

        return $payload_b64 . '.' . $signature_b64;
    }

    /**
     * فقط لایسنسِ V3 (امضای نامتقارنِ Ed25519) قبول می‌شود. V2 (HMAC مشترک)
     * عمداً دیگر پذیرفته نمی‌شود — چون کلیدِ آن قبلاً در مخزنِ عمومی لو رفت
     * و پذیرفتنش یعنی همان حفره‌ی امنیتی هنوز باز است.
     */
    public static function verify_v2_signed_key($license_key, $hwid = '')
    {
        if (!is_string($license_key) || strpos($license_key, '.') === false) {
            return null;
        }
        if (!function_exists('sodium_crypto_sign_verify_detached')) {
            return null;
        }

        $parts = explode('.', $license_key, 2);
        if (count($parts) !== 2) {
            return null;
        }

        list($payload_b64, $given_sig_b64) = $parts;

        $pad = strlen($payload_b64) % 4;
        $padded_payload_b64 = $pad ? $payload_b64 . str_repeat('=', 4 - $pad) : $payload_b64;
        $payload_json = base64_decode(strtr($padded_payload_b64, '-_', '+/'), true);
        if ($payload_json === false) {
            return null;
        }

        $payload = json_decode($payload_json, true);
        if (!is_array($payload) || (int) ($payload['v'] ?? 0) !== 3) {
            return null;
        }

        $sig_pad = strlen($given_sig_b64) % 4;
        $padded_sig_b64 = $sig_pad ? $given_sig_b64 . str_repeat('=', 4 - $sig_pad) : $given_sig_b64;
        $signature = base64_decode(strtr($padded_sig_b64, '-_', '+/'), true);
        if ($signature === false) {
            return null;
        }

        $public_key_b64 = self::ed25519_public_key_b64();
        if ($public_key_b64 === '') {
            return null;
        }
        $public_key = base64_decode($public_key_b64, true);
        if ($public_key === false) {
            return null;
        }

        if (!sodium_crypto_sign_verify_detached($signature, $payload_b64, $public_key)) {
            return null;
        }

        $hwid = trim((string) $hwid);
        $payload_hwid = trim((string) ($payload['h'] ?? ''));
        if ($hwid !== '' && $payload_hwid !== '' && strcasecmp($payload_hwid, $hwid) !== 0) {
            return null;
        }

        if (self::is_expired($payload['e'] ?? null)) {
            return null;
        }

        return $payload;
    }

    public static function row_from_v2_payload($license_key, array $payload)
    {
        $updates_until = self::cap_updates_until($payload['e'] ?? null, $payload['u'] ?? null);
        return array(
            'id' => 0,
            'license_key' => $license_key,
            'customer_name' => '',
            'customer_email' => '',
            'hwid' => (string) ($payload['h'] ?? ''),
            'status' => 'active',
            'license_expires' => self::normalize_date($payload['e'] ?? null),
            'updates_until' => $updates_until,
            'notes' => '',
        );
    }

    public static function resolve_row($license_key, $hwid = '')
    {
        $license_key = trim((string) $license_key);
        $hwid = trim((string) $hwid);
        if ($hwid !== '' && Peecha_LM_DB::is_hwid_blocked($hwid)) {
            $active = Peecha_LM_DB::get_license_by_hwid($hwid);
            if ($active && ($active['status'] ?? '') === 'active') {
                Peecha_LM_DB::unblock_hwid($hwid);
            } else {
                return array(
                    'id' => 0,
                    'license_key' => $license_key,
                    'customer_name' => '',
                    'customer_email' => '',
                    'hwid' => $hwid,
                    'status' => 'revoked',
                    'license_expires' => null,
                    'updates_until' => null,
                    'notes' => 'Blocked on admin delete',
                );
            }
        }

        if ($license_key === '') {
            return null;
        }

        $row = Peecha_LM_DB::get_license_by_key($license_key);
        if ($row) {
            return $row;
        }

        $payload = self::verify_v2_signed_key($license_key, $hwid);
        if (!$payload) {
            return null;
        }

        $payload_hwid = trim((string) ($payload['h'] ?? ''));
        if ($payload_hwid !== '') {
            $row = Peecha_LM_DB::get_license_by_hwid($payload_hwid);
            if ($row) {
                return $row;
            }
        }

        return self::row_from_v2_payload($license_key, $payload);
    }

    /**
     * Save virtual (signed-only) licenses into wp-admin list and refresh last_seen.
     */
    public static function persist_row($row, $hwid, $app_version = '', $site_url = '')
    {
        if (!$row || !is_array($row)) {
            return $row;
        }

        $hwid = trim((string) $hwid);
        $app_version = sanitize_text_field((string) $app_version);
        $site_url = self::normalize_customer_site_url($site_url);
        $license_key = trim((string) ($row['license_key'] ?? ''));

        if (!empty($row['id'])) {
            Peecha_LM_DB::touch_seen((int) $row['id'], $hwid, $app_version, $site_url);
            $fresh = Peecha_LM_DB::get_license((int) $row['id']);
            return $fresh ?: $row;
        }

        if ($license_key === '') {
            return $row;
        }

        $hwid = trim((string) $hwid);
        if ($hwid !== '' && Peecha_LM_DB::is_hwid_blocked($hwid)) {
            return $row;
        }

        if (($row['status'] ?? '') === 'revoked') {
            return $row;
        }

        $id = Peecha_LM_DB::upsert_license_row(array(
            'license_key' => $license_key,
            'customer_name' => $row['customer_name'] ?? '',
            'customer_email' => $row['customer_email'] ?? '',
            'hwid' => $hwid !== '' ? $hwid : ($row['hwid'] ?? null),
            'status' => $row['status'] ?? 'active',
            'license_expires' => $row['license_expires'] ?? null,
            'updates_until' => $row['updates_until'] ?? null,
            'notes' => !empty($row['notes']) ? $row['notes'] : 'Auto-imported on client connect',
        ));

        if ($id > 0) {
            if ($hwid !== '' && ($row['status'] ?? '') === 'active') {
                Peecha_LM_DB::unblock_hwid($hwid);
            }
            Peecha_LM_DB::touch_seen($id, $hwid, $app_version, $site_url);
            $fresh = Peecha_LM_DB::get_license($id);
            return $fresh ?: $row;
        }

        return $row;
    }

    public static function normalize_date($value)
    {
        if (!$value) {
            return null;
        }
        $value = sanitize_text_field((string) $value);
        if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $value)) {
            return null;
        }
        return $value;
    }

    public static function jalali_to_gregorian($jy, $jm, $jd)
    {
        $jy = (int) $jy;
        $jm = (int) $jm;
        $jd = (int) $jd;
        if ($jy < 1 || $jm < 1 || $jm > 12 || $jd < 1 || $jd > 31) {
            return null;
        }

        $jy -= 979;
        $jm -= 1;
        $jd -= 1;

        $j_day_no = 365 * $jy + (int) ($jy / 33) * 8 + (int) (($jy % 33 + 3) / 4);
        $j_days_in_month = array(31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29);
        for ($i = 0; $i < $jm; $i++) {
            $j_day_no += $j_days_in_month[$i];
        }
        $j_day_no += $jd;

        $g_day_no = $j_day_no + 79;
        $gy = 1600 + 400 * (int) ($g_day_no / 146097);
        $g_day_no = $g_day_no % 146097;

        $leap = true;
        if ($g_day_no >= 36525) {
            $g_day_no--;
            $gy += 100 * (int) ($g_day_no / 36524);
            $g_day_no = $g_day_no % 36524;
            if ($g_day_no >= 365) {
                $g_day_no++;
            } else {
                $leap = false;
            }
        }

        $gy += 4 * (int) ($g_day_no / 1461);
        $g_day_no = $g_day_no % 1461;

        if ($g_day_no >= 366) {
            $leap = false;
            $g_day_no--;
            $gy += (int) ($g_day_no / 365);
            $g_day_no = $g_day_no % 365;
        }

        $g_days_in_month = array(31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31);
        for ($i = 0; $g_day_no >= $g_days_in_month[$i] + ($i === 1 && $leap ? 1 : 0); $i++) {
            $g_day_no -= $g_days_in_month[$i] + ($i === 1 && $leap ? 1 : 0);
        }
        $gm = $i + 1;
        $gd = $g_day_no + 1;

        return sprintf('%04d-%02d-%02d', $gy, $gm, $gd);
    }

    /** Accepts Y-m-d (Gregorian) or Y/m/d Jalali from admin form. */
    public static function normalize_date_input($value)
    {
        if (!$value) {
            return null;
        }
        $value = sanitize_text_field((string) $value);
        $value = str_replace(array('۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'), range(0, 9), $value);
        $value = trim(str_replace('/', '-', $value));

        if (!preg_match('/^(\d{4})-(\d{1,2})-(\d{1,2})$/', $value, $m)) {
            return null;
        }

        $y = (int) $m[1];
        $mo = (int) $m[2];
        $d = (int) $m[3];
        if ($mo < 1 || $mo > 12 || $d < 1 || $d > 31) {
            return null;
        }

        if ($y >= 1900) {
            return self::normalize_date(sprintf('%04d-%02d-%02d', $y, $mo, $d));
        }

        return self::jalali_to_gregorian($y, $mo, $d);
    }

    public static function cap_updates_until($license_expires, $updates_until = null)
    {
        $license_expires = self::normalize_date($license_expires);
        if (!$license_expires) {
            return null;
        }
        $updates_until = self::normalize_date($updates_until);
        if (!$updates_until || $updates_until > $license_expires) {
            return $license_expires;
        }
        return $updates_until;
    }

    public static function is_expired($date)
    {
        $date = self::normalize_date($date);
        if (!$date) {
            return true;
        }
        $today = gmdate('Y-m-d');
        return $date < $today;
    }

    public static function license_state($row, $hwid, $app_version = '')
    {
        if (!$row) {
            return array(
                'valid' => false,
                'code' => 'not_found',
                'message' => 'License key not found',
            );
        }

        if (($row['status'] ?? '') === 'revoked') {
            return array(
                'valid' => false,
                'code' => 'revoked',
                'message' => 'License revoked',
                'license_expires' => $row['license_expires'] ?? null,
                'updates_until' => $row['updates_until'] ?? null,
                'status' => 'revoked',
            );
        }

        if (self::is_expired($row['license_expires'] ?? null)) {
            return array(
                'valid' => false,
                'code' => 'expired',
                'message' => 'License expired',
                'license_expires' => $row['license_expires'] ?? null,
                'updates_until' => $row['updates_until'] ?? null,
                'status' => 'expired',
            );
        }

        $stored_hwid = trim((string) ($row['hwid'] ?? ''));
        $hwid = trim((string) $hwid);
        if ($stored_hwid !== '' && strcasecmp($stored_hwid, $hwid) !== 0) {
            return array(
                'valid' => false,
                'code' => 'hwid_mismatch',
                'message' => 'License bound to another device',
            );
        }

        $updates_allowed = !self::is_expired($row['updates_until'] ?? $row['license_expires'] ?? null);

        return array(
            'valid' => true,
            'code' => 'ok',
            'message' => 'License valid',
            'license_key' => $row['license_key'],
            'customer_name' => $row['customer_name'],
            'customer_email' => $row['customer_email'],
            'hwid' => $hwid,
            'status' => $row['status'],
            'license_expires' => $row['license_expires'],
            'updates_until' => $row['updates_until'] ?: $row['license_expires'],
            'updates_allowed' => $updates_allowed,
            'offline_grace_days' => (int) get_option('peecha_lm_offline_grace_days', 7),
            'app_version' => $app_version,
        );
    }

    public static function activate($license_key, $hwid, $app_version = '', $site_url = '')
    {
        $row = self::resolve_row($license_key, $hwid);
        if (!$row) {
            return new WP_Error('not_found', 'License key not found', array('status' => 404));
        }

        if (($row['status'] ?? '') === 'revoked') {
            return new WP_Error('revoked', 'License revoked', array('status' => 403));
        }

        if (self::is_expired($row['license_expires'] ?? null)) {
            return new WP_Error('expired', 'License expired', array('status' => 403));
        }

        $stored_hwid = trim((string) ($row['hwid'] ?? ''));
        $hwid = trim((string) $hwid);
        if ($stored_hwid !== '' && strcasecmp($stored_hwid, $hwid) !== 0) {
            return new WP_Error('hwid_mismatch', 'License bound to another device', array('status' => 403));
        }

        if ($stored_hwid === '' && $hwid !== '' && !empty($row['id'])) {
            Peecha_LM_DB::update_license((int) $row['id'], array('hwid' => $hwid));
            $row['hwid'] = $hwid;
        }

        $row = self::persist_row($row, $hwid, $app_version, $site_url);
        return self::license_state($row, $hwid, $app_version);
    }

    public static function validate($license_key, $hwid, $app_version = '', $site_url = '')
    {
        $row = self::resolve_row($license_key, $hwid);
        if (!$row) {
            return new WP_Error('not_found', 'License key not found', array('status' => 404));
        }

        $hwid = trim((string) $hwid);
        $state = self::license_state($row, $hwid, $app_version);
        if (!$state['valid']) {
            return new WP_Error($state['code'], $state['message'], array('status' => 403, 'data' => $state));
        }

        $row = self::persist_row($row, $hwid, $app_version, $site_url);
        return self::license_state($row, $hwid, $app_version);
    }

    public static function import_signed_key($license_key, $hwid = '', $app_version = '')
    {
        $license_key = trim((string) $license_key);
        if ($license_key === '') {
            return new WP_Error('bad_request', 'license_key is required', array('status' => 400));
        }

        $row = self::resolve_row($license_key, $hwid);
        if (!$row) {
            return new WP_Error('invalid_key', 'Signed license key is invalid or expired', array('status' => 400));
        }

        $hwid = trim((string) $hwid);
        if ($hwid === '') {
            $hwid = trim((string) ($row['hwid'] ?? ''));
        }

        $row = self::persist_row($row, $hwid, $app_version);
        return $row;
    }
}
