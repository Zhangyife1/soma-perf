<?php
/**
 * SomaPerf WordPress 埋点代码
 *
 * 用法一（推荐）：用 WPCode / Insert Headers and Footers 插件新建一个
 *               「PHP Snippet」，把本文件内容粘贴进去并启用。
 * 用法二：把内容追加到子主题的 functions.php（不要直接改父主题）。
 *
 * 依赖：deploy.sh 已把 soma-perf.js 复制到网站根目录 /js/soma-perf.js。
 */
add_action('wp_enqueue_scripts', function () {
    if (is_admin()) {
        return;
    }

    $endpoint = defined('SOMA_PERF_ENDPOINT') ? SOMA_PERF_ENDPOINT : 'https://www.somaagent.com.cn/collect';
    $site_id  = defined('SOMA_PERF_SITE_ID') ? SOMA_PERF_SITE_ID : 'somaagent';
    $token    = defined('SOMA_PERF_TOKEN') ? SOMA_PERF_TOKEN : '';
    $defer    = defined('SOMA_PERF_DEFER') ? (bool) SOMA_PERF_DEFER : false;

    wp_enqueue_script('soma-perf', '/js/soma-perf.js', array(), '0.2.0', false);
    if ($defer) {
        wp_script_add_data('soma-perf', 'defer', true);
    }

    $init = sprintf(
        'window.SomaPerf.init({endpoint:%1$s, siteId:%2$s, token:%3$s});',
        wp_json_encode($endpoint),
        wp_json_encode($site_id),
        wp_json_encode($token)
    );
    if ($defer) {
        $init = 'document.addEventListener("DOMContentLoaded", function(){ if (window.SomaPerf) { ' . $init . ' } });';
    }
    wp_add_inline_script('soma-perf', $init);
});
