USE [BoHai]
GO

-- =============================================
-- 挑选完钻数据查询
-- 从渤海数据库中提取完钻测量数据
-- =============================================
SELECT * FROM (
    SELECT 
        CD_POLICY.customer_name AS 公司名,
        CD_PROJECT_SOURCE.project_name AS 油田,
        CD_PROJECT_SOURCE.project_id AS 油田ID,
        CD_SITE_SOURCE.site_name AS 平台,
	    CD_SITE_SOURCE.site_id AS 平台id,
        CD_WELL_SOURCE.well_common_name AS 井名,
	    CD_WELL_SOURCE.well_id AS 井名id,
	    CD_WELLBORE_T.wellbore_name AS WellBore_surevey,
	    --CD_WELLBORE_T.wellbore_id AS WellBore_surevey_id,
	    CD_VERTICAL_SECTION.def_survey_header_id as def_id,
        CD_DEFINITIVE_SURVEY_STATION_T.sequence_no AS survey_No,
        ROUND((CD_DEFINITIVE_SURVEY_STATION_T.tvd - CD_VERTICAL_SECTION.tvd_start) * 0.3048000000012, 2) AS TVD,
	    ROUND(CD_DEFINITIVE_SURVEY_STATION_T.inclination, 2) AS INC,
        ROUND(CD_DEFINITIVE_SURVEY_STATION_T.azimuth - CD_SITE_SOURCE.convergence, 2) AS Azi,
        ROW_NUMBER() OVER (PARTITION BY CD_DEFINITIVE_SURVEY_STATION_T.wellbore_id ORDER BY CD_DEFINITIVE_SURVEY_STATION_T.sequence_no DESC) AS rn,
        CASE WHEN DP_TEMPLATE.site_id IS NOT NULL THEN 'Production' ELSE 'Exploratory' END AS 井型
    FROM
        CD_DEFINITIVE_SURVEY_STATION_T
    INNER JOIN CD_WELLBORE_T 
        ON CD_WELLBORE_T.wellbore_id = CD_DEFINITIVE_SURVEY_STATION_T.wellbore_id
    INNER JOIN CD_WELL_SOURCE 
        ON CD_WELL_SOURCE.well_id = CD_DEFINITIVE_SURVEY_STATION_T.well_id
    INNER JOIN CD_SITE_SOURCE 
        ON CD_WELL_SOURCE.site_id = CD_SITE_SOURCE.site_id
    LEFT JOIN DP_TEMPLATE
        ON DP_TEMPLATE.site_id = CD_SITE_SOURCE.site_id
    INNER JOIN CD_PROJECT_SOURCE 
        ON CD_SITE_SOURCE.project_id = CD_PROJECT_SOURCE.project_id
    INNER JOIN CD_POLICY 
        ON CD_POLICY.policy_id = CD_PROJECT_SOURCE.policy_id
    INNER JOIN CD_VERTICAL_SECTION 
        ON CD_VERTICAL_SECTION.def_survey_header_id = CD_DEFINITIVE_SURVEY_STATION_T.def_survey_header_id
	INNER JOIN CD_DEFINITIVE_SURVEY_HEADER 
        ON CD_DEFINITIVE_SURVEY_HEADER.def_survey_header_id = CD_DEFINITIVE_SURVEY_STATION_T.def_survey_header_id
    WHERE 
        CD_DEFINITIVE_SURVEY_HEADER.phase = 'ACTUAL'
        AND CD_POLICY.customer_name = 'BoHai'
        AND CD_PROJECT_SOURCE.project_name NOT IN ('HK-1', 'LHIV', 'JJSY', 'XJSY', 'SHAN')
		--不包含陀螺复测
		AND CD_WELLBORE_T.wellbore_name NOT LIKE '%TI%'
		--清除杂项
        AND ROUND(CD_DEFINITIVE_SURVEY_STATION_T.tvd * 0.3048000000012, 2) > 600
        AND PATINDEX('%[^a-zA-Z0-9() -]%', CD_WELLBORE_T.wellbore_name) = 0
        AND CD_WELLBORE_T.wellbore_name NOT LIKE '16'
        AND CD_WELLBORE_T.wellbore_name NOT LIKE '%FISH%'
        AND CD_WELLBORE_T.wellbore_name NOT LIKE '%落%'
        AND CD_WELLBORE_T.wellbore_name NOT LIKE '%OLD%'
        AND CD_WELLBORE_T.wellbore_name NOT LIKE '%epor%'
) AS T
WHERE T.rn = 1
order by 1,2,4,6,8