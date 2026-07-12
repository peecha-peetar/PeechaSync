<?php
/**
 * Emergency: disable plugin when wp-admin shows critical error.
 * Open once in browser, then delete this file.
 */

@ini_set('display_errors', '1');
@error_reporting(E_ALL);
header('Content-Type: text/plain; charset=utf-8');

$wp_load = realpath(__DIR__ . '/../../../wp-load.php');
if (!$wp_load || !is_file($wp_load)) {
    echo "ERROR: wp-load.php not found\n";
    exit;
}

define('WP_USE_THEMES', false);
require_once $wp_load;

if (!function_exists('deactivate_plugins')) {
    require_once ABSPATH . 'wp-admin/includes/plugin.php';
}

deactivate_plugins('peecha-license-manager/peecha-license-manager.php', true, false);
echo "OK\nPlugin deactivated.\n";
echo "wp-admin should work now.\n";
echo "Fix files, then activate again from Plugins.\n";
echo "Delete plugin-off.php after use.\n";
