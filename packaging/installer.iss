; Inno Setup 6: installer til Hinge Auto Swipe. Bygges af build_windows.ps1 (ISCC /DAppVersion=x.y.z installer.iss).
; Installerer pr. bruger (ingen administrator), med genvej i Start og evt. på skrivebordet.

#define AppName "Hinge Auto Swipe"
#define AppExe "HingeAutoSwipe.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{2D4B2338-B6B4-4239-BAB1-86C01F7CF2BE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Byens IT
AppPublisherURL=https://github.com/byensitmagnus/hinge-swipe-iphone
AppSupportURL=https://byensitmagnus.github.io/hinge-swipe-iphone/
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=HingeAutoSwipe-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
danish.GetITunes=Hent iTunes (Apples USB-driver til iPhone – mangler på denne pc)
english.GetITunes=Get iTunes (Apple's USB driver for iPhone – missing on this PC)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Fjern filer fra en ældre version, så der ikke ligger gamle biblioteker tilbage.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\HingeAutoSwipe\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "https://apps.microsoft.com/detail/9pb2mz1zmb1s"; Description: "{cm:GetITunes}"; Flags: shellexec postinstall skipifsilent nowait; Check: AppleDriverMissing
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Apples USB-tjeneste følger med iTunes. Uden den kan appen ikke se iPhonen.
// Klassisk iTunes registrerer tjenesten; iTunes og Apple Devices fra Microsoft Store er pakker.
function AppleDriverMissing(): Boolean;
var
  Names: TArrayOfString;
  I: Integer;
begin
  Result := not RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\Apple Mobile Device Service');
  if Result and RegGetSubkeyNames(HKCU, 'Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages', Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if (Pos('AppleInc.iTunes', Names[I]) = 1) or (Pos('AppleInc.AppleDevices', Names[I]) = 1) then
        Result := False;
end;
