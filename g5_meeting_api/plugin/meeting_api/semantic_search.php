<?php
/**
 * GET /plugin/meeting_api/semantic_search.php?q=검색어&bo_table=free
 *
 * 게시판 의미 기반(시맨틱) 검색 페이지. 그누보드 기본 LIKE 검색과 달리
 * "환불 규정"으로 "반품 정책" 글을 찾는다.
 *
 * 동작:
 *  1. 검색어를 Ollama 임베딩 모델로 벡터화 (cURL)
 *  2. Python(semantic_index.py)이 만든 posts.db의 글 임베딩과 코사인 유사도 계산
 *  3. 유사한 글을 그누보드 게시글 링크와 함께 표시
 *
 * 상시 Python 서비스 없이 PHP만으로 검색한다. 인덱싱만 Python으로 주기 실행.
 * 방문자 공개용이므로 API 토큰을 요구하지 않는다(읽기 전용).
 */
require_once __DIR__ . '/config.php';

header('Content-Type: text/html; charset=utf-8');

$db_path = (string)meeting_SEMANTIC_DB_PATH;
$ollama_host = rtrim((string)meeting_SEMANTIC_OLLAMA_HOST, '/');
$embed_model = (string)meeting_SEMANTIC_EMBED_MODEL;
$min_score = (float)meeting_SEMANTIC_MIN_SCORE;
$top_k = (int)meeting_SEMANTIC_TOP_K;
$rate_per_min = (int)meeting_SEMANTIC_RATE_PER_MIN;
$max_query_len = (int)meeting_SEMANTIC_MAX_QUERY_LEN;

$q = isset($_GET['q']) ? trim((string)$_GET['q']) : '';
// 임베딩 부하/남용 방지: 검색어 길이 제한
if ($q !== '' && mb_strlen($q, 'UTF-8') > $max_query_len) {
    $q = mb_substr($q, 0, $max_query_len, 'UTF-8');
}
$bo_filter = isset($_GET['bo_table']) ? preg_replace('/[^A-Za-z0-9_]/', '', (string)$_GET['bo_table']) : '';

/** 무인증 공개 페이지 보호: IP당 분당 검색 횟수 제한 (파일 기반 슬라이딩 윈도우). */
function semantic_rate_limited(int $max_per_min): bool {
    if ($max_per_min <= 0) return false;
    $ip = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    $dir = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'meeting_sem_rl';
    if (!is_dir($dir)) @mkdir($dir, 0700, true);
    $file = $dir . DIRECTORY_SEPARATOR . hash('sha256', $ip) . '.json';
    $now = time();
    $hits = is_file($file) ? (json_decode((string)@file_get_contents($file), true) ?: []) : [];
    $hits = array_values(array_filter($hits, fn($t) => (int)$t > $now - 60));
    if (count($hits) >= $max_per_min) return true;
    $hits[] = $now;
    @file_put_contents($file, json_encode($hits), LOCK_EX);
    return false;
}

/** Ollama 임베딩 호출 + L2 정규화. 실패 시 null. */
function semantic_embed(string $host, string $model, string $text): ?array {
    $payload = json_encode(['model' => $model, 'input' => $text], JSON_UNESCAPED_UNICODE);
    $ch = curl_init("$host/api/embed");
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $payload,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 30,
    ]);
    $resp = curl_exec($ch);
    $err = curl_error($ch);
    curl_close($ch);
    if ($resp === false) return null;
    $data = json_decode($resp, true);
    $vec = $data['embeddings'][0] ?? null;
    if (!is_array($vec) || !$vec) return null;
    $norm = 0.0;
    foreach ($vec as $x) $norm += $x * $x;
    $norm = sqrt($norm);
    if ($norm > 0) {
        foreach ($vec as $i => $x) $vec[$i] = $x / $norm;
    }
    return $vec;
}

/** posts.db에서 글 단위 최고 코사인 점수로 상위 결과 반환. */
function semantic_search(string $db_path, string $model, array $qvec, string $bo_filter,
                        float $min_score, int $top_k): array {
    $pdo = new PDO("sqlite:$db_path");
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $sql = "SELECT bo_table, wr_id, subject, name, datetime, snippet, embedding
            FROM post_chunks WHERE model = :model";
    $params = [':model' => $model];
    if ($bo_filter !== '') {
        $sql .= " AND bo_table = :bo";
        $params[':bo'] = $bo_filter;
    }
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);

    $best = [];
    $n = count($qvec);
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        // float32 little-endian 복원 (numpy tobytes 호환), 1-indexed
        $emb = unpack('g*', $row['embedding']);
        if (!$emb || count($emb) < $n) continue;
        $score = 0.0;
        for ($i = 1; $i <= $n; $i++) $score += $qvec[$i - 1] * $emb[$i];
        if ($min_score > 0 && $score < $min_score) continue;
        $key = $row['bo_table'] . '#' . $row['wr_id'];
        if (!isset($best[$key]) || $score > $best[$key]['score']) {
            $best[$key] = [
                'score' => $score,
                'bo_table' => $row['bo_table'],
                'wr_id' => (int)$row['wr_id'],
                'subject' => $row['subject'],
                'name' => $row['name'],
                'datetime' => $row['datetime'],
                'snippet' => $row['snippet'],
            ];
        }
    }
    usort($best, fn($a, $b) => $b['score'] <=> $a['score']);
    return array_slice(array_values($best), 0, $top_k);
}

