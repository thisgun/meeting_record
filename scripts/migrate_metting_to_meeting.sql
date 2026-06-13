-- metting → meeting 게시판/테이블 마이그레이션 (원본 보존)
-- 실행 전 MariaDB/MySQL 백업을 권장합니다.
SET SESSION sql_mode = '';

DELIMITER //
CREATE PROCEDURE _meeting_migration_precheck()
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = DATABASE()
           AND table_name = 'g5_board'
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'g5_board table not found';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM g5_board
         WHERE bo_table = 'metting'
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'source board bo_table=metting not found';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = DATABASE()
           AND table_name = 'g5_write_metting'
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'source table g5_write_metting not found';
    END IF;
END//
DELIMITER ;

CALL _meeting_migration_precheck();
DROP PROCEDURE _meeting_migration_precheck;

-- 1) 'metting' 게시판 설정을 'meeting' 게시판으로 복사 (이미 있으면 유지)
CREATE TEMPORARY TABLE _tmp_meeting_board LIKE g5_board;
INSERT INTO _tmp_meeting_board SELECT * FROM g5_board WHERE bo_table = 'metting';
UPDATE _tmp_meeting_board SET bo_table = 'meeting';
INSERT IGNORE INTO g5_board SELECT * FROM _tmp_meeting_board;
DROP TEMPORARY TABLE _tmp_meeting_board;

-- 2) g5_write_metting 구조를 기준으로 g5_write_meeting 테이블 생성 (없을 때만)
CREATE TABLE IF NOT EXISTS g5_write_meeting LIKE g5_write_metting;

-- 3) 기존 글/댓글을 새 테이블로 복사 (중복 wr_id는 스킵)
INSERT IGNORE INTO g5_write_meeting
SELECT * FROM g5_write_metting;

-- 4) g5_board_new (새글 알림)의 게시판 코드도 새 이름으로 복사
CREATE TEMPORARY TABLE _tmp_meeting_board_new AS
SELECT 'meeting' AS bo_table, wr_id, wr_parent, bn_datetime, mb_id
  FROM g5_board_new
 WHERE bo_table = 'metting';

DELETE t
  FROM _tmp_meeting_board_new AS t
  JOIN g5_board_new AS existing
    ON existing.bo_table = t.bo_table
   AND existing.wr_id = t.wr_id
   AND existing.wr_parent = t.wr_parent;

INSERT INTO g5_board_new (bo_table, wr_id, wr_parent, bn_datetime, mb_id)
SELECT bo_table, wr_id, wr_parent, bn_datetime, mb_id
  FROM _tmp_meeting_board_new;

DROP TEMPORARY TABLE _tmp_meeting_board_new;

-- 5) 결과 확인
SELECT '== g5_board:meeting ==' AS info;
SELECT bo_table, bo_subject FROM g5_board WHERE bo_table = 'meeting';
SELECT '== 행 수 비교 ==' AS info;
SELECT 'meeting' AS tbl, COUNT(*) AS cnt FROM g5_write_meeting
UNION ALL SELECT 'metting (원본)' AS tbl, COUNT(*) AS cnt FROM g5_write_metting;
