param()
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectDir

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" }
}

$pins = @(
    @{ Name = 'mediacrawler-pilot'; Repo = 'NanmiCoder/MediaCrawler'; Ref = '8f583999006d5b692272c608440e193ca282e73b' },
    @{ Name = 'newscrawler-pilot'; Repo = 'NanmiCoder/NewsCrawler'; Ref = '25fb3b4a20186905f5ce38f7a7f854050d402253' }
)
foreach ($pin in $pins) {
    $checkoutDir = Join-Path '.external-skills' $pin.Name
    if (-not (Test-Path -LiteralPath $checkoutDir)) {
        Invoke-Checked 'git' @('clone', '--no-checkout', "https://github.com/$($pin.Repo).git", $checkoutDir)
        Invoke-Checked 'git' @('-C', $checkoutDir, 'checkout', '--detach', $pin.Ref)
    }
    $actualRef = & git -C $checkoutDir rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actualRef -ne $pin.Ref) {
        throw "Unexpected revision in $checkoutDir; preserve the checkout and inspect it manually."
    }
}
$pilotPython = '.external-skills/cn-pilot-venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pilotPython)) {
    Invoke-Checked '.venv/Scripts/python.exe' @('-m', 'venv', '.external-skills/cn-pilot-venv')
}
Invoke-Checked $pilotPython @('-m', 'pip', 'install', '-r', '.external-skills/mediacrawler-pilot/requirements.txt')
Invoke-Checked $pilotPython @('-m', 'pip', 'install', 'demjson3==3.0.6', 'curl-cffi==0.16.3')
Invoke-Checked $pilotPython @('-m', 'src.cn_pilot', 'doctor')
