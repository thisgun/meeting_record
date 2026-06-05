<?php
require_once __DIR__ . '/../../g5_meeting_api/plugin/meeting_api/_bootstrap.php';

function expect_true($condition, $message) {
    if (!$condition) {
        fwrite(STDERR, "[fail] $message\n");
        exit(1);
    }
}

expect_true(meeting_ip_allowed('127.0.0.1', ''), 'empty allowlist should allow all clients');
expect_true(meeting_ip_allowed('127.0.0.1', '127.0.0.1'), 'exact IPv4 should match');
expect_true(!meeting_ip_allowed('127.0.0.2', '127.0.0.1'), 'different IPv4 should not match');
expect_true(meeting_ip_allowed('203.0.113.7', '203.0.113.0/24'), 'IPv4 CIDR should match');
expect_true(!meeting_ip_allowed('203.0.114.7', '203.0.113.0/24'), 'outside IPv4 CIDR should not match');
expect_true(meeting_ip_allowed('2001:db8::1', '2001:db8::/32'), 'IPv6 CIDR should match');
expect_true(!meeting_ip_allowed('2001:db9::1', '2001:db8::/32'), 'outside IPv6 CIDR should not match');
expect_true(meeting_ip_allowed('192.0.2.10', '127.0.0.1, 192.0.2.0/24'), 'comma-separated allowlist should match');

meeting_require_max_bytes('field', 'abc', 3);
expect_true(meeting_normalize_idempotency_key('meeting_record:test-1') === 'meeting_record:test-1', 'valid idempotency key should pass');

echo "[ok] bootstrap helper behavior\n";
