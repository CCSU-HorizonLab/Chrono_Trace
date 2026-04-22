#define AppName "Chrono Trace"
#define AppExeName "Chrono Trace.exe"
#define AppIconFile "..\chrono Trace.ico"

#ifndef BuildRoot
  #define BuildRoot "..\release\pyinstaller\Chrono Trace"
#endif

#ifndef ProjectVersion
  #define ProjectVersion "0.1.0"
#endif

#define AppVersion GetStringFileInfo(AddBackslash(BuildRoot) + AppExeName, "ProductVersion")
#if AppVersion == ""
  #undef AppVersion
  #define AppVersion ProjectVersion
#endif

#define WebView2Bootstrapper "third_party\MicrosoftEdgeWebview2Setup.exe"

[Setup]
AppId={{6FEEB5EC-97A9-4E7B-BE78-EE673FB5BDA0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Chrono Trace
SetupIconFile={#AppIconFile}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\release\installer
OutputBaseFilename=ChronoTraceSetup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableDirPage=no
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "{#BuildRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifexist "{#WebView2Bootstrapper}"
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: deleteafterinstall ignoreversion
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
#ifexist "{#WebView2Bootstrapper}"
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 Runtime..."; Flags: waituntilterminated runhidden; Check: NeedsWebView2Runtime
#endif
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasValidWebView2Version(const Value: string): Boolean;
begin
  Result := (Value <> '') and (Value <> '0.0.0.0');
end;

function IsWebView2RuntimeInstalled(): Boolean;
var
  VersionValue: string;
begin
  Result :=
    (RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid, 'pv', VersionValue) and HasValidWebView2Version(VersionValue)) or
    (RegQueryStringValue(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid, 'pv', VersionValue) and HasValidWebView2Version(VersionValue)) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid, 'pv', VersionValue) and HasValidWebView2Version(VersionValue)) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid, 'pv', VersionValue) and HasValidWebView2Version(VersionValue)) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid, 'pv', VersionValue) and HasValidWebView2Version(VersionValue));
end;

function NeedsWebView2Runtime(): Boolean;
begin
  Result := not IsWebView2RuntimeInstalled();
end;
