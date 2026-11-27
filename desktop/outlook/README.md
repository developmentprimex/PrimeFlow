# Hapja e emailit në Outlook Classic

Në PX Notes, hap detajet e një shënimi të importuar dhe zgjidh **Hap në Outlook
Classic**. Lidhja kërkon `Message-ID` e saktë në kutinë e importit në profilin
lokal të Outlook. Për Exchange të deleguar, kërkimi bëhet në Inbox dhe
nëndosjet e tij. Për kutitë e shtuara si llogari, kërkimi përfshin edhe dosjet
e tjera të asaj kutie.

Për të instaluar komponentin për përdoruesin aktual të Windows, nga rrënja
e projektit ekzekuto në PowerShell:

```powershell
powershell.exe -ExecutionPolicy RemoteSigned -File .\desktop\outlook\install.ps1
```

Në hapjen e parë Chrome ose Edge mund të kërkojë leje për përdorimin e
protokollit të instaluar. Në **New Outlook**, përdor **Hap emailin origjinal**
për ta hapur në webmail kur ajo lidhje është e disponueshme.

Shënimet e vjetra marrin identifikuesin kur i njëjti mesazh kthehet nga
rifreskimi i kutisë në M1 për intervalin e raportit. Për pilotin, përdor
një mesazh të importuar rishtas dhe një profil Outlook Classic ku kutia
përkatëse është tashmë e disponueshme.

Për ta hequr komponentin për përdoruesin aktual:

```powershell
powershell.exe -ExecutionPolicy RemoteSigned -File .\desktop\outlook\install.ps1 -Uninstall
```
