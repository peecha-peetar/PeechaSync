<?php
/**
 * One-time installer — inside plugin folder. Delete after OK.
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

function peecha_lm_fail($message)
{
    echo "ERROR\n";
    echo $message . "\n";
    exit;
}

$wp_load = realpath(__DIR__ . '/../../../wp-load.php');
if (!$wp_load || !is_file($wp_load)) {
    peecha_lm_fail('wp-load.php not found');
}

define('WP_USE_THEMES', false);
require_once $wp_load;

if (!defined('ABSPATH')) {
    peecha_lm_fail('WordPress bootstrap failed');
}

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
    echo "OK\nPlugin removed from active_plugins.\nDelete web-install.php\n";
    exit;
}

if (!is_file($plugin_main)) {
    peecha_lm_fail('Plugin main file missing');
}

$db_file = WP_PLUGIN_DIR . '/peecha-license-manager/includes/class-db.php';
if (!is_file($db_file)) {
    peecha_lm_fail('class-db.php missing');
}

require_once $db_file;

try {
    Peecha_LM_DB::activate();
} catch (Throwable $e) {
    peecha_lm_fail('DB activate: ' . $e->getMessage());
}

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
echo "\nDelete web-install.php now.\n";
