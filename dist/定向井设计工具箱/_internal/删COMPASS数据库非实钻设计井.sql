/*===========================================================================
  文件：删COMPASS数据库非实钻设计井.sql
  适用：COMPASS 5000 / EDM（SQL Server 实例 .\EDM5000，数据库 EDM）
  对应：删xml格式中非实钻数据(应用场景外挂设计).py

  本版按“测斜头 -> 井眼 -> 井”三级自下而上清理：

    第 1 级  删除所有 phase <> 'ACTUAL' 的 CD_DEFINITIVE_SURVEY_HEADER_T
             （PLAN、PROTOTYPE、空值都算非实钻；ACTUAL 保留）
    第 2 级  如果某个井眼的所有定稿测斜头都不是 ACTUAL，删除该井眼
             （CD_WELLBORE_T；测斜站、设计、BHA、套管等子表随外键级联删除）
    第 3 级  如果某口井的所有井眼里的定稿测斜头全不是 ACTUAL，删除该井
             （CD_WELL_SOURCE；其余子表随外键级联删除）

  安全阀：
    - 没有任何定稿测斜头的井眼/井，默认不删（@DeleteNoSurveyObjects = 0），
      避免把“还没录测斜”的实钻井误删。
    - @Execute = 0 只预览，不删数据。
    - 删除头之前，把 CD_SCENARIO_T / DM_WELL_PLAN_HOLE_SECT_T /
      DP_PROJECT_TARGET 里的相关引用置空，并删掉已失效的 DP_ANTICOL_T
      防碰行，避免悬空 ID。
    - 整个删除过程在一个事务里，任何一步失败自动回滚。

  用法：
    - SSMS 打开本文件，先填 @project_name（或 @project_id），
      @Execute 保持 0 执行一次，核对三个层级的清单；
    - 确认无误后把 @Execute 改为 1，再执行。
    - 命令行：sqlcmd -S .\EDM5000 -d EDM -E -f 65001 ^
              -i "删COMPASS数据库非实钻设计井.sql"

  重要：
    - 执行前先完整备份 EDM 数据库！
    - 建议先在小项目（如 Test Well #1 - SPE 67616）上试跑。
    - 默认按单个项目处理，避免误删其他项目。
===========================================================================*/

USE [EDM];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

/*---------------------------------------------------------------------------
  1. 参数
---------------------------------------------------------------------------*/
DECLARE @project_id    char(10)     = NULL;   -- 项目ID，例如 'GBz9TR5qhJ'
DECLARE @project_name  nvarchar(50) = NULL;   -- 项目名，例如 N'YueDong'；@project_id 为空时使用
DECLARE @all_projects  bit          = 0;      -- 1 = 所有项目（危险，默认 0）

DECLARE @Execute       bit          = 0;      -- 0 = 预览；1 = 真正删除

DECLARE @DeleteNoSurveyObjects bit  = 0;
-- 0（推荐）= 没有任何定稿测斜头的井眼/井不删
-- 1         = 把“完全没有测斜头”也视为“全不是 ACTUAL”，一并删除（危险）

DECLARE @DeleteTargets bit          = 1;      -- 1 = 清理只属于被删井/井眼的靶点
DECLARE @DeleteHistory bit          = 1;      -- 1 = 清理变更历史/Explorer 中的井定位串
DECLARE @NullDanglingRefs bit       = 1;      -- 1 = 清理场景/设计/靶点/防碰里对已删头的引用

/*---------------------------------------------------------------------------
  2. 解析项目
---------------------------------------------------------------------------*/
DECLARE @pid char(10);

