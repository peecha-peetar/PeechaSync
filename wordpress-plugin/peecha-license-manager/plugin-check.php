<?php
/**
 * One-time diagnostics. Open in browser, then delete this file.
 * https://peecha.ir/wp-content/plugins/peecha-license-manager/plugin-check.php
 */

@ini_set('display_errors', '1');
@error_reporting(E_ALL);

header('Content-Type: text/plain; charset=utf-8');

echo "Peecha License Manager — check\n";
echo 'PHP: ' . PHP_VERSION . "\n";
echo 'Folder: ' . basename(__DIR__) . "\n\n";

if (basename(__DIR__) !== 'peecha-license-manager') {
    echo "WARN: Wrong folder name. Must be wp-content/plugins/peecha-license-manager/\n";
    echo "      Delete folder " . basename(__DIR__) . " after copying files to peecha-license-manager/\n\n";
}

$required = array(
    'peecha-license-manager.php',
    'includes/class-admin.php',
    'includes/class-db.php',
    'includes/class-license.php',
    'includes/class-rest-api.php',
    'includes/class-updater.php',
    'assets/css/admin.css',
    'assets/js/admin.js',
    'assets/vendor/persian-date.min.js',
    'assets/vendor/persian-datepicker.min.css',
    'assets/vendor/persian-datepicker.min.js',
);

$missing = array();
foreach ($required as $rel) {
    $path = __DIR__ . '/' . $rel;
    if (is_file($path)) {
        echo "OK   $rel\n";
    } else {
        echo "MISS $rel\n";
        $missing[] = $rel;
    }
}

$main = __DIR__ . '/peecha-license-manager.php';
if (is_file($main)) {
    $header = file_get_contents($main);
    if ($header && preg_match('/Version:\s*(.+)/i', $header, $m)) {
        echo "\nVersion in files: " . trim($m[1]) . "\n";
    }
}

$plugins_root = realpath(__DIR__ . '/..');
if ($plugins_root) {
    foreach (array('peecha-license-manager-wp', 'peecha-license-manager-old') as $bad) {
        if (is_dir($plugins_root . '/' . $bad)) {
            echo "\nWARN: Remove wrong folder: wp-content/plugins/{$bad}/\n";
        }
    }
}

if ($missing) {
    echo "\nUpload missing files from tools/wp-license-deploy/peecha-license-manager/\n";
    echo "Or upload update.zip and open web-update.php\n";
    exit;
}

if (version_compare(PHP_VERSION, '7.4.0', '<')) {
    echo "\nERROR: PHP 7.4+ required. Change PHP version in DirectAdmin.\n";
    exit;
}

$wp_load = realpath(__DIR__ . '/../../../wp-load.php');
if (!$wp_load || !is_file($wp_load)) {
    echo "\nERROR: wp-load.php not found\n";
    exit;
}

define('WP_USE_THEMES', false);
require_once $wp_load;

echo "\nWordPress loaded OK\n";

if (!is_plugin_active('peecha-license-manager/peecha-license-manager.php')) {
    echo "Plugin status: not active (activate peecha-license-manager/peecha-license-manager.php only)\n";
} else {
    echo "Plugin status: active\n";
}

require_once __DIR__ . '/includes/class-db.php';
Peecha_LM_DB::activate();
echo "DB tables: OK\n";

echo "\nAll good. Delete plugin-check.php\n";
echo "Update without wp-admin delete: Peecha Licenses -> بروزرسانی افزونه -> upload update.zip\n";
