<?php
/**
 * HostHive SSO bridge for phpMyAdmin (signon auth mode).
 * Reads one-time token from Redis, sets SignonSession, redirects to phpMyAdmin.
 */
$token = $_GET['token'] ?? '';
if (empty($token) || !preg_match('/^[A-Za-z0-9_-]+$/', $token)) {
    header('Location: /phpmyadmin/signon.php');
    exit;
}

// Read Redis password
$redisPass = '';
$lines = @file('/opt/hosthive/config/secrets.env', FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
if ($lines) {
    foreach ($lines as $line) {
        if (strpos($line, 'REDIS_PASSWORD=') === 0) {
            $redisPass = substr($line, strlen('REDIS_PASSWORD='));
            break;
        }
    }
}

$redis = new Redis();
$redis->connect('127.0.0.1', 6379);
if (!empty($redisPass)) {
    $redis->auth($redisPass);
}

$data = $redis->get("hosthive:pma_sso:{$token}");
if ($data === false) {
    header('Location: /phpmyadmin/signon.php?error=expired');
    exit;
}
$redis->del("hosthive:pma_sso:{$token}");

$creds = json_decode($data, true);
session_name('SignonSession');
session_start();
$_SESSION['PMA_single_signon_user'] = $creds['user'];
$_SESSION['PMA_single_signon_password'] = $creds['password'];
$_SESSION['PMA_single_signon_host'] = 'localhost';
session_write_close();

header('Location: /phpmyadmin/index.php');
exit;