IF @all_projects = 0
BEGIN
    IF @project_id IS NOT NULL
        SET @pid = @project_id;
    ELSE IF @project_name IS NOT NULL
        SELECT TOP (1) @pid = project_id
        FROM dbo.CD_PROJECT_SOURCE
        WHERE project_name COLLATE DATABASE_DEFAULT = @project_name
        ORDER BY project_id;

    IF @pid IS NULL
    BEGIN
        PRINT N'未指定项目。可用项目如下，请把 @project_id 或 @project_name 填上后重跑：';

        SELECT project_id, project_name, create_date, update_date
        FROM dbo.CD_PROJECT_SOURCE
        ORDER BY project_name;

        RETURN;
    END
END

/*---------------------------------------------------------------------------
  3. 生成三级删除清单（全部基于删除前的数据计算）
---------------------------------------------------------------------------*/
IF OBJECT_ID('tempdb..#del_headers') IS NOT NULL DROP TABLE #del_headers;
IF OBJECT_ID('tempdb..#del_wellbores') IS NOT NULL DROP TABLE #del_wellbores;
IF OBJECT_ID('tempdb..#del_wells') IS NOT NULL DROP TABLE #del_wells;
IF OBJECT_ID('tempdb..#del_wellbores_all') IS NOT NULL DROP TABLE #del_wellbores_all;

CREATE TABLE #del_headers
(
    -- EDM 的 ID 列是 Latin1_General_CS_AS，临时表在 tempdb 默认是
    -- Chinese_PRC_CI_AS，不显式指定会在 JOIN 时报 collation conflict。
    well_id              char(10)     COLLATE Latin1_General_CS_AS NOT NULL,
    wellbore_id          char(10)     COLLATE Latin1_General_CS_AS NOT NULL,
    def_survey_header_id char(5)      COLLATE Latin1_General_CS_AS NOT NULL,
    phase                nvarchar(20) COLLATE Latin1_General_CS_AS NULL,
    well_common_name     nvarchar(60) COLLATE Latin1_General_CS_AS NULL,
    wellbore_name        nvarchar(120) COLLATE Latin1_General_CS_AS NULL,
    CONSTRAINT PK_del_headers PRIMARY KEY (well_id, wellbore_id, def_survey_header_id)
);

CREATE TABLE #del_wellbores
(
    well_id          char(10)      COLLATE Latin1_General_CS_AS NOT NULL,
    wellbore_id      char(10)      COLLATE Latin1_General_CS_AS NOT NULL,
    well_common_name nvarchar(60)  COLLATE Latin1_General_CS_AS NULL,
    wellbore_name    nvarchar(120) COLLATE Latin1_General_CS_AS NULL,
    CONSTRAINT PK_del_wellbores PRIMARY KEY (wellbore_id)
);

CREATE TABLE #del_wells
(
    well_id          char(10)     COLLATE Latin1_General_CS_AS NOT NULL,
    well_common_name nvarchar(60) COLLATE Latin1_General_CS_AS NULL,
    site_id          char(10)     COLLATE Latin1_General_CS_AS NULL,
    CONSTRAINT PK_del_wells PRIMARY KEY (well_id)
);

CREATE TABLE #del_wellbores_all
(
    wellbore_id char(10) COLLATE Latin1_General_CS_AS NOT NULL PRIMARY KEY
);

/* 3.1 第 1 级：非 ACTUAL 的定稿测斜头 */
INSERT INTO #del_headers
    (well_id, wellbore_id, def_survey_header_id, phase,
     well_common_name, wellbore_name)
SELECT
    h.well_id,
    h.wellbore_id,
    h.def_survey_header_id,
    h.phase,
    w.well_common_name,
    wb.wellbore_name
FROM dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
JOIN dbo.CD_WELL_SOURCE w
    ON w.well_id = h.well_id
JOIN dbo.CD_SITE_SOURCE s
    ON s.site_id = w.site_id
LEFT JOIN dbo.CD_WELLBORE_T wb
    ON wb.wellbore_id = h.wellbore_id
WHERE (@all_projects = 1 OR s.project_id COLLATE DATABASE_DEFAULT = @pid)
  AND ISNULL(h.phase, N'') <> N'ACTUAL';

