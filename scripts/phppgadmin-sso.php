<?php
/**
 * HostHive SSO bridge for phpPgAdmin.
 *
 * Reads a one-time token from Redis (set by the NovaPanel API), validates it,
 * and auto-logs the user into phpPgAdmin by submitting credentials to its
 * login handler.
 *
 * This script must be placed at /usr/share/phppgadmin/sso.php
 */

$token = $_GET['token'] ?? '';

if (empty($token) || !preg_match('/^[A-Za-z0-9_-]+$/', $token)) {
    header('HTTP/1.1 400 Bad Request');
    echo 'Invalid or missing SSO token.';
    exit;
}

// Read Redis password from secrets
$redisPass = '';
$secretsFile = '/opt/hosthive/config/secrets.env';
if (file_exists($secretsFile)) {
    $lines = @file($secretsFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if ($lines) {
        foreach ($lines as $line) {
            if (strpos($line, 'REDIS_PASSWORD=') === 0) {
                $redisPass = substr($line, strlen('REDIS_PASSWORD='));
                break;
            }
        }
    }
}

// Connect to Redis
$redis = new Redis();
$redis->connect('127.0.0.1', 6379);
if (!empty($redisPass)) {
    $redis->auth($redisPass);
}

// Look up the one-time token
$key = "hosthive:pgadmin_sso:{$token}";
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

$server = $creds['server'] ?? 'localhost';
$database = $creds['database'] ?? '';

// Store credentials in session for phpPgAdmin auto-login.
// phpPgAdmin uses $_SESSION to hold login state per server.
session_name('PPA_ID');
session_start();

// phpPgAdmin stores credentials keyed by server index.
// The default server (localhost:5432) is typically server index 0.
// We set the login credentials directly in the session structure that
// phpPgAdmin expects.
$serverKey = 'server:localhost:5432';
$_SESSION['webdbLogin'][$serverKey]['username'] = $creds['user'];
$_SESSION['webdbLogin'][$serverKey]['password'] = $creds['password'];

// Also set for the simplified key format some phpPgAdmin versions use
$_SESSION['webdbLogin'][0]['username'] = $creds['user'];
$_SESSION['webdbLogin'][0]['password'] = $creds['password'];

session_write_close();

// Redirect to phpPgAdmin -- target the specific database if available
if (!empty($database)) {
    header("Location: /phppgadmin/redirect.php?subject=database&server=localhost:5432&database=" . urlencode($database));
} else {
    header('Location: /phppgadmin/index.php');
}
exit;
