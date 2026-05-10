; Inno Setup script — AutoTax Watcher Windows Installer
; --------------------------------------------------------------
; Inno Setup 6.x ile derlenir.  Indir: https://jrsoftware.org/isinfo.php
; Komut satiri:  iscc.exe installer.iss
; Cikti:         release\AutoTaxWatcher-Setup-x.y.z.exe
;
; Tasarim kararlari:
; - Per-user kurulum (PrivilegesRequired=lowest) → admin gerekmez,
;   musteri "Yine de calistir"a bile basmadan kurabilir.
; - HKCU\Run kayit defteri ile auto-start (opsiyonel checkbox).
; - %LOCALAPPDATA%\AutoTax\Watcher altindaki config + queue + loglar
;   uninstall'da KORUNUR (kullanici sansiyla yeniden login olmasin).
; - Eski surum varsa otomatik upgrade (UninstallDisplayName ile match).

#define MyAppName        "AutoTax Watcher"
#define MyAppExeName     "AutoTaxWatcher.exe"
#define MyAppPublisher   "AutoTax-Cloud"
#define MyAppURL         "https://autotax.cloud"
#define MyAppId          "{{8C2A1F70-4E3D-4F20-BA15-7E0F2A9D6B12}}"

; Versiyon build.bat tarafindan -DAppVersion=... ile gecirilir.
; Default 0.0.0 → manuel calistirinca bir hata gormeyelim diye.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\AutoTax Watcher
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=..\release
OutputBaseFilename=AutoTaxWatcher-Setup-{#AppVersion}
SetupIconFile=AutoTaxWatcher.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
; SmartScreen reputation icin oneml: VersionInfo* alanlari EXE'deki
; version_info.txt ile tutarli olmali.
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoCopyright=(C) {#MyAppPublisher}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german";  MessagesFile: "compiler:Languages\German.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startupicon"; Description: "Beim Windows-Start automatisch starten"; GroupDescription: "Autostart:"; Flags: checkedonce

[Files]
; PyInstaller ciktisi.  build.bat once `pyinstaller AutoTaxWatcher.spec`
; calistirir, sonra `iscc installer.iss` calistirir.  Bu yuzden
; ..\dist\AutoTaxWatcher.exe burada hazir olur.
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Lisans/README opsiyonel — yoksa Inno ihtilaf cikarmaz.
; Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; HKCU\Run — Windows acilirken sessizce baslat.
; Tasks: startupicon checkbox'i isaretliyse yazilir.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#MyAppName}"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Tasks: startupicon; Flags: uninsdeletevalue

[Run]
; Kurulum sonu ekranindaki "Launch AutoTax Watcher" checkbox.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Sadece program klasoru.  AppData (config + queue + log) silinmez —
; reinstall sonrasi kullanici tekrar login olmak zorunda kalmasin.
Type: filesandordirs; Name: "{app}"

[Code]
{ Eski surumun calisirken installer cakismamasi icin process'i sonlandir. }
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM AutoTaxWatcher.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('taskkill.exe', '/F /IM AutoTaxWatcher.exe', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
  end;
end;
