<?php

if (!defined('ABSPATH')) {
    exit;
}

class Peecha_LM_Update
{
    public static function normalize_repo($repo)
    {
        $repo = trim((string) $repo);
        if ($repo === '') {
            return '';
        }

        if (preg_match('#github\.com/([^/]+/[^/#?\s]+)#i', $repo, $matches)) {
            return trim($matches[1], '/');
        }

        $repo = trim($repo, '/');
        if (preg_match('#^[^/\s]+/[^/\s]+$#', $repo)) {
            return $repo;
        }

        return '';
    }

    public static function github_repo()
    {
        $raw = get_option('peecha_lm_github_repo', '');
        if ($raw === '' && defined('PEECHA_LM_DEFAULT_GITHUB_REPO')) {
            $raw = PEECHA_LM_DEFAULT_GITHUB_REPO;
        }
        return self::normalize_repo($raw);
    }

    public static function github_token()
    {
        return trim((string) get_option('peecha_lm_github_token', ''));
    }

    private static function github_headers($accept = 'application/vnd.github+json')
    {
        $headers = array(
            'Accept' => $accept,
            'User-Agent' => 'Peecha-License-Manager/' . PEECHA_LM_VERSION,
        );
        $token = self::github_token();
        if ($token !== '') {
            $headers['Authorization'] = 'Bearer ' . $token;
        }
        return $headers;
    }

    public static function latest_release()
    {
        $repo = self::github_repo();
        if ($repo === '') {
            return null;
        }

        $url = 'https://api.github.com/repos/' . $repo . '/releases/latest';
        $resp = wp_remote_get($url, array(
            'timeout' => 6,
            'headers' => self::github_headers(),
        ));
        if (is_wp_error($resp)) {
            return null;
        }

        $code = (int) wp_remote_retrieve_response_code($resp);
        if ($code >= 400) {
            return null;
        }

        $body = json_decode(wp_remote_retrieve_body($resp), true);
        return is_array($body) ? $body : null;
    }

    public static function latest_version_from_github()
    {
        $release = self::latest_release();
        if (!$release || empty($release['tag_name'])) {
            return '';
        }

        return ltrim((string) $release['tag_name'], 'vV');
    }

    public static function client_mirror_dir()
    {
        $upload = wp_upload_dir();
        if (!empty($upload['error'])) {
            return '';
        }

        $dir = trailingslashit($upload['basedir']) . 'peecha-sync-updates';
        if (!is_dir($dir)) {
            wp_mkdir_p($dir);
        }

        return is_dir($dir) ? $dir : '';
    }

    private static function resolve_filesystem_path($raw)
    {
        $raw = trim((string) $raw);
        if ($raw === '') {
            return '';
        }

        if ($raw[0] === '/' || preg_match('#^[A-Za-z]:[\\\\/]#', $raw)) {
            return wp_normalize_path($raw);
        }

        return wp_normalize_path(ABSPATH . ltrim($raw, '/'));
    }

    public static function mirror_path()
    {
        $custom = trim((string) get_option('peecha_lm_mirror_path', ''));
        if ($custom !== '') {
            $path = self::resolve_filesystem_path($custom);
            if ($path !== '' && is_file($path)) {
                return $path;
            }
        }

        $dir = self::client_mirror_dir();
        if ($dir === '') {
            return '';
        }

        $saved = trim((string) get_option('peecha_lm_mirror_filename', ''));
        if ($saved !== '') {
            $path = $dir . '/' . basename($saved);
            if (is_file($path)) {
                return $path;
            }
        }

        $newest = self::newest_mirror_version();
        if ($newest !== '') {
            $path = $dir . '/PeechaSync-' . $newest . '.zip';
            if (is_file($path)) {
                return $path;
            }
        }

        $version = trim((string) get_option('peecha_lm_latest_version', ''));
        if ($version !== '') {
            $path = $dir . '/PeechaSync-' . $version . '.zip';
            if (is_file($path)) {
                return $path;
            }
        }

        $latest = $dir . '/latest.zip';
        if (is_file($latest)) {
            return $latest;
        }

        $candidates = glob($dir . '/PeechaSync-*.zip');
        if (is_array($candidates) && $candidates !== array()) {
            usort($candidates, function ($a, $b) {
                return filemtime($b) - filemtime($a);
            });
            if (is_file($candidates[0])) {
                return $candidates[0];
            }
        }

        return '';
    }

    public static function has_local_mirror()
    {
        if (self::mirror_path() !== '') {
            return true;
        }

        $mirror_id = (int) get_option('peecha_lm_mirror_attachment_id', 0);
        if ($mirror_id > 0) {
            $path = get_attached_file($mirror_id);
            return $path && file_exists($path);
        }

        return false;
    }

    public static function version_from_path($path)
    {
        if (!$path || !is_file($path)) {
            return '';
        }

        $name = basename($path);
        if (preg_match('/PeechaSync[-_]?v?(\d+\.\d+(?:\.\d+)?)/i', $name, $matches)) {
            return (string) $matches[1];
        }

        return '';
    }

    public static function version_from_mirror()
    {
        $newest = self::newest_mirror_version();
        if ($newest !== '') {
            return $newest;
        }
        return self::version_from_path(self::mirror_path());
    }

