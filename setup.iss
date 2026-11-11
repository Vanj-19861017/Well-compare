; ============================================================
;  定向井设计工具箱 —— Inno Setup 安装包脚本
;  一般不需要直接编译本文件，请双击「一键打包成安装包.bat」
;  （它会先运行 PyInstaller 生成 dist\定向井设计工具箱，再调用 ISCC 编译本脚本）
; ============================================================

#define MyAppName "定向井设计工具箱"
#ifndef MyAppVersion
  #define MyAppVersion "1.0"
#endif
#define MyAppPublisher "油技塘沽作业公司定向随钻业务线设计室"
#define MyAppExeName "定向井设计工具箱.exe"

[Setup]
; AppId 用应用名，是为了能直接覆盖升级「应用和功能」里已有的旧版本
; （旧版本安装时未指定 AppId，Inno 用应用名生成标识；这里保持一致）
AppId={#MyAppName}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

; 装到当前用户目录，无需管理员权限
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 仅支持 64 位（程序由 64 位 Python 打包）
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=安装包输出
OutputBaseFilename={#MyAppName}_v{#MyAppVersion}_安装包
SetupIconFile=wj.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
DisableWelcomePage=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; 覆盖升级时清掉旧的运行库目录，避免残留旧文件
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; 兜底：卸载时把程序目录整个删掉（目录是本程序专用）
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}"

[Files]
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