$error = '';
$results = [];
if ($q !== '') {
    if (semantic_rate_limited($rate_per_min)) {
        http_response_code(429);
        $error = '검색 요청이 너무 많습니다. 잠시 후 다시 시도하세요.';
    } elseif ($db_path === '' || !is_file($db_path)) {
        $error = '검색 인덱스가 설정되지 않았습니다. config.local.php에 meeting_SEMANTIC_DB_PATH를 지정하고 '
               . 'python semantic_index.py 로 인덱싱하세요.';
    } else {
        $qvec = semantic_embed($ollama_host, $embed_model, $q);
        if ($qvec === null) {
            $error = "임베딩 서버에 연결하지 못했습니다 ($ollama_host). Ollama 실행과 '$embed_model' 설치를 확인하세요.";
        } else {
            try {
                $results = semantic_search($db_path, $embed_model, $qvec, $bo_filter, $min_score, $top_k);
            } catch (Throwable $e) {
                $error = '검색 중 오류: ' . $e->getMessage();
            }
        }
    }
}

function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
// 게시글 링크: 이 파일은 plugin/meeting_api/ 에 있으므로 2단계 위가 그누보드 루트
$board_base = '../../bbs/board.php';
?>
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>게시판 의미 검색</title>
<style>
  body { font-family: -apple-system, "Malgun Gothic", sans-serif; max-width: 760px; margin: 0 auto; padding: 24px; color: #222; }
  h1 { font-size: 1.4rem; }
  .desc { color: #666; font-size: .9rem; margin-bottom: 16px; }
  form { display: flex; gap: 8px; margin-bottom: 20px; }
  input[type=text] { flex: 1; padding: 10px 12px; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; }
  button { padding: 10px 18px; font-size: 1rem; border: 0; border-radius: 6px; background: #2563eb; color: #fff; cursor: pointer; }
  .err { background: #fef2f2; color: #b91c1c; padding: 12px; border-radius: 6px; }
  .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; }
  .card a { font-size: 1.05rem; font-weight: 600; color: #1d4ed8; text-decoration: none; }
  .card .meta { color: #888; font-size: .8rem; margin: 4px 0; }
  .card .snip { color: #444; font-size: .9rem; }
  .score { float: right; color: #16a34a; font-size: .8rem; font-weight: 600; }
  .empty { color: #888; }
</style>
</head>
<body>
  <h1>🔎 게시판 의미 검색</h1>
  <div class="desc">단어가 정확히 일치하지 않아도 의미가 비슷한 글을 찾습니다. (예: "환불 규정" → "반품 정책")</div>
  <form method="get" action="">
    <input type="text" name="q" value="<?= h($q) ?>" placeholder="검색어를 입력하세요" autofocus>
    <?php if ($bo_filter !== ''): ?><input type="hidden" name="bo_table" value="<?= h($bo_filter) ?>"><?php endif; ?>
    <button type="submit">검색</button>
  </form>

  <?php if ($error): ?>
    <div class="err"><?= h($error) ?></div>
  <?php elseif ($q !== ''): ?>
    <?php if (!$results): ?>
      <p class="empty">"<?= h($q) ?>"와 의미가 비슷한 글을 찾지 못했습니다.</p>
    <?php else: ?>
      <p class="empty"><?= count($results) ?>건 (의미 유사도순)</p>
      <?php foreach ($results as $r): ?>
        <div class="card">
          <span class="score"><?= number_format($r['score'], 3) ?></span>
          <a href="<?= h($board_base) ?>?bo_table=<?= h($r['bo_table']) ?>&wr_id=<?= (int)$r['wr_id'] ?>">
            <?= h($r['subject']) ?>
          </a>
          <div class="meta">[<?= h($r['bo_table']) ?>] <?= h($r['name']) ?> · <?= h($r['datetime']) ?></div>
          <div class="snip"><?= h($r['snippet']) ?></div>
        </div>
      <?php endforeach; ?>
    <?php endif; ?>
  <?php endif; ?>
</body>
</html>
