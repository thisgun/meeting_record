-- metting → meeting 게시판/테이블 마이그레이션 (안전한 방식)
SET SESSION sql_mode = '';

-- 1) 'meeting' 게시판이 없으면 'meeting' 게시판을 임시 테이블 거쳐 복사
CREATE TEMPORARY TABLE _tmp_meeting LIKE g5_board;
INSERT INTO _tmp_meeting SELECT * FROM g5_board WHERE bo_table = 'meeting';
UPDATE _tmp_meeting SET bo_table = 'meeting';
INSERT IGNORE INTO g5_board SELECT * FROM _tmp_meeting;
DROP TEMPORARY TABLE _tmp_meeting;

-- 2) g5_write_meeting 테이블 생성 (없을 때만)
CREATE TABLE IF NOT EXISTS g5_write_meeting LIKE g5_write_meeting;

-- 3) g5_write_meeting의 데이터를 g5_write_meeting으로 복사 (중복 wr_id는 스킵)
INSERT IGNORE INTO g5_write_meeting
SELECT * FROM g5_write_meeting;

-- 4) g5_board_new (새글 알림)에서 bo_table = 'meeting' → 'meeting'
UPDATE g5_board_new SET bo_table = 'meeting' WHERE bo_table = 'meeting';

-- 5) 결과 확인
SELECT '== g5_board:meeting ==' AS info;
SELECT bo_table, bo_subject FROM g5_board WHERE bo_table = 'meeting';
SELECT '== 행 수 비교 ==' AS info;
SELECT 'meeting' AS tbl, COUNT(*) AS cnt FROM g5_write_meeting
UNION ALL SELECT 'metting (원본)' AS tbl, COUNT(*) AS cnt FROM g5_write_meeting;
