<?php
/**
 * Plugin Name: Huquq+ RAG Webhook
 * Description: Maqola nashr qilinganda, tahrirlanganda yoki nashrdan olinganda Huquq+ AI yordamchisiga (RAG) imzolangan xabar yuboradi. Xabarda maqola matni bo'lmaydi: RAG serveri maqolani o'zi ochiq REST API'dan oladi.
 * Version: 1.0.0
 * Requires at least: 5.8
 * Requires PHP: 7.4
 * Author: Huquq Plus
 * License: GPLv2 or later
 *
 * Sozlash (wp-config.php, "That's all, stop editing!" qatoridan OLDIN):
 *   define('HUQUQPLUS_RAG_WEBHOOK_URL', 'https://rag.example.uz/api/v1/webhooks/huquqplus');
 *   define('HUQUQPLUS_RAG_WEBHOOK_SECRET', '...kamida 32 belgili tasodifiy kalit...');
 * Kalit RAG serveridagi .env faylidagi HUQUQPLUS_WEBHOOK_SECRET bilan bir xil bo'lishi kerak.
 *
 * Imzo: X-HuquqPlus-Signature: sha256=HEX( HMAC-SHA256( secret, "<timestamp>.<body>" ) ),
 *       X-HuquqPlus-Timestamp: <unix soniya>. Server 5 daqiqadan eski xabarlarni rad etadi.
 */

if (!defined('ABSPATH')) {
    exit;
}

final class HuquqPlus_RAG_Webhook
{
    const VERSION = '1.0.0';
    const CRON_HOOK = 'huquqplus_rag_dispatch';
    const LOG_OPTION = 'huquqplus_rag_webhook_log';
    const LOG_SIZE = 30;
    const MAX_ATTEMPTS = 5;
    const MIN_SECRET_LENGTH = 32;

    /** @var array<string, array> post_id:lang => payload, collected during one request and sent at shutdown */
    private static $pending = array();

    public static function init()
    {
        add_action('transition_post_status', array(__CLASS__, 'on_transition'), 10, 3);
        add_action('before_delete_post', array(__CLASS__, 'on_delete'), 10, 1);
        add_action('shutdown', array(__CLASS__, 'flush'));
        add_action(self::CRON_HOOK, array(__CLASS__, 'dispatch'), 10, 2);

        if (is_admin()) {
            add_action('admin_menu', array(__CLASS__, 'admin_menu'));
            add_action('admin_post_huquqplus_rag_test', array(__CLASS__, 'handle_test'));
            add_action('admin_notices', array(__CLASS__, 'admin_notice'));
        }
    }

    /* ------------------------------------------------------------------ events */

    /**
     * transition_post_status fires on every save, including updates of an already published post
     * (publish -> publish), so it covers create, edit, unpublish and trash in one place.
     */
    public static function on_transition($new_status, $old_status, $post)
    {
        if (!$post instanceof WP_Post || $post->post_type !== 'post') {
            return;
        }
        if (wp_is_post_revision($post) || wp_is_post_autosave($post)) {
            return;
        }
        if ($new_status === 'publish') {
            self::queue('upsert', $post);
        } elseif ($old_status === 'publish') {
            // published -> draft / pending / private / trash: the article must leave the knowledge base
            self::queue('delete', $post);
        }
    }

    public static function on_delete($post_id)
    {
        $post = get_post($post_id);
        if ($post instanceof WP_Post && $post->post_type === 'post') {
            self::queue('delete', $post);
        }
    }

    private static function queue($event, WP_Post $post)
    {
        $lang = self::post_language($post->ID);
        // the last event of the request wins (e.g. a publish followed by a quick edit)
        self::$pending[$post->ID . ':' . $lang] = array(
            'event'        => $event,
            'event_id'     => wp_generate_uuid4(),
            'post_id'      => (int) $post->ID,
            'lang'         => $lang,
            'modified_gmt' => (string) $post->post_modified_gmt,
            'site'         => home_url('/'),
        );
    }

    /** WPML keeps every translation as a separate post; the RAG side needs the language to fetch the right one. */
    private static function post_language($post_id)
    {
        $details = apply_filters('wpml_post_language_details', null, $post_id);
        if (is_array($details) && !empty($details['language_code'])) {
            return sanitize_key($details['language_code']);
        }
        return '';
    }

