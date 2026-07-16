<?php
/**
 * One-time Peecha License Manager installer.
 * Upload to WordPress root (same folder as wp-config.php), open once, then delete.
 */

@ini_set('display_errors', '1');
@error_reporting(E_ALL);
@set_time_limit(120);

header('Content-Type: text/plain; charset=utf-8');

if (($_GET['token'] ?? '') !== '__INSTALL_TOKEN__') {
    http_response_code(403);
    echo "Forbidden\n";
    exit;
}

$wp_load = __DIR__ . '/wp-load.php';
if (!is_file($wp_load)) {
    echo "wp-load.php not found.\nPut peecha-lm-install.php in WordPress root.\n";
    exit;
}

define('WP_USE_THEMES', false);
require_once $wp_load;

require_once ABSPATH . 'wp-admin/includes/upgrade.php';

$plugin_slug = 'peecha-license-manager/peecha-license-manager.php';
$plugin_main = WP_PLUGIN_DIR . '/peecha-license-manager/peecha-license-manager.php';
$action = strtolower(trim((string) ($_GET['action'] ?? 'install')));

if ($action === 'remove') {
    $active = get_option('active_plugins', array());
    if (!is_array($active)) {
        $active = array();
    }
    $active = array_values(array_filter($active, function ($item) use ($plugin_slug) {
        return $item !== $plugin_slug;
    }));
    update_option('active_plugins', $active);
    echo "OK\nPlugin removed from active_plugins.\nDelete peecha-lm-install.php\n";
    exit;
}

if (!is_file($plugin_main)) {
    echo "Plugin files missing.\n";
    echo "Upload folder peecha-license-manager to wp-content/plugins/ first.\n";
    exit;
}

require_once WP_PLUGIN_DIR . '/peecha-license-manager/includes/class-db.php';
Peecha_LM_DB::activate();

$active = get_option('active_plugins', array());
if (!is_array($active)) {
    $active = array();
}
if (!in_array($plugin_slug, $active, true)) {
    $active[] = $plugin_slug;
    sort($active);
    update_option('active_plugins', $active);
}

echo "OK\n";
echo "Plugin: Peecha License Manager\n";
$version = 'unknown';
$header = @file_get_contents($plugin_main);
if ($header && preg_match('/Version:\s*(.+)/i', $header, $m)) {
    $version = trim($m[1]);
}
echo "Version: {$version}\n";
$site = rtrim((string) get_option('siteurl'), '/');
echo "REST base: {$site}/wp-json/peecha/v1/\n";
echo "\nDelete peecha-lm-install.php from server now.\n";
