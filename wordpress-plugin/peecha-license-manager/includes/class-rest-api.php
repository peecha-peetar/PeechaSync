<?php

if (!defined('ABSPATH')) {
    exit;
}

class Peecha_LM_REST_API
{
    const NS = 'peecha/v1';

    public static function init()
    {
        add_action('rest_api_init', array(__CLASS__, 'register_routes'));
    }

    public static function register_routes()
    {
        register_rest_route(self::NS, '/license/activate', array(
            'methods' => 'POST',
            'callback' => array(__CLASS__, 'activate'),
            'permission_callback' => array(__CLASS__, 'client_permission'),
        ));

        register_rest_route(self::NS, '/license/validate', array(
            'methods' => 'POST',
            'callback' => array(__CLASS__, 'validate'),
            'permission_callback' => array(__CLASS__, 'client_permission'),
        ));

        register_rest_route(self::NS, '/updates/check', array(
            'methods' => 'GET',
            'callback' => array(__CLASS__, 'updates_check'),
            'permission_callback' => array(__CLASS__, 'client_permission'),
        ));

        register_rest_route(self::NS, '/updates/download', array(
            'methods' => 'GET',
            'callback' => array(__CLASS__, 'updates_download'),
            'permission_callback' => array(__CLASS__, 'client_permission'),
        ));

        register_rest_route(self::NS, '/health', array(
            'methods' => 'GET',
            'callback' => array(__CLASS__, 'health'),
            'permission_callback' => '__return_true',
        ));
    }

    public static function client_permission(WP_REST_Request $request)
    {
        $expected = (string) get_option('peecha_lm_api_key', '');
        if ($expected === '') {
            return true;
        }

        $provided = $request->get_header('x-peecha-api-key');
        if (!$provided) {
            $provided = $request->get_param('api_key');
        }

        if (!is_string($provided) || !hash_equals($expected, $provided)) {
            return new WP_Error('forbidden', 'Invalid API key', array('status' => 403));
        }

        return true;
    }

    private static function read_license_key($value)
    {
        $key = is_string($value) ? trim($value) : '';
        if ($key === '') {
            return '';
        }
        return preg_replace('/[\r\n\t\0]/', '', $key);
    }

    private static function read_body(WP_REST_Request $request)
    {
        $params = $request->get_json_params();
        if (!is_array($params)) {
            $params = array();
        }
        foreach (array('license_key', 'hwid', 'app_version', 'version', 'site_url', 'wc_url') as $key) {
            if (!isset($params[$key]) && $request->get_param($key) !== null) {
                $params[$key] = $request->get_param($key);
            }
        }
        return $params;
    }

    private static function read_site_url(WP_REST_Request $request, array $body = null)
    {
        $body = is_array($body) ? $body : self::read_body($request);
        $raw = (string) ($body['site_url'] ?? $body['wc_url'] ?? $request->get_param('site_url') ?? $request->get_param('wc_url') ?? '');
        if ($raw === '') {
            $raw = (string) $request->get_header('x-peecha-site-url');
        }
        return Peecha_LM_License::normalize_customer_site_url($raw);
    }

    public static function activate(WP_REST_Request $request)
    {
        $body = self::read_body($request);
        $license_key = self::read_license_key($body['license_key'] ?? '');
        $hwid = sanitize_text_field((string) ($body['hwid'] ?? ''));
        $app_version = sanitize_text_field((string) ($body['app_version'] ?? ''));
        $site_url = self::read_site_url($request, $body);

        if ($license_key === '' || $hwid === '') {
            return new WP_Error('bad_request', 'license_key and hwid are required', array('status' => 400));
        }

        $result = Peecha_LM_License::activate($license_key, $hwid, $app_version, $site_url);
        if (is_wp_error($result)) {
            return $result;
        }

        return rest_ensure_response(array('ok' => true, 'license' => $result));
    }

    public static function validate(WP_REST_Request $request)
    {
        $body = self::read_body($request);
        $license_key = self::read_license_key($body['license_key'] ?? '');
        $hwid = sanitize_text_field((string) ($body['hwid'] ?? ''));
        $app_version = sanitize_text_field((string) ($body['app_version'] ?? ''));
        $site_url = self::read_site_url($request, $body);

        if ($license_key === '' || $hwid === '') {
            return new WP_Error('bad_request', 'license_key and hwid are required', array('status' => 400));
        }

        $result = Peecha_LM_License::validate($license_key, $hwid, $app_version, $site_url);
        if (is_wp_error($result)) {
            return $result;
        }

        return rest_ensure_response(array('ok' => true, 'license' => $result));
    }

