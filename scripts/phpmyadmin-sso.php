<?php
/**
 * HostHive SSO bridge for phpMyAdmin.
 *
 * Accepts a one-time token issued by the HostHive API, validates it
 * against Redis, and sets up a phpMyAdmin SignonSession so the user
 * is automatically logged in.
 *
 * phpMyAdmin must be configured with:
 *   $cfg['Servers'][1]['auth_type'] = 'signon';
 *   $cfg['Servers'][1]['SignonSession'] = 'SignonSession';
 *   $cfg['Servers'][1]['SignonURL'] = '/phpmyadmin/sso.php';
 */

// Start the named session that phpMyAdmin expects for signon auth
session_name('SignonSession');
session_start();

$token = $_GET['token'] ?? '';

// No token -- redirect to phpMyAdmin (will show login page via SignonURL loop)
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
$key = "hosthive:pma_sso:{$token}";
$data = $redis->get($key);

if ($data === false) {
    header('HTTP/1.1 403 Forbidden');
    echo 'SSO token expired or invalid. Please try again from the panel.';
    exit;
}

// Delete immediately -- one-time use
$redis->del($key);

$creds = json_decode($data, true);
if (!$creds || empty($creds['user'])) {
    header('HTTP/1.1 500 Internal Server Error');
    echo 'Invalid SSO payload.';
    exit;
}

// Set the session variables that phpMyAdmin signon auth expects
$_SESSION['PMA_single_signon_user']     = $creds['user'];
$_SESSION['PMA_single_signon_password'] = $creds['password'];
$_SESSION['PMA_single_signon_host']     = $creds['server'] ?? 'localhost';

// Redirect to phpMyAdmin -- it will pick up credentials from the session
header('Location: /phpmyadmin/index.php');
exit;
