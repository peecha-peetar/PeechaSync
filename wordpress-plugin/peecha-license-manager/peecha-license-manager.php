<?php
/**
 * Plugin Name: Peecha License Manager
 * Description: License CRUD, activation/validation API, and update mirror for PeechaSync desktop app.
 * Version: 1.0.41
 * Author: Peecha
 * Text Domain: peecha-license-manager
 * Domain Path: /languages
 */

if (!defined('ABSPATH')) {
    exit;
}

define('PEECHA_LM_VERSION', '1.0.41');
define('PEECHA_LM_DEFAULT_GITHUB_REPO', 'peecha-peetar/PeechaSync');
define('PEECHA_LM_PLUGIN_FILE', __FILE__);
define('PEECHA_LM_PLUGIN_DIR', plugin_dir_path(__FILE__));

function peecha_lm_load_core()
{
    require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-db.php';
    require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-license.php';
    require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-update.php';
    require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-updater.php';
    require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-rest-api.php';
}

register_activation_hook(__FILE__, function () {
    require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-db.php';
    Peecha_LM_DB::activate();
});

add_action('plugins_loaded', function () {
    load_plugin_textdomain(
        'peecha-license-manager',
        false,
        dirname(plugin_basename(PEECHA_LM_PLUGIN_FILE)) . '/languages'
    );

    peecha_lm_load_core();
    Peecha_LM_REST_API::init();

    if (get_option('peecha_lm_db_version') !== PEECHA_LM_VERSION) {
        Peecha_LM_DB::activate();
        update_option('peecha_lm_db_version', PEECHA_LM_VERSION);
    }
    Peecha_LM_DB::ensure_runtime_options();

    if (is_admin()) {
        require_once PEECHA_LM_PLUGIN_DIR . 'includes/class-admin.php';
        Peecha_LM_Admin::init();
    }
});