    public static function updates_check(WP_REST_Request $request)
    {
        $license_key = self::read_license_key($request->get_param('license_key'));
        $hwid = sanitize_text_field((string) $request->get_param('hwid'));
        $current = sanitize_text_field((string) ($request->get_param('version') ?: $request->get_param('app_version')));

        if ($license_key === '' || $hwid === '') {
            return new WP_Error('bad_request', 'license_key and hwid are required', array('status' => 400));
        }

        $row = Peecha_LM_License::resolve_row($license_key, $hwid);
        $state = Peecha_LM_License::license_state($row, $hwid, $current);
        if (!$state['valid']) {
            return new WP_Error($state['code'], $state['message'], array('status' => 403, 'data' => $state));
        }

        $site_url = self::read_site_url($request);
        Peecha_LM_License::persist_row($row, $hwid, $current, $site_url);

        Peecha_LM_Update::sync_latest_version_from_mirror();

        if (empty($state['updates_allowed'])) {
            return rest_ensure_response(array(
                'ok' => true,
                'update_available' => false,
                'reason' => 'updates_not_allowed',
                'current_version' => $current,
                'latest_version' => $current,
            ));
        }

        $latest = Peecha_LM_Update::resolve_latest_version(
            sanitize_text_field((string) get_option('peecha_lm_latest_version', $current))
        );
        $update_available = $latest !== '' && version_compare($latest, $current, '>');

        $download_url = rest_url(self::NS . '/updates/download');

        return rest_ensure_response(array(
            'ok' => true,
            'update_available' => $update_available,
            'current_version' => $current,
            'latest_version' => $latest !== '' ? $latest : $current,
            'download_url' => $download_url,
            'mirror_url' => $download_url,
            'mirror_ready' => Peecha_LM_Update::has_local_mirror(),
            'changelog' => (string) get_option('peecha_lm_changelog', ''),
            'license' => $state,
        ));
    }

    public static function updates_download(WP_REST_Request $request)
    {
        $license_key = self::read_license_key($request->get_param('license_key'));
        $hwid = sanitize_text_field((string) $request->get_param('hwid'));

        if ($license_key === '' || $hwid === '') {
            return new WP_Error('bad_request', 'license_key and hwid are required', array('status' => 400));
        }

        $row = Peecha_LM_License::resolve_row($license_key, $hwid);
        $state = Peecha_LM_License::license_state($row, $hwid);
        if (!$state['valid']) {
            return new WP_Error($state['code'], $state['message'], array('status' => 403));
        }
        if (empty($state['updates_allowed'])) {
            return new WP_Error('updates_not_allowed', 'Updates not allowed for this license', array('status' => 403));
        }

        $current = sanitize_text_field((string) ($request->get_param('version') ?: $request->get_param('app_version')));
        $site_url = self::read_site_url($request);
        Peecha_LM_License::persist_row($row, $hwid, $current, $site_url);

        $latest = Peecha_LM_Update::resolve_latest_version(
            sanitize_text_field((string) get_option('peecha_lm_latest_version', ''))
        );

        if ($latest !== '') {
            $versioned = Peecha_LM_Update::mirror_path_for_version($latest);
            if ($versioned !== '') {
                Peecha_LM_Update::serve_local_zip($versioned);
            }
        }

        $local_path = Peecha_LM_Update::mirror_path();
        if ($local_path !== '') {
            $mirror_ver = Peecha_LM_Update::version_from_path($local_path);
            if ($latest === '' || $mirror_ver === '' || version_compare($mirror_ver, $latest, '>=')) {
                Peecha_LM_Update::serve_local_zip($local_path);
            }
        }

        $mirror_id = (int) get_option('peecha_lm_mirror_attachment_id', 0);
        if ($mirror_id > 0) {
            $path = get_attached_file($mirror_id);
            if ($path && file_exists($path)) {
                Peecha_LM_Update::serve_local_zip($path);
            }
        }

        if (Peecha_LM_Update::github_repo() !== '') {
            return Peecha_LM_Update::stream_github_zip();
        }

        return new WP_Error('no_update_source', 'No update package available', array('status' => 404));
    }

    public static function health(WP_REST_Request $request)
    {
        $licenses = Peecha_LM_DB::list_licenses('');
        Peecha_LM_Update::sync_latest_version_from_mirror();
        $latest = Peecha_LM_Update::resolve_latest_version(
            sanitize_text_field((string) get_option('peecha_lm_latest_version', ''))
        );
        return rest_ensure_response(array(
            'ok' => true,
            'plugin_version' => PEECHA_LM_VERSION,
            'latest_client_version' => $latest !== '' ? $latest : null,
            'mirror_ready' => Peecha_LM_Update::has_local_mirror(),
            'mirror_version' => Peecha_LM_Update::version_from_mirror(),
            'github_repo' => Peecha_LM_Update::github_repo(),
            'license_count' => is_array($licenses) ? count($licenses) : 0,
            'auto_import' => true,
            'api_key_required' => (string) get_option('peecha_lm_api_key', '') !== '',
        ));
    }
}
