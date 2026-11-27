param([Parameter(Mandatory)][string]$Link)

$ErrorActionPreference = 'Stop'

function Get-MessageTarget([string]$Value) {
    $parts = [regex]::Match($Value, '^primeflow-outlook://message/([^/?#]{1,200})/([^/?#]{1,3000})/?$')
    if (-not $parts.Success) { throw 'Lidhja PrimeFlow nuk është e vlefshme.' }

    $mailbox = [Uri]::UnescapeDataString($parts.Groups[1].Value).ToLowerInvariant()
    $messageId = [Uri]::UnescapeDataString($parts.Groups[2].Value)
    $mailboxes = @('info@primexeu.com', 'it@forestdream.de', 'info@homeface.de', 'primex.eu@gmail.com')
    if ($mailbox -notin $mailboxes -or $messageId.Length -gt 998 -or
        $messageId -cnotmatch '\A<[!-;=?-~]+@[!-;=?-~]+>\z') {
        throw 'Lidhja PrimeFlow nuk është e vlefshme.'
    }
    @{ Mailbox = $mailbox; MessageId = $messageId }
}

function Find-Message($Folder, [string]$Filter, [string]$SkipEntryId = '') {
    if ($Folder.EntryID -eq $SkipEntryId) { return }
    if ($Folder.DefaultItemType -eq 0) {
        try { $item = $Folder.Items.Find($Filter) }
        catch { $item = $null }
        if ($item) { return ,$item }
    }
    foreach ($subfolder in $Folder.Folders) {
        $item = Find-Message $subfolder $Filter $SkipEntryId
        if ($item) { return ,$item }
    }
}

function Open-OutlookMessage([string]$Value) {
    $target = Get-MessageTarget $Value
    try { $outlook = New-Object -ComObject Outlook.Application }
    catch { throw 'Kërkohet Outlook Classic i konfiguruar në këtë kompjuter.' }
    $session = $outlook.Session
    $filter = '@SQL="http://schemas.microsoft.com/mapi/proptag/0x1035001F" = ' +
        "'" + $target.MessageId.Replace("'", "''") + "'"

    foreach ($account in $session.Accounts) {
        if ($account.SmtpAddress -ne $target.Mailbox -or -not $account.DeliveryStore) { continue }
        $inbox = $account.DeliveryStore.GetDefaultFolder(6)
        $item = Find-Message $inbox $filter
        if (-not $item) { $item = Find-Message ($account.DeliveryStore.GetRootFolder()) $filter $inbox.EntryID }
        if (-not $item) { throw 'Mesazhi nuk u gjet në kutinë e konfiguruar në Outlook Classic.' }
        $item.Display($false)
        return
    }

    # An Exchange mailbox may be delegated without being listed as an account.
    $recipient = $session.CreateRecipient($target.Mailbox)
    $sharedInbox = $null
    if ($recipient.Resolve()) {
        $owner = $recipient.AddressEntry.GetExchangeUser()
        if ($owner -and $owner.PrimarySmtpAddress -eq $target.Mailbox) {
            try { $sharedInbox = $session.GetSharedDefaultFolder($recipient, 6) } catch { }
        }
    }
    if ($sharedInbox) {
        $item = Find-Message $sharedInbox $filter
        if ($item) {
            $item.Display($false)
            return
        }
        throw 'Mesazhi nuk u gjet në Inbox-in e përbashkët në Outlook Classic.'
    }
    throw 'Kjo kuti emaili nuk është e disponueshme në profilin tënd të Outlook Classic.'
}

# Dot-sourcing loads the functions for local tests without launching Outlook.
if ($MyInvocation.InvocationName -ne '.') {
    try { Open-OutlookMessage $Link }
    catch {
        Add-Type -AssemblyName PresentationFramework
        [void][System.Windows.MessageBox]::Show($_.Exception.Message, 'PrimeFlow / Outlook Classic')
        exit 1
    }
}
