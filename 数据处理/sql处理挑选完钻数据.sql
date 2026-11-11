USE [EDM]
GO

-- =============================================
-- 挑选完钻数据查询
-- 从渤海数据库中提取完钻测量数据
-- =============================================
SELECT 
    CD_POLICY.customer_name AS 公司名,
    CD_PROJECT_SOURCE.project_name AS 油田,
    CD_SITE_SOURCE.site_name AS 平台,
    CD_WELL_SOURCE.well_common_name AS 井名,
    CD_WELLBORE_T.wellbore_name AS WellBore_surevey,
    CD_DEFINITIVE_SURVEY_STATION_T.sequence_no AS No,
    ROUND((CD_DEFINITIVE_SURVEY_STATION_T.md - CD_VERTICAL_SECTION.tvd_start) * 0.3048000000012, 2) AS MD,
    ROUND(CD_DEFINITIVE_SURVEY_STATION_T.inclination, 2) AS INC,
    ROUND(CD_DEFINITIVE_SURVEY_STATION_T.azimuth - CD_SITE_SOURCE.convergence, 2) AS Azi,
    ROUND((CD_DEFINITIVE_SURVEY_STATION_T.tvd - CD_VERTICAL_SECTION.tvd_start) * 0.3048000000012, 2) AS TVD,
    ROUND((CD_DEFINITIVE_SURVEY_STATION_T.tvd) * 0.3048000000012, 2) AS TVDSS,
    -- 使用CROSS APPLY中计算好的NS和EW
    calc.NS,
    calc.EW,
    
    -- 派生计算
    ROUND(SQRT(calc.EW * calc.EW + calc.NS * calc.NS), 2) AS CLD,
    CASE WHEN calc.NS = 0 THEN 0 ELSE ROUND(ATAN(calc.EW / calc.NS) / 0.0174533, 2) END AS CLA,
    
    -- 坐标计算
    ROUND(well.geo_offset_north * 0.3048 + calc.NS, 2) AS North,
    ROUND(well.geo_offset_east * 0.3048 + calc.EW, 2) AS East,
    
    -- 经纬度度分秒格式
    lon_conv.degrees + '° ' + lon_conv.minutes + ''' ' + lon_conv.seconds + '"' AS 经度,
    lat_conv.degrees + '° ' + lat_conv.minutes + ''' ' + lat_conv.seconds + '"' AS 纬度
    
FROM CD_DEFINITIVE_SURVEY_STATION_T stat
INNER JOIN CD_WELLBORE_T bore ON bore.wellbore_id = stat.wellbore_id
INNER JOIN CD_WELL_SOURCE well ON well.well_id = stat.well_id
INNER JOIN CD_SITE_SOURCE site ON well.site_id = site.site_id
INNER JOIN CD_PROJECT_SOURCE proj ON site.project_id = proj.project_id
INNER JOIN CD_POLICY pol ON pol.policy_id = proj.policy_id
INNER JOIN CD_VERTICAL_SECTION vs ON vs.def_survey_header_id = stat.def_survey_header_id

-- NS/EW计算
CROSS APPLY (
    SELECT
        ROUND((stat.offset_east * SIN(site.convergence * 0.0174533) + stat.offset_north * COS(site.convergence * 0.0174533)) * 0.3048, 2) AS NS,
        ROUND((stat.offset_east * COS(site.convergence * 0.0174533) - stat.offset_north * SIN(site.convergence * 0.0174533)) * 0.3048, 2) AS EW
) AS calc

-- 经度转换
CROSS APPLY (
    SELECT 
        CASE WHEN well.geo_longitude >= 0 THEN 'E ' ELSE 'W ' END + CAST(ABS(FLOOR(well.geo_longitude)) AS VARCHAR) AS degrees,
        RIGHT('0' + CAST(FLOOR(ABS((well.geo_longitude - FLOOR(well.geo_longitude)) * 60)) AS VARCHAR), 2) AS minutes,
        CAST(ROUND(ABS((((well.geo_longitude - FLOOR(well.geo_longitude)) * 60) - FLOOR((well.geo_longitude - FLOOR(well.geo_longitude)) * 60)) * 60, 3) AS VARCHAR) AS seconds
) AS lon_conv

-- 纬度转换
CROSS APPLY (
    SELECT 
        CASE WHEN well.geo_latitude >= 0 THEN 'N ' ELSE 'S ' END + CAST(ABS(FLOOR(well.geo_latitude)) AS VARCHAR) AS degrees,
        RIGHT('0' + CAST(FLOOR(ABS((well.geo_latitude - FLOOR(well.geo_latitude)) * 60)) AS VARCHAR), 2) AS minutes,
        CAST(ROUND(ABS((((well.geo_latitude - FLOOR(well.geo_latitude)) * 60) - FLOOR((well.geo_latitude - FLOOR(well.geo_latitude)) * 60)) * 60, 3) AS VARCHAR) AS seconds
) AS lat_conv

-- 筛选条件
WHERE 
    stat.sequence_no IS NOT NULL
    AND stat.md IS NOT NULL
    AND stat.inclination IS NOT NULL
    AND stat.azimuth IS NOT NULL
    AND calc.NS IS NOT NULL
    AND well.geo_longitude IS NOT NULL
    AND well.geo_latitude IS NOT NULL
    AND site.site_id NOT IN (SELECT site_id FROM DP_TEMPLATE)

-- 排序
ORDER BY 
    公司名, 油田, 平台, 井名, WellBore_surevey, No
GO
