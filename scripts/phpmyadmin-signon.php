<?php
/**
 * HostHive phpMyAdmin manual login page (signon auth).
 */
session_name('SignonSession');
session_start();
$error = $_GET['error'] ?? '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $_SESSION['PMA_single_signon_user'] = $_POST['user'] ?? '';
    $_SESSION['PMA_single_signon_password'] = $_POST['password'] ?? '';
    $_SESSION['PMA_single_signon_host'] = 'localhost';
    session_write_close();
    header('Location: /phpmyadmin/index.php');
    exit;
}
?>
<!DOCTYPE html>
<html><head><title>phpMyAdmin Login</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;background:#f5f5f5;margin:0}
.box{background:white;padding:2rem;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.1);width:320px}
h2{margin:0 0 1rem;color:#333}
label{font-size:13px;color:#555;display:block;margin-top:8px}
input{width:100%;padding:8px;margin:4px 0 8px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}
button{width:100%;padding:10px;background:#4f46e5;color:white;border:none;border-radius:4px;cursor:pointer;font-size:14px;margin-top:8px}
button:hover{background:#4338ca}
.err{color:red;font-size:12px;margin:0 0 8px}
.hint{font-size:11px;color:#888;margin-top:12px;text-align:center}</style></head>
<body><div class="box">
<h2>phpMyAdmin</h2>
<?php if($error === 'expired') echo '<p class="err">Session expired. Please login again.</p>'; ?>
<form method="post">
<label>Username</label><input name="user" required autofocus>
<label>Password</label><input name="password" type="password" required>
<button type="submit">Log In</button>
</form>
<p class="hint">Or use SSO from the HostHive panel.</p>
</div></body></html>