    public static function newest_mirror_version()
    {
        $dir = self::client_mirror_dir();
        if ($dir === '') {
            return '';
        }

        $best = '';
        foreach (glob($dir . '/PeechaSync-*.zip') ?: array() as $path) {
            if (!is_file($path)) {
                continue;
            }
            $ver = self::version_from_path($path);
            if ($ver === '') {
                continue;
            }
            if ($best === '' || version_compare($ver, $best, '>')) {
                $best = $ver;
            }
        }
        return $best;
    }

    public static function sync_latest_version_from_mirror()
    {
        $detected = self::newest_mirror_version();
        if ($detected === '') {
            return '';
        }

        $current = trim((string) get_option('peecha_lm_latest_version', ''));
        if ($current === '' || version_compare($detected, $current, '>')) {
            update_option('peecha_lm_latest_version', $detected);
            update_option('peecha_lm_mirror_filename', 'PeechaSync-' . $detected . '.zip');
        }

        return $detected;
    }

    public static function mirror_path_for_version($version = '')
    {
        $version = trim((string) $version);
        if ($version === '') {
            return '';
        }

        $custom = trim((string) get_option('peecha_lm_mirror_path', ''));
        if ($custom !== '') {
            $path = self::resolve_filesystem_path($custom);
            if ($path !== '' && is_file($path)) {
                $custom_ver = self::version_from_path($path);
                if ($custom_ver === '' || version_compare($custom_ver, $version, '>=')) {
                    return $path;
                }
            }
        }

        $dir = self::client_mirror_dir();
        if ($dir === '') {
            return '';
        }

        $exact = $dir . '/PeechaSync-' . $version . '.zip';
        if (is_file($exact)) {
            return $exact;
        }

        $latest = $dir . '/latest.zip';
        if (is_file($latest)) {
            $latest_ver = self::version_from_path($latest);
            if ($latest_ver === '' || version_compare($latest_ver, $version, '>=')) {
                return $latest;
            }
        }

        return '';
    }

    public static function resolve_latest_version($fallback = '')
    {
        $manual = trim((string) $fallback);
        $from_scan = self::newest_mirror_version();

        if ($from_scan !== '') {
            if ($manual === '' || version_compare($from_scan, $manual, '>=')) {
                return $from_scan;
            }
        }

        if (self::has_local_mirror()) {
            $from_mirror = self::version_from_path(self::mirror_path());
            if ($manual !== '' && $from_mirror !== '' && version_compare($manual, $from_mirror, '>')) {
                return $manual;
            }
            if ($from_mirror !== '' && ($manual === '' || version_compare($from_mirror, $manual, '>'))) {
                return $from_mirror;
            }
            if ($manual !== '') {
                return $manual;
            }
            if ($from_mirror !== '') {
                return $from_mirror;
            }
        }

        if ($manual !== '') {
            return $manual;
        }

        $github = self::latest_version_from_github();
        if ($github !== '') {
            return $github;
        }

        return $manual;
    }

    public static function zip_asset_from_release($release)
    {
        if (!is_array($release) || empty($release['assets']) || !is_array($release['assets'])) {
            return null;
        }

        foreach ($release['assets'] as $asset) {
            if (!is_array($asset)) {
                continue;
            }
            $name = (string) ($asset['name'] ?? '');
            if ($name !== '' && preg_match('/\.zip$/i', $name)) {
                return $asset;
            }
        }

        return null;
    }

    public static function serve_local_zip($path)
    {
        if (!$path || !is_file($path)) {
            return new WP_Error('no_mirror', 'Update package missing on server', array('status' => 404));
        }

        $filename = basename($path);
        header('Content-Type: application/zip');
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        header('Content-Length: ' . filesize($path));
        readfile($path);
        exit;
    }

    public static function stream_github_zip()
    {
        $release = self::latest_release();
        if (!$release) {
            return new WP_Error('no_github_release', 'GitHub release not found', array('status' => 404));
        }

        $asset = self::zip_asset_from_release($release);
        if (!$asset || empty($asset['url'])) {
            return new WP_Error('no_github_zip', 'No ZIP asset in latest GitHub release', array('status' => 404));
        }

        $browser_url = (string) ($asset['browser_download_url'] ?? '');
        if ($browser_url !== '') {
            header('Location: ' . $browser_url, true, 302);
            exit;
        }

        $asset_url = (string) $asset['url'];
        $filename = !empty($asset['name']) ? basename((string) $asset['name']) : 'PeechaSync-update.zip';

        $resp = wp_remote_get($asset_url, array(
            'timeout' => 60,
            'headers' => self::github_headers('application/octet-stream'),
        ));
        if (is_wp_error($resp)) {
            return new WP_Error('github_download_failed', $resp->get_error_message(), array('status' => 502));
        }

        $code = (int) wp_remote_retrieve_response_code($resp);
        if ($code >= 400) {
            return new WP_Error('github_download_failed', 'GitHub download failed (HTTP ' . $code . ')', array('status' => 502));
        }

        $body = wp_remote_retrieve_body($resp);
        if ($body === '') {
            return new WP_Error('github_download_failed', 'Empty update package from GitHub', array('status' => 502));
        }

        header('Content-Type: application/zip');
        header('Content-Disposition: attachment; filename="' . $filename . '"');
        header('Content-Length: ' . strlen($body));
        echo $body;
        exit;
    }
}