    /**
     * Sending happens in WP-Cron, not inside the editor's save request: a slow or unreachable RAG server
     * never delays saving, and failed deliveries are retried with backoff.
     */
    public static function flush()
    {
        if (empty(self::$pending)) {
            return;
        }
        foreach (self::$pending as $payload) {
            wp_schedule_single_event(time(), self::CRON_HOOK, array($payload, 1));
        }
        self::$pending = array();
    }

    /* ---------------------------------------------------------------- delivery */

    public static function dispatch($payload, $attempt = 1)
    {
        $result = self::send($payload);
        self::log($payload, $attempt, $result);

        $retryable = $result['code'] === 0 || $result['code'] === 429 || $result['code'] >= 500;
        if (!$result['ok'] && $retryable && $attempt < self::MAX_ATTEMPTS) {
            // 2, 4, 8, 16 minutes
            wp_schedule_single_event(time() + 60 * (2 ** $attempt), self::CRON_HOOK, array($payload, $attempt + 1));
        }
    }

    /** @return array{ok: bool, code: int, message: string} */
    private static function send(array $payload)
    {
        $url = defined('HUQUQPLUS_RAG_WEBHOOK_URL') ? (string) HUQUQPLUS_RAG_WEBHOOK_URL : '';
        $secret = defined('HUQUQPLUS_RAG_WEBHOOK_SECRET') ? (string) HUQUQPLUS_RAG_WEBHOOK_SECRET : '';
        if ($url === '' || $secret === '') {
            return array('ok' => false, 'code' => -1, 'message' => 'Plagin sozlanmagan (URL yoki kalit yo\'q)');
        }

        $body = wp_json_encode($payload);
        $timestamp = (string) time();
        $signature = hash_hmac('sha256', $timestamp . '.' . $body, $secret);

        $response = wp_remote_post($url, array(
            'timeout'     => 10,
            'redirection' => 0,
            'headers'     => array(
                'Content-Type'          => 'application/json',
                'User-Agent'            => 'HuquqPlus-RAG-Webhook/' . self::VERSION,
                'X-HuquqPlus-Timestamp' => $timestamp,
                'X-HuquqPlus-Signature' => 'sha256=' . $signature,
            ),
            'body'        => $body,
            'data_format' => 'body',
        ));

        if (is_wp_error($response)) {
            return array('ok' => false, 'code' => 0, 'message' => $response->get_error_message());
        }
        $code = (int) wp_remote_retrieve_response_code($response);
        $message = substr(wp_strip_all_tags((string) wp_remote_retrieve_body($response)), 0, 200);
        return array('ok' => $code >= 200 && $code < 300, 'code' => $code, 'message' => $message);
    }

    private static function log(array $payload, $attempt, array $result)
    {
        $log = get_option(self::LOG_OPTION, array());
        if (!is_array($log)) {
            $log = array();
        }
        array_unshift($log, array(
            'time'    => time(),
            'event'   => isset($payload['event']) ? $payload['event'] : '',
            'post_id' => isset($payload['post_id']) ? (int) $payload['post_id'] : 0,
            'lang'    => isset($payload['lang']) ? $payload['lang'] : '',
            'attempt' => (int) $attempt,
            'ok'      => (bool) $result['ok'],
            'code'    => (int) $result['code'],
            'message' => (string) $result['message'],
        ));
        update_option(self::LOG_OPTION, array_slice($log, 0, self::LOG_SIZE), false);
    }

    /* ------------------------------------------------------------------ admin */

    private static function config_problems()
    {
        $problems = array();
        $url = defined('HUQUQPLUS_RAG_WEBHOOK_URL') ? (string) HUQUQPLUS_RAG_WEBHOOK_URL : '';
        $secret = defined('HUQUQPLUS_RAG_WEBHOOK_SECRET') ? (string) HUQUQPLUS_RAG_WEBHOOK_SECRET : '';
        if ($url === '') {
            $problems[] = 'wp-config.php da HUQUQPLUS_RAG_WEBHOOK_URL belgilanmagan.';
        } elseif (stripos($url, 'https://') !== 0) {
            $problems[] = 'HUQUQPLUS_RAG_WEBHOOK_URL https:// bilan boshlanishi kerak.';
        }
        if ($secret === '') {
            $problems[] = 'wp-config.php da HUQUQPLUS_RAG_WEBHOOK_SECRET belgilanmagan.';
        } elseif (strlen($secret) < self::MIN_SECRET_LENGTH) {
            $problems[] = 'HUQUQPLUS_RAG_WEBHOOK_SECRET kamida ' . self::MIN_SECRET_LENGTH . ' belgidan iborat bo\'lishi kerak.';
        }
        return $problems;
    }

