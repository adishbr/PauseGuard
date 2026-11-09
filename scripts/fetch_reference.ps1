# Fetches ONE curated reference repository to .references/ after explicit human approval.
# Does not execute third-party code; does not install packages; never modifies existing checkout.
param(
    [ValidateSet("ecc","fastapi","pydantic","networkx","scikit-learn","playwright","ui","razorpay-python","indic-asr","gsd")]
    [string]$Name,
    [switch]$List
)
$ErrorActionPreference = 'Stop'
$repos = @{
  'ecc' = 'https://github.com/affaan-m/ECC.git'
  'fastapi' = 'https://github.com/fastapi/fastapi.git'
  'pydantic' = 'https://github.com/pydantic/pydantic.git'
  'networkx' = 'https://github.com/networkx/networkx.git'
  'scikit-learn' = 'https://github.com/scikit-learn/scikit-learn.git'
  'playwright' = 'https://github.com/microsoft/playwright.git'
  'ui' = 'https://github.com/shadcn-ui/ui.git'
  'razorpay-python' = 'https://github.com/razorpay/razorpay-python.git'
  'indic-asr' = 'https://github.com/AI4Bharat/IndicConformerASR.git'
  'gsd' = 'https://github.com/open-gsd/gsd-core.git'
}
if ($List) { $repos.GetEnumerator() | Sort-Object Key | Format-Table -AutoSize; exit 0 }
if (-not $Name) { throw 'Specify -Name <shortname>. Use -List to inspect available sources.' }
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$folder = Join-Path $root ".references/$Name"
if (Test-Path $folder) { throw "Reference already exists at $folder. Inspect or remove only by explicit owner approval." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git not installed / on PATH' }
New-Item -Path (Join-Path $root '.references') -ItemType Directory -Force | Out-Null
Write-Host "FETCH REQUEST APPROVED? Fetching $($repos[$Name]) into $folder."
& git clone --depth 1 --single-branch $repos[$Name] $folder
if ($LASTEXITCODE -ne 0) { throw 'Git clone failed; inspect partial directory' }
& git -C $folder rev-parse HEAD
Write-Host 'IMPORTANT: Check license, SHA, source and dependencies manually. Do not execute unreviewed third-party scripts. Record in docs/EXTERNAL_REFERENCE_LOCK.md.'
