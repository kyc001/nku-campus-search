param(
    [string]$EsHome = $env:ES_HOME,
    [string]$EsUrl = $(if ($env:NKU_SEARCH_ES_URL) { $env:NKU_SEARCH_ES_URL } else { "http://127.0.0.1:9200" }),
    [string]$Version = "9.4.0",
    [switch]$InstallIfMissing,
    [switch]$SkipIndex
)

$ErrorActionPreference = "Stop"

function Test-Elasticsearch {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Find-ElasticsearchBat {
    param([string]$InstallRoot)

    $candidates = @()
    if ($InstallRoot) {
        $candidates += (Join-Path $InstallRoot "bin\elasticsearch.bat")
    }
    $candidates += @(
        "C:\elasticsearch\bin\elasticsearch.bat",
        "C:\Program Files\Elastic\Elasticsearch\bin\elasticsearch.bat",
        "$env:USERPROFILE\elasticsearch\bin\elasticsearch.bat"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $cmd = Get-Command "elasticsearch.bat" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Install-ProjectElasticsearch {
    param(
        [string]$ToolsRoot,
        [string]$Version
    )

    $targetHome = Join-Path $ToolsRoot ("elasticsearch-" + $Version)
    $targetBat = Join-Path $targetHome "bin\elasticsearch.bat"
    if (Test-Path -LiteralPath $targetBat) {
        return (Resolve-Path -LiteralPath $targetBat).Path
    }

    New-Item -ItemType Directory -Force $ToolsRoot | Out-Null
    $zipPath = Join-Path $ToolsRoot ("elasticsearch-" + $Version + "-windows-x86_64.zip")
    $downloadUrl = "https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-$Version-windows-x86_64.zip"

    if (-not (Test-Path -LiteralPath $zipPath)) {
        Write-Host ("Downloading Elasticsearch " + $Version + " ...")
        Write-Host $downloadUrl
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
    }

    Write-Host "Extracting Elasticsearch ..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $ToolsRoot -Force
    if (-not (Test-Path -LiteralPath $targetBat)) {
        throw ("Elasticsearch executable not found after extraction: " + $targetBat)
    }
    return (Resolve-Path -LiteralPath $targetBat).Path
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$codeRoot = Resolve-Path (Join-Path $scriptRoot "..")
$projectRoot = Resolve-Path (Join-Path $codeRoot "..")
$defaultToolsRoot = if (Test-Path "D:\Tools") { "D:\Tools" } else { Join-Path $env:USERPROFILE "elastic-tools" }
$toolsRoot = $defaultToolsRoot
Set-Location $codeRoot

$env:NKU_SEARCH_ES_URL = $EsUrl
$env:ES_JAVA_OPTS = "-Xms1g -Xmx1g"

if (Test-Elasticsearch -Url $EsUrl) {
    Write-Host ("Elasticsearch online: " + $EsUrl)
} else {
    $esBat = Find-ElasticsearchBat -InstallRoot $EsHome
    if (-not $esBat) {
        if (-not $InstallIfMissing) {
            Write-Host "Elasticsearch service was not found locally."
            Write-Host "Use an installed Windows zip/native service, or run this script with -InstallIfMissing."
            Write-Host "Manual download: https://www.elastic.co/downloads/elasticsearch"
            Write-Host 'Example after zip extraction:'
            Write-Host '  $env:ES_HOME="D:\tools\elasticsearch-9.4.0"'
            Write-Host '  .\scripts\start_es.ps1'
            exit 2
        }
        $esBat = Install-ProjectElasticsearch -ToolsRoot $toolsRoot -Version $Version
    }

    Write-Host ("Starting Elasticsearch: " + $esBat)
    $args = @(
        "-E", "discovery.type=single-node",
        "-E", "xpack.security.enabled=false",
        "-E", "cluster.routing.allocation.disk.threshold_enabled=false",
        "-E", "network.host=127.0.0.1",
        "-E", "http.port=9200"
    )
    $log = Join-Path (Join-Path $codeRoot "data") "elasticsearch.out.log"
    $err = Join-Path (Join-Path $codeRoot "data") "elasticsearch.err.log"
    Remove-Item -LiteralPath $log,$err -ErrorAction SilentlyContinue
    Start-Process -FilePath $esBat -ArgumentList $args -WorkingDirectory (Split-Path -Parent (Split-Path -Parent $esBat)) -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err

    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Elasticsearch -Url $EsUrl) {
            $ready = $true
            break
        }
        Write-Host ("Waiting Elasticsearch... " + [int](($i + 1) * 2) + "s")
    }
    if (-not $ready) {
        Write-Host ("Elasticsearch not ready: " + $EsUrl)
        Get-Content -Path $err -ErrorAction SilentlyContinue | Select-Object -Last 60
        exit 3
    }
}

if (-not $SkipIndex) {
    Write-Host "Building Elasticsearch index..."
    pixi run build-es-index
}

Write-Host "ES backend ready."
Write-Host '  $env:NKU_SEARCH_BACKEND="auto"'
Write-Host '  pixi run serve'
