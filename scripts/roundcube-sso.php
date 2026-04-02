<?php
/**
 * HostHive SSO bridge for Roundcube webmail.
 *
 * Accepts a one-time token issued by the HostHive API, validates it
 * against Redis, and automatically logs the user into Roundcube by
 * submitting credentials to its login handler.
 *
 * This script must be placed at /usr/share/roundcube/sso.php
 */

$token = $_GET['token'] ?? '';

if (empty($token) || !preg_match('/^[A-Za-z0-9_-]+$/', $token)) {
    header('HTTP/1.1 400 Bad Request');
    echo 'Invalid or missing SSO token.';
    exit;
}

// Connect to Redis
$redis = new Redis();
$redis->connect('127.0.0.1', 6379);

// Authenticate with Redis using the password from secrets.env
$secretsFile = '/opt/hosthive/config/secrets.env';
if (file_exists($secretsFile)) {
    $contents = file_get_contents($secretsFile);
    if (preg_match('/REDIS_PASSWORD=(.+)/', $contents, $matches)) {
        $redisPass = trim($matches[1]);
        if (!empty($redisPass)) {
            $redis->auth($redisPass);
        }
    }
}

// Look up the one-time token
$key = "hosthive:rc_sso:{$token}";
$data = $redis->get($key);

if ($data === false) {
    header('HTTP/1.1 403 Forbidden');
    echo 'SSO token expired or invalid. Please try again from the panel.';
    exit;
}

// Delete immediately -- one-time use
$redis->del($key);

$creds = json_decode($data, true);
if (!$creds || empty($creds['user']) || empty($creds['password'])) {
    header('HTTP/1.1 500 Internal Server Error');
    echo 'Invalid SSO payload.';
    exit;
}

// Bootstrap Roundcube environment
define('INSTALL_PATH', '/usr/share/roundcube/');

// Include Roundcube framework
require_once INSTALL_PATH . 'program/include/iniset.php';

$rcmail = rcmail::get_instance(0, 'web');

// Authenticate directly through Roundcube's auth mechanism
$auth = $rcmail->login($creds['user'], $creds['password'], 'localhost', false);

if ($auth) {
    // Login succeeded -- redirect to Roundcube inbox
    $rcmail->session->remove('temp');
    $rcmail->session->set('language', 'en_US');

    // Build the redirect URL to Roundcube mailbox
    header('Location: /roundcube/?_task=mail');
    exit;
} else {
    // Login failed -- could be wrong credentials or IMAP issue
    header('HTTP/1.1 401 Unauthorized');
    echo 'Roundcube login failed. The email credentials may be incorrect or the mail server is unreachable.';
    exit;
}
