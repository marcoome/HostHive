<?php
/**
 * HostHive SSO bridge for phpMyAdmin (cookie auth mode).
 * Accepts a one-time token from Redis, renders auto-submit login form.
 */

$token = $_GET['token'] ?? '';
if (empty($token) || !preg_match('/^[A-Za-z0-9_-]+$/', $token)) {
    die('Invalid or missing SSO token.');
}

// Read Redis password from secrets
$redisPass = '';
$secretsFile = '/opt/hosthive/config/secrets.env';
if (file_exists($secretsFile)) {
    $lines = file($secretsFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    foreach ($lines as $line) {
        if (strpos($line, 'REDIS_PASSWORD=') === 0) {
            $redisPass = substr($line, strlen('REDIS_PASSWORD='));
            break;
        }
    }
}

// Connect to Redis with auth
$redis = new Redis();
$redis->connect('127.0.0.1', 6379);
if (!empty($redisPass)) {
    // Try Redis 6+ ACL auth (user + password), fall back to legacy auth
    try {
        $redis->auth(['default', $redisPass]);
    } catch (Exception $e) {
        try {
            $redis->auth($redisPass);
        } catch (Exception $e2) {
            die('Redis authentication failed: ' . $e2->getMessage());
        }
    }
}

// Look up the one-time token
$key = "hosthive:pma_sso:{$token}";
$data = $redis->get($key);

if ($data === false) {
    die('Token expired or invalid. Please try again from the panel.');
}

// Delete immediately -- one-time use
$redis->del($key);

$creds = json_decode($data, true);
if (!$creds || empty($creds['user'])) {
    die('Invalid SSO payload.');
}

$user = htmlspecialchars($creds['user'], ENT_QUOTES, 'UTF-8');
$pass = htmlspecialchars($creds['password'], ENT_QUOTES, 'UTF-8');
$server = htmlspecialchars($creds['server'] ?? 'localhost', ENT_QUOTES, 'UTF-8');
?>
<!DOCTYPE html>
<html>
<head><title>Logging into phpMyAdmin...</title></head>
<body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
<div>
<p>Logging into phpMyAdmin as <strong><?= $user ?></strong>...</p>
<form id="sso_form" method="post" action="/phpmyadmin/index.php">
    <input type="hidden" name="pma_username" value="<?= $user ?>">
    <input type="hidden" name="pma_password" value="<?= $pass ?>">
    <input type="hidden" name="pma_servername" value="<?= $server ?>">
    <noscript><button type="submit">Click to login</button></noscript>
</form>
</div>
<script>document.getElementById('sso_form').submit();</script>
</body>
</html>