    public static function admin_notice()
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        $problems = self::config_problems();
        if (empty($problems)) {
            return;
        }
        echo '<div class="notice notice-warning"><p><strong>Huquq+ RAG Webhook:</strong> ';
        echo esc_html(implode(' ', $problems));
        echo '</p></div>';
    }

    public static function admin_menu()
    {
        add_management_page('Huquq+ RAG Webhook', 'Huquq+ RAG Webhook', 'manage_options', 'huquqplus-rag-webhook', array(__CLASS__, 'render_page'));
    }

    public static function render_page()
    {
        if (!current_user_can('manage_options')) {
            wp_die(esc_html__('Ruxsat yo\'q.'));
        }
        $problems = self::config_problems();
        $log = get_option(self::LOG_OPTION, array());
        $url = defined('HUQUQPLUS_RAG_WEBHOOK_URL') ? (string) HUQUQPLUS_RAG_WEBHOOK_URL : '';
        ?>
        <div class="wrap">
            <h1>Huquq+ RAG Webhook</h1>
            <p>Maqola nashr qilinganda, tahrirlanganda yoki nashrdan olinganda AI yordamchi bazasi avtomatik yangilanadi.
               Xabar yetib bormasa ham RAG serveri har soatda saytni o'zi tekshiradi.</p>

            <h2>Holat</h2>
            <?php if (empty($problems)) : ?>
                <p><span class="dashicons dashicons-yes-alt" style="color:#008a20" aria-hidden="true"></span>
                   Sozlangan. Manzil: <code><?php echo esc_html($url); ?></code></p>
            <?php else : ?>
                <ul><?php foreach ($problems as $problem) : ?><li><?php echo esc_html($problem); ?></li><?php endforeach; ?></ul>
            <?php endif; ?>

            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <input type="hidden" name="action" value="huquqplus_rag_test">
                <?php wp_nonce_field('huquqplus_rag_test'); ?>
                <?php submit_button('Sinov xabarini yuborish', 'secondary', 'submit', false, empty($problems) ? array() : array('disabled' => 'disabled')); ?>
            </form>

            <h2>Oxirgi yuborishlar</h2>
            <?php if (empty($log) || !is_array($log)) : ?>
                <p>Hali hech narsa yuborilmagan.</p>
            <?php else : ?>
                <table class="widefat striped">
                    <thead><tr><th scope="col">Vaqt</th><th scope="col">Hodisa</th><th scope="col">Post</th><th scope="col">Til</th><th scope="col">Urinish</th><th scope="col">Natija</th></tr></thead>
                    <tbody>
                    <?php foreach ($log as $row) : ?>
                        <tr>
                            <td><?php echo esc_html(wp_date('Y-m-d H:i:s', (int) $row['time'])); ?></td>
                            <td><?php echo esc_html($row['event']); ?></td>
                            <td><?php echo $row['post_id'] ? '<a href="' . esc_url(get_edit_post_link((int) $row['post_id'])) . '">' . (int) $row['post_id'] . '</a>' : '&mdash;'; ?></td>
                            <td><?php echo esc_html($row['lang']); ?></td>
                            <td><?php echo (int) $row['attempt']; ?></td>
                            <td><?php echo $row['ok'] ? 'OK' : esc_html('Xato ' . $row['code'] . ($row['message'] !== '' ? ': ' . $row['message'] : '')); ?></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            <?php endif; ?>
        </div>
        <?php
    }

    public static function handle_test()
    {
        if (!current_user_can('manage_options')) {
            wp_die(esc_html__('Ruxsat yo\'q.'));
        }
        check_admin_referer('huquqplus_rag_test');
        $payload = array(
            'event'        => 'ping',
            'event_id'     => wp_generate_uuid4(),
            'post_id'      => 0,
            'lang'         => '',
            'modified_gmt' => gmdate('Y-m-d H:i:s'),
            'site'         => home_url('/'),
        );
        self::log($payload, 1, self::send($payload));
        wp_safe_redirect(admin_url('tools.php?page=huquqplus-rag-webhook'));
        exit;
    }
}

HuquqPlus_RAG_Webhook::init();