/* 3.2 第 2 级：没有任何 ACTUAL 头的井眼 */
INSERT INTO #del_wellbores
    (well_id, wellbore_id, well_common_name, wellbore_name)
SELECT
    wb.well_id,
    wb.wellbore_id,
    w.well_common_name,
    wb.wellbore_name
FROM dbo.CD_WELLBORE_T wb
JOIN dbo.CD_WELL_SOURCE w
    ON w.well_id = wb.well_id
JOIN dbo.CD_SITE_SOURCE s
    ON s.site_id = w.site_id
WHERE (@all_projects = 1 OR s.project_id COLLATE DATABASE_DEFAULT = @pid)
  AND NOT EXISTS (
        SELECT 1
        FROM dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
        WHERE h.wellbore_id = wb.wellbore_id
          AND ISNULL(h.phase, N'') = N'ACTUAL')
  AND (@DeleteNoSurveyObjects = 1
       OR EXISTS (
            SELECT 1
            FROM dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
            WHERE h.wellbore_id = wb.wellbore_id));

/* 3.3 第 3 级：所有井眼都没有 ACTUAL 头的井 */
INSERT INTO #del_wells
    (well_id, well_common_name, site_id)
SELECT
    w.well_id,
    w.well_common_name,
    w.site_id
FROM dbo.CD_WELL_SOURCE w
JOIN dbo.CD_SITE_SOURCE s
    ON s.site_id = w.site_id
WHERE (@all_projects = 1 OR s.project_id COLLATE DATABASE_DEFAULT = @pid)
  AND NOT EXISTS (
        SELECT 1
        FROM dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
        WHERE h.well_id = w.well_id
          AND ISNULL(h.phase, N'') = N'ACTUAL')
  AND (@DeleteNoSurveyObjects = 1
       OR EXISTS (
            SELECT 1
            FROM dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
            WHERE h.well_id = w.well_id));

/* 3.4 本次会被删掉的井眼全集：
       显式删除的井眼 + 整口井被删时它下面的所有井眼 */
INSERT INTO #del_wellbores_all (wellbore_id)
SELECT wellbore_id FROM #del_wellbores
UNION
SELECT wb.wellbore_id
FROM dbo.CD_WELLBORE_T wb
JOIN #del_wells d
    ON d.well_id = wb.well_id;

