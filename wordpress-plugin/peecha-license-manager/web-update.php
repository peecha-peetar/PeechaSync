<?php
/**
 * In-place update when wp-admin cannot replace the plugin folder.
 * Upload update.zip here, open this URL once, then delete this file and the zip.
 */

@ini_set('display_errors', '1');
@error_reporting(E_ALL);
@set_time_limit(300);

header('Content-Type: text/plain; charset=utf-8');

function peecha_lm_web_fail($message)
{
    echo "ERROR\n";
    echo $message . "\n";
    exit;
}

$token = (string) ($_GET['token'] ?? '');
$has_token = ($token !== '' && $token === '__INSTALL_TOKEN__');

if (!is_file(__DIR__ . '/includes/class-updater.php')) {
    peecha_lm_web_fail(
        'includes/class-updater.php is missing. Upload the whole includes/ folder from tools/wp-license-deploy/peecha-license-manager/ first, then open this URL again.'
    );
}

require_once __DIR__ . '/includes/class-updater.php';

$authorized = $has_token;
if (!$authorized) {
    $wp_load = realpath(__DIR__ . '/../../../wp-load.php');
    if ($wp_load && is_file($wp_load)) {
        define('WP_USE_THEMES', false);
        require_once $wp_load;
        if (function_exists('is_user_logged_in') && is_user_logged_in()
            && function_exists('current_user_can') && current_user_can('manage_options')) {
            $authorized = true;
        }
    }
}

if (!$authorized) {
    http_response_code(403);
    echo "Forbidden\n";
    echo "Log in to wp-admin first, or use the token link from INSTALL-URL.txt\n";
    exit;
}

$zip_path = null;
foreach (array('update.zip', 'peecha-license-manager.zip', 'peecha-license-manager-wp.zip') as $name) {
    $candidate = __DIR__ . '/' . $name;
    if (is_file($candidate)) {
        $zip_path = $candidate;
        break;
    }
}
if (!$zip_path) {
    $matches = glob(__DIR__ . '/*.zip');
    if (is_array($matches)) {
        foreach ($matches as $candidate) {
            if (is_file($candidate)) {
                $zip_path = $candidate;
                break;
            }
        }
    }
}
if (!$zip_path) {
    peecha_lm_web_fail('Upload update.zip to this folder first (File Manager)');
}

$result = Peecha_LM_Updater::apply_zip($zip_path, __DIR__);
if (is_array($result) && empty($result['ok'])) {
    peecha_lm_web_fail((string) ($result['message'] ?? 'Update failed'));
}
if (function_exists('is_wp_error') && is_wp_error($result)) {
    peecha_lm_web_fail($result->get_error_message());
}

$version = is_array($result) ? (string) ($result['version'] ?? 'unknown') : 'unknown';

echo "OK\n";
echo "Plugin updated in place\n";
echo "Version: {$version}\n";
echo "\nDelete web-update.php and the ZIP file now.\n";
echo "If peecha-license-manager-wp folder exists in plugins/, delete it from File Manager.\n";
