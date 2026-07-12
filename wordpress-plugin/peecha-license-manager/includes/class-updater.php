<?php

if (!defined('ABSPATH')) {
    // web-update.php may load this before WordPress.
}

class Peecha_LM_Updater
{
    public static function apply_zip($zip_path, $dest_dir)
    {
        if (!is_file($zip_path)) {
            return self::err('zip_missing', 'ZIP file not found');
        }
        if (!class_exists('ZipArchive')) {
            return self::err('ziparchive_missing', 'ZipArchive PHP extension missing');
        }
        if (!is_dir($dest_dir) && !@mkdir($dest_dir, 0755, true)) {
            return self::err('dest_missing', 'Plugin folder not writable');
        }

        $tmp = rtrim(sys_get_temp_dir(), '/\\') . '/peecha_lm_up_' . bin2hex(random_bytes(4));
        if (!@mkdir($tmp, 0700, true) && !is_dir($tmp)) {
            return self::err('temp_failed', 'Cannot create temp folder');
        }

        $zip = new ZipArchive();
        if ($zip->open($zip_path) !== true) {
            self::rrmdir($tmp);
            return self::err('zip_open_failed', 'Cannot open ZIP');
        }
        if (!$zip->extractTo($tmp)) {
            $zip->close();
            self::rrmdir($tmp);
            return self::err('extract_failed', 'Extract failed');
        }
        $zip->close();

        $source = self::find_source_root($tmp);
        if (!$source) {
            self::rrmdir($tmp);
            return self::err('bad_zip_layout', 'ZIP must contain peecha-license-manager.php (folder or flat layout)');
        }

        if (!self::copy_tree($source, rtrim($dest_dir, '/\\'))) {
            self::rrmdir($tmp);
            return self::err('copy_failed', 'Copy failed — check folder permissions (755/644)');
        }
        self::rrmdir($tmp);

        $main = rtrim($dest_dir, '/\\') . '/peecha-license-manager.php';
        if (!is_file($main)) {
            return self::err('main_missing', 'peecha-license-manager.php missing after update');
        }

        return array(
            'ok' => true,
            'version' => self::read_version($main),
        );
    }

    public static function find_source_root($tmp)
    {
        if (!is_dir($tmp)) {
            return null;
        }

        if (is_file($tmp . '/peecha-license-manager.php')) {
            return $tmp;
        }

        $children = array_values(array_diff(scandir($tmp), array('.', '..')));
        if (!$children) {
            return null;
        }

        foreach (array('peecha-license-manager', 'peecha-license-manager-wp') as $name) {
            $candidate = $tmp . '/' . $name;
            if (is_dir($candidate) && is_file($candidate . '/peecha-license-manager.php')) {
                return $candidate;
            }
        }

        if (count($children) === 1) {
            $only = $tmp . '/' . $children[0];
            if (is_dir($only) && is_file($only . '/peecha-license-manager.php')) {
                return $only;
            }
        }

        foreach ($children as $child) {
            $path = $tmp . '/' . $child;
            if (is_dir($path) && is_file($path . '/peecha-license-manager.php')) {
                return $path;
            }
        }

        return null;
    }

    public static function read_version($main_file)
    {
        $header = @file_get_contents($main_file);
        if ($header && preg_match('/Version:\s*(.+)/i', $header, $matches)) {
            return trim($matches[1]);
        }
        return 'unknown';
    }

    public static function wrong_plugin_folders()
    {
        if (!defined('WP_PLUGIN_DIR')) {
            return array();
        }

        $wrong = array();
        $base = rtrim(WP_PLUGIN_DIR, '/\\');
        foreach (array('peecha-license-manager-wp', 'peecha-license-manager-old') as $name) {
            $path = $base . '/' . $name;
            if (is_dir($path)) {
                $wrong[] = $path;
            }
        }
        return $wrong;
    }

    private static function err($code, $message)
    {
        if (function_exists('is_wp_error')) {
            return new WP_Error($code, $message);
        }
        return array('ok' => false, 'code' => $code, 'message' => $message);
    }

    public static function copy_tree($src, $dst)
    {
        if (!is_dir($src)) {
            return false;
        }
        if (!is_dir($dst) && !@mkdir($dst, 0755, true)) {
            return false;
        }

        $items = scandir($src);
        if ($items === false) {
            return false;
        }

        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            $from = $src . '/' . $item;
            $to = $dst . '/' . $item;
            if (is_dir($from)) {
                if (!self::copy_tree($from, $to)) {
                    return false;
                }
                @chmod($to, 0755);
            } else {
                if (!@copy($from, $to)) {
                    return false;
                }
                @chmod($to, 0644);
            }
        }

        return true;
    }

    public static function rrmdir($dir)
    {
        if (!is_dir($dir)) {
            return;
        }
        $items = scandir($dir);
        if ($items === false) {
            return;
        }
        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            $path = $dir . '/' . $item;
            if (is_dir($path)) {
                self::rrmdir($path);
            } else {
                @unlink($path);
            }
        }
        @rmdir($dir);
    }
}