/*---------------------------------------------------------------------------
  4. 预览
---------------------------------------------------------------------------*/
SELECT
    @pid AS project_id,
    (SELECT project_name FROM dbo.CD_PROJECT_SOURCE
      WHERE project_id COLLATE DATABASE_DEFAULT = @pid) AS project_name,
    (SELECT COUNT(*) FROM #del_headers)       AS headers_to_delete,
    (SELECT COUNT(*) FROM #del_wellbores)     AS wellbores_to_delete,
    (SELECT COUNT(*) FROM #del_wells)         AS wells_to_delete;

SELECT
    N'HEADER' AS delete_level,
    d.well_common_name, d.well_id,
    d.wellbore_name, d.wellbore_id,
    d.def_survey_header_id, d.phase
FROM #del_headers d
ORDER BY d.well_common_name, d.wellbore_name, d.def_survey_header_id;

SELECT
    N'WELLBORE' AS delete_level,
    d.well_common_name, d.well_id,
    d.wellbore_name, d.wellbore_id
FROM #del_wellbores d
ORDER BY d.well_common_name, d.wellbore_name;

SELECT
    N'WELL' AS delete_level,
    d.well_common_name, d.well_id, d.site_id
FROM #del_wells d
ORDER BY d.well_common_name, d.well_id;

IF NOT EXISTS (SELECT 1 FROM #del_headers)
   AND NOT EXISTS (SELECT 1 FROM #del_wellbores)
   AND NOT EXISTS (SELECT 1 FROM #del_wells)
BEGIN
    PRINT N'没有符合条件的非实钻对象，未删除任何数据。';
    RETURN;
END

IF @Execute = 0
BEGIN
    PRINT N'当前为预览模式，未删除任何数据。确认无误后把 @Execute 改为 1 再执行。';
    RETURN;
END

/*---------------------------------------------------------------------------
  5. 执行删除（单事务）
---------------------------------------------------------------------------*/
BEGIN TRY
    BEGIN TRANSACTION;

    /* 5.1 不再写数据库审计表，删除明细由工具箱导出为 Excel */
    DECLARE @run_id uniqueidentifier = NEWID();

    /* 5.2 删除前的硬校验：确认清单里没有 ACTUAL 头 */
    IF EXISTS (
        SELECT 1
        FROM #del_headers d
        WHERE ISNULL(d.phase, N'') = N'ACTUAL')
        RAISERROR(N'内部校验失败：待删表里出现 ACTUAL 头，已回滚。', 16, 1);

    IF EXISTS (
        SELECT 1
        FROM #del_wellbores d
        JOIN dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
            ON h.wellbore_id = d.wellbore_id
        WHERE ISNULL(h.phase, N'') = N'ACTUAL')
        RAISERROR(N'内部校验失败：待删井眼里仍有 ACTUAL 头，已回滚。', 16, 1);

    IF EXISTS (
        SELECT 1
        FROM #del_wells d
        JOIN dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
            ON h.well_id = d.well_id
        WHERE ISNULL(h.phase, N'') = N'ACTUAL')
        RAISERROR(N'内部校验失败：待删井里仍有 ACTUAL 头，已回滚。', 16, 1);

    /* 5.3 清空对“即将被删的测斜头”的引用（这些表没有外键，不会级联） */
    IF @NullDanglingRefs = 1
    BEGIN
        UPDATE t
        SET drill_def_survey_header_id = NULL
        FROM dbo.DP_PROJECT_TARGET t
        JOIN #del_headers d
            ON d.wellbore_id          = t.drill_wellbore_id
           AND d.def_survey_header_id = t.drill_def_survey_header_id;

        UPDATE s
        SET def_survey_header_id = NULL
        FROM dbo.CD_SCENARIO_T s
        JOIN #del_headers d
            ON d.wellbore_id          = s.wellbore_id
           AND d.def_survey_header_id = s.def_survey_header_id;

        UPDATE p
        SET def_survey_header_id = NULL
        FROM dbo.DM_WELL_PLAN_HOLE_SECT_T p
        JOIN #del_headers d
            ON d.wellbore_id          = p.wellbore_id
           AND d.def_survey_header_id = p.def_survey_header_id;

        -- 邻井防碰：offset 端的头/井眼/井被删后，这一行防碰数据已经失效。
        -- 这三个 offset 列都是 NOT NULL，不能置空，只能删行。
        DELETE a
        FROM dbo.DP_ANTICOL_T a
        WHERE EXISTS (
                SELECT 1
                FROM #del_headers d
                WHERE d.wellbore_id          = a.offset_wellbore_id
                  AND d.def_survey_header_id = a.offset_def_survey_header_id)
           OR a.offset_wellbore_id IN (SELECT wellbore_id FROM #del_wellbores_all)
           OR a.offset_well_id     IN (SELECT well_id     FROM #del_wells);
    END

    /* 5.4 先删“井/井眼-靶点”链接，这些外键指向 DP_PROJECT_TARGET，不随井级联 */
    DELETE l
    FROM dbo.CD_PROJECT_TARGET_WB_LINK_T l
    JOIN #del_wellbores_all a
        ON a.wellbore_id = l.wellbore_id;

    DELETE l
    FROM dbo.CD_PROJECT_TARGET_WB_LINK_T l
    JOIN #del_wells d
        ON d.well_id = l.well_id;

    DELETE l
    FROM dbo.CD_PROJ_TARG_WELL_LINK l
    JOIN #del_wells d
        ON d.well_id = l.well_id;

    DELETE l
    FROM dbo.CD_PROJ_TARG_SCENARIO_LINK l
    JOIN #del_wellbores_all a
        ON a.wellbore_id = l.wellbore_id;

    DELETE l
    FROM dbo.CD_PROJ_TARG_SCENARIO_LINK l
    JOIN #del_wells d
        ON d.well_id = l.well_id;

    /* 5.5 清理只属于被删井/井眼的靶点；仍被其他对象引用的靶点保留 */
    IF @DeleteTargets = 1
    BEGIN
        DELETE t
        FROM dbo.DP_PROJECT_TARGET t
        WHERE (@all_projects = 1 OR t.project_id COLLATE DATABASE_DEFAULT = @pid)
          AND (t.drill_well_id IN (SELECT well_id FROM #del_wells)
               OR t.drill_wellbore_id IN (SELECT wellbore_id FROM #del_wellbores_all))
          AND NOT EXISTS (
                SELECT 1
                FROM dbo.CD_PROJECT_TARGET_WB_LINK_T l
                WHERE l.project_id = t.project_id
                  AND l.project_target_id = t.project_target_id)
          AND NOT EXISTS (
                SELECT 1
                FROM dbo.CD_PROJ_TARG_WELL_LINK l
                WHERE l.project_id = t.project_id
                  AND l.project_target_id = t.project_target_id)
          AND NOT EXISTS (
                SELECT 1
                FROM dbo.CD_PROJ_TARG_SCENARIO_LINK l
                WHERE l.project_id = t.project_id
                  AND l.project_target_id = t.project_target_id)
          AND NOT EXISTS (
                SELECT 1
                FROM dbo.CD_SURVEY_STATION_T st
                WHERE st.project_id = t.project_id
                  AND st.project_target_id = t.project_target_id);

        -- 仍保留的靶点：断开对被删井/井眼的引用
        UPDATE t
        SET drill_well_id = NULL,
            drill_wellbore_id = NULL,
            drill_def_survey_header_id = NULL
        FROM dbo.DP_PROJECT_TARGET t
        WHERE (@all_projects = 1 OR t.project_id COLLATE DATABASE_DEFAULT = @pid)
          AND t.drill_well_id IN (SELECT well_id FROM #del_wells);

        UPDATE t
        SET drill_wellbore_id = NULL,
            drill_def_survey_header_id = NULL
        FROM dbo.DP_PROJECT_TARGET t
        WHERE t.drill_wellbore_id IN (SELECT wellbore_id FROM #del_wellbores_all);
    END

    /* 5.6 清理没有外键的“定位串”表（变更历史 / Explorer / 多段线） */
    IF @DeleteHistory = 1
    BEGIN
        DELETE j
        FROM dbo.CD_CHANGE_HISTORY_JOURNAL j
        WHERE EXISTS (
                SELECT 1 FROM #del_wells d
                WHERE j.parent_locator LIKE '%well_id=(' + d.well_id + ')%'
                   OR j.item_locator   LIKE '%well_id=(' + d.well_id + ')%')
           OR EXISTS (
                SELECT 1 FROM #del_wellbores_all b
                WHERE j.parent_locator LIKE '%wellbore_id=(' + b.wellbore_id + ')%'
                   OR j.item_locator   LIKE '%wellbore_id=(' + b.wellbore_id + ')%')
           OR EXISTS (
                SELECT 1 FROM #del_headers h
                WHERE j.parent_locator LIKE '%def_survey_header_id=(' + h.def_survey_header_id + ')%'
                   OR j.item_locator   LIKE '%def_survey_header_id=(' + h.def_survey_header_id + ')%');

        DELETE f
        FROM dbo.CD_EXPLORER_FOLDER f
        WHERE EXISTS (
                SELECT 1 FROM #del_wells d
                WHERE f.parent_locator LIKE '%well_id=(' + d.well_id + ')%')
           OR EXISTS (
                SELECT 1 FROM #del_wellbores_all b
                WHERE f.parent_locator LIKE '%wellbore_id=(' + b.wellbore_id + ')%');

        DELETE m
        FROM dbo.CD_EXPLORER_FOLDER_MEMBER m
        WHERE EXISTS (
                SELECT 1 FROM #del_wells d
                WHERE m.member_locator LIKE '%well_id=(' + d.well_id + ')%')
           OR EXISTS (
                SELECT 1 FROM #del_wellbores_all b
                WHERE m.member_locator LIKE '%wellbore_id=(' + b.wellbore_id + ')%');

        DELETE ph
        FROM dbo.CD_POLYLINE_HEADER ph
        WHERE EXISTS (
                SELECT 1 FROM #del_wells d
                WHERE ph.attachment_locator LIKE '%well_id=(' + d.well_id + ')%')
           OR EXISTS (
                SELECT 1 FROM #del_wellbores_all b
                WHERE ph.attachment_locator LIKE '%wellbore_id=(' + b.wellbore_id + ')%');
    END

    /* 5.7 唯一的 NO ACTION 关联，先手工清掉，避免挡住宿主表删除 */
    IF OBJECT_ID('dbo.DM_EVENT_COMPLETION_LINK_T') IS NOT NULL
    BEGIN
        DELETE l
        FROM dbo.DM_EVENT_COMPLETION_LINK_T l
        JOIN #del_wells d
            ON d.well_id = l.well_id;

        DELETE l
        FROM dbo.DM_EVENT_COMPLETION_LINK_T l
        JOIN #del_wellbores_all a
            ON a.wellbore_id = l.wellbore_id;
    END

    /* 5.8 第 1 级：删除非 ACTUAL 的定稿测斜头。
           测斜站、设计程序、垂直剖面、防碰、注释等随外键级联删除。 */
    DELETE h
    FROM dbo.CD_DEFINITIVE_SURVEY_HEADER_T h
    JOIN #del_headers d
        ON d.well_id              = h.well_id
       AND d.wellbore_id          = h.wellbore_id
       AND d.def_survey_header_id = h.def_survey_header_id;

    /* 5.9 第 2 级：删除没有任何 ACTUAL 头的井眼。
           该井眼下的 BHA、套管、固井、完井、地质等子表随外键级联删除。 */
    DELETE wb
    FROM dbo.CD_WELLBORE_T wb
    JOIN #del_wellbores d
        ON d.wellbore_id = wb.wellbore_id;

    /* 5.10 第 3 级：删除所有井眼都没有 ACTUAL 头的井。
            剩余子表随外键级联删除。 */
    DELETE w
    FROM dbo.CD_WELL_SOURCE w
    JOIN #del_wells d
        ON d.well_id = w.well_id;

    /* 5.11 兜底：清理没有外键、但带 well_id 的残留表 */
    DECLARE @sql nvarchar(max) = N'';

    SELECT @sql = @sql
        + N'DELETE FROM '
        + QUOTENAME(OBJECT_SCHEMA_NAME(t.object_id)) + N'.' + QUOTENAME(t.name)
        + N' WHERE well_id COLLATE DATABASE_DEFAULT'
        + N' IN (SELECT well_id COLLATE DATABASE_DEFAULT FROM #del_wells);'
        + CHAR(13) + CHAR(10)
    FROM sys.tables t
    WHERE t.is_ms_shipped = 0
      AND t.name <> 'CD_WELL_SOURCE'
      AND t.name NOT IN ('ZZ_DELETE_DESIGN_SURVEY_LOG', 'ZZ_DELETE_DESIGN_WELL_LOG')
      AND EXISTS (
            SELECT 1
            FROM sys.columns c
            WHERE c.object_id = t.object_id
              AND c.name = 'well_id')
    ORDER BY t.name;

    IF LEN(@sql) > 0
        EXEC sp_executesql @sql;

    /* 5.12 兜底：清理没有外键、但带 wellbore_id 的残留表
            （DM_DAILY、CD_WELLHEAD、报表等大量表属于这一类） */
    SET @sql = N'';

    SELECT @sql = @sql
        + N'DELETE FROM '
        + QUOTENAME(OBJECT_SCHEMA_NAME(t.object_id)) + N'.' + QUOTENAME(t.name)
        + N' WHERE wellbore_id COLLATE DATABASE_DEFAULT'
        + N' IN (SELECT wellbore_id COLLATE DATABASE_DEFAULT FROM #del_wellbores_all);'
        + CHAR(13) + CHAR(10)
    FROM sys.tables t
    WHERE t.is_ms_shipped = 0
      AND t.name <> 'CD_WELLBORE_T'
      AND t.name NOT IN ('ZZ_DELETE_DESIGN_SURVEY_LOG', 'ZZ_DELETE_DESIGN_WELL_LOG')
      AND EXISTS (
            SELECT 1
            FROM sys.columns c
            WHERE c.object_id = t.object_id
              AND c.name = 'wellbore_id')
    ORDER BY t.name;

    IF LEN(@sql) > 0
        EXEC sp_executesql @sql;

    COMMIT TRANSACTION;

    DECLARE @cnt_header   int = (SELECT COUNT(*) FROM #del_headers);
    DECLARE @cnt_wellbore int = (SELECT COUNT(*) FROM #del_wellbores);
    DECLARE @cnt_well     int = (SELECT COUNT(*) FROM #del_wells);

    PRINT N'完成：项目=' + ISNULL(@pid, N'<全部>')
        + N'，删除测斜头 ' + CAST(@cnt_header AS nvarchar(20))
        + N' 个，井眼 ' + CAST(@cnt_wellbore AS nvarchar(20))
        + N' 个，井 ' + CAST(@cnt_well AS nvarchar(20))
        + N' 口，run_id=' + CAST(@run_id AS nvarchar(36));
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0
        ROLLBACK TRANSACTION;

    DECLARE @msg nvarchar(2048) =
        N'已回滚，未删除任何数据。错误：' + ERROR_MESSAGE();

    RAISERROR(@msg, 16, 1);
END CATCH
GO

/*===========================================================================
  附：原 Python 中未在主流程调用的功能，如确实需要，按项目/公司限定后再启用

  -- 1) CD_PROJECT 坐标系替换
  UPDATE dbo.CD_PROJECT_SOURCE
  SET geo_system_id = N'CGCS2000_UTM120',
      geo_zone_id   = N'BoHai',
      geo_datum_id  = N'CGCS2000'
  WHERE project_id = @pid
    AND geo_zone_id = N'Zone20, North 117E to 123E';

  -- 2) DP_ACRULE 只保留指定 ID（注意：这是公司 policy 级数据，
  --    会影响到该公司下所有项目，务必先按 policy_id 限定）
  DELETE a
  FROM dbo.DP_ACRULE a
  WHERE a.policy_id = (
        SELECT policy_id
        FROM dbo.CD_PROJECT_SOURCE
        WHERE project_id = @pid)
    AND a.acrule_id NOT IN ('clUsh', 'kXivj', 'M24PK');

  -- 3) 清理“没有被任何剩余测斜引用”的靶点
  DELETE t
  FROM dbo.DP_PROJECT_TARGET t
  WHERE t.project_id = @pid
    AND NOT EXISTS (
        SELECT 1
        FROM dbo.CD_SURVEY_STATION_T s
        WHERE s.project_id = t.project_id
          AND s.project_target_id = t.project_target_id);

  -- 注意：CD_SURVEY_TOOL、DP_TOOL_TERM、CD_BHA_COMP 等是公司 policy
  -- 或井眼级模板数据，不是单井数据，不建议照 XML 的做法整表删除。
===========================================================================*/
