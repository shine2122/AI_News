# Upload newsletter settings from .env to GitHub Actions secrets.

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$envFile = Join-Path $scriptDir '.env'

if (-not (Test-Path $envFile)) {
    Write-Host 'Missing .env file. Create it from .env.example first.' -ForegroundColor Red
    exit 1
}

try {
    gh auth status *> $null
} catch {
    Write-Host 'GitHub CLI login is required: gh auth login -h github.com --web --scopes repo,workflow' -ForegroundColor Yellow
    exit 1
}

$values = @{}
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) {
        return
    }

    $parts = $line -split '=', 2
    $name = $parts[0].Trim()
    $value = $parts[1].Trim().Trim('"').Trim("'")

    if ($name) {
        $values[$name] = $value
    }
}

$requiredSecrets = @(
    'GEMINI_API_KEY',
    'GMAIL_USER',
    'GMAIL_APP_PASSWORD',
    'RECIPIENT_EMAIL'
)

$optionalSecrets = @(
    'NEWSLETTER_NAME',
    'AUTHOR_NAME'
)

$missing = $requiredSecrets | Where-Object { -not $values.ContainsKey($_) -or [string]::IsNullOrWhiteSpace($values[$_]) }
if ($missing.Count -gt 0) {
    Write-Host "Missing required .env values: $($missing -join ', ')" -ForegroundColor Red
    exit 1
}

foreach ($name in ($requiredSecrets + $optionalSecrets)) {
    if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($values[$name])) {
        continue
    }

    $values[$name] | gh secret set $name --app actions
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to upload secret: $name" -ForegroundColor Red
        exit 1
    }

    Write-Host "Uploaded secret: $name"
}

Write-Host 'GitHub Actions secrets are configured.' -ForegroundColor Green
