/*===============================================================
  数据库维护脚本 - BH
  适用版本：SQL Server 2016 及以上
  功能：查询表大小、清理历史数据、重建索引、收缩数据库
===============================================================*/

USE BH;
GO

--===============================================================
-- 0. 查看数据库文件信息（请先执行此查询获取正确的文件名）
--===============================================================
SELECT 
    name AS FileName,
    physical_name AS PhysicalPath,
    type_desc AS FileType,
    CAST(size * 8.0 / 1024 AS DECIMAL(10,2)) AS SizeMB
FROM sys.database_files;
GO

--===============================================================
-- 1. 查询数据库中各表的占用空间（按大小降序排列）
--===============================================================
SELECT 
    t.NAME AS TableName,
    s.Name AS SchemaName,
    p.rows AS RowCounts,
    CAST(SUM(a.total_pages) * 8.0 / 1024 AS DECIMAL(10,2)) AS TotalSpaceMB, 
    CAST(SUM(a.used_pages) * 8.0 / 1024 AS DECIMAL(10,2)) AS UsedSpaceMB, 
    CAST((SUM(a.total_pages) - SUM(a.used_pages)) * 9.0 / 1024 AS DECIMAL(10,2)) AS UnusedSpaceMB
FROM 
    sys.tables t
INNER JOIN sys.indexes i ON t.OBJECT_ID = i.object_id
INNER JOIN sys.partitions p ON i.object_id = p.OBJECT_ID AND i.index_id = p.index_id
INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
LEFT OUTER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE t.is_ms_shipped = 0
GROUP BY t.Name, s.Name, p.Rows
ORDER BY TotalSpaceMB DESC;
GO

--===============================================================
-- 2. 清理历史数据（删除指定时间之前的数据）
--===============================================================

-- 2.1 清理 CD_CHANGE_HISTORY_JOURNAL 表（1年前的数据）
DELETE FROM CD_CHANGE_HISTORY_JOURNAL 
WHERE change_date < DATEADD(MONTH, -3, GETDATE());

-- 2.2 清理 SYNC_CHANGE_LOG 表（约4个月前的数据）
DELETE FROM SYNC_CHANGE_LOG 
WHERE MODIFIED_TIME < DATEADD(MONTH, -1, GETDATE());

-- 可选：使用 TRUNCATE 清空整表（更高效，但不记录日志）
-- TRUNCATE TABLE CD_CHANGE_HISTORY_JOURNAL;
-- TRUNCATE TABLE SYNC_CHANGE_LOG;
GO

--===============================================================
-- 3. 重建索引（减少碎片，提升查询性能）
--===============================================================
ALTER INDEX ALL ON CD_CHANGE_HISTORY_JOURNAL REBUILD;
ALTER INDEX ALL ON SYNC_CHANGE_LOG REBUILD;
GO

--===============================================================
-- 4. 收缩事务日志文件
--===============================================================
DBCC SHRINKFILE (N'edm_Log', 100);  -- 收缩到 100MB
GO

--===============================================================
-- 5. 收缩数据文件
--===============================================================
DBCC SHRINKFILE (N'edm_Data', 0);  -- 收缩到最小可能大小
GO

-- 如果上述命令失败，可通过 SSMS 界面操作：
-- 右键数据库 -> Tasks -> Shrink -> Files

--===============================================================
-- 附录：查看表结构信息
--===============================================================
EXEC sp_help 'CD_CHANGE_HISTORY_JOURNAL';
EXEC sp_help 'SYNC_CHANGE_LOG';