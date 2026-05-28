# generate_and_run.ps1
#
# USAGE:
#   .\generate_and_run.ps1 -BaseFile "base_files\8369 DUTY CALCS - REv 3.EDR" -JobTag "8369" -MaxMultiplier 2.5
#   .\generate_and_run.ps1 -BaseFile "base_files\8497 DUTY REV 1.EDR"          -JobTag "8497"  # defaults to 2.5x
#
# What it does:
#   1. Reads design FoulResCS + FoulResHS from the base file
#   2. Builds a 10x10 fouling grid (0 .. MaxMultiplier x design for each side)
#   3. Writes 100 variation EDR files into generated\<JobTag>\
#   4. Runs each through AspenEDR COM in Rating mode
#   5. Saves all 52 columns to results\results_<JobTag>.csv
#   6. Validates: 100 rows, no empty/zero HeatTranRatDirty or AreaRatioDirty

param(
    [Parameter(Mandatory)][string]$BaseFile,        # relative or absolute path to base EDR
    [Parameter(Mandatory)][string]$JobTag,          # e.g. "8369" - used for folder + CSV names
    [double]$MaxMultiplier = 2.5                    # grid upper bound as multiple of design value
)

$root     = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML"
$basePath = if ([System.IO.Path]::IsPathRooted($BaseFile)) { $BaseFile } `
            else { Join-Path $root $BaseFile }
$genDir   = Join-Path $root "generated\$JobTag"
$csvOut   = Join-Path $root "results\results_$JobTag.csv"
$logFile  = Join-Path $root "results\run_$JobTag.log"

# ── Result fields (must match results_8497_clean.csv column order) ────────────
$resultFields = @(
    "HeatTranRatClean","HeatTranRatDirty","HeatTranRatService",
    "AreaRatioClean","AreaRatioDirty",
    "HtLdTotal","DutyRatio",
    "PresDropCalcSS","PresDropCalcTS",
    "PresDropAlloSS","PresDropAlloTS",
    "DPratioSS","DPratioTS",
    "TempInSS","TempOutSS","TempInTS","TempOutTS",
    "FlRaTotalSS","FlRaTotalTS",
    "VelThruTubesMaxTS","VelCrossFlowMaxSS",
    "RV2BundleEnt","RV2InNoz","RV2ShlEnt",
    "FoulMaxSS","FoulMaxTS",
    "FoulResSS","FoulResTS",
    "LMTD","MTDCorrFactor",
    "ExcessSurfClean","ExcessSurfDirty",
    "TubeNum","TubeOD","TubeID","TubeLng",
    "ShlID","BafNum","BafSpcCC","BafCutPerc",
    "TubePassNum","TubePattern",
    "OverallLength","Area",
    "FilmCoefSS","FilmCoefTS",
    "PresOperInSS","PresOperInTS"
)

function Extract-Scalars($xml) {
    $dict = @{}
    $hits = [regex]::Matches($xml,
        '(?s)<scalar name="([^"]+)">\s*(?:<uom>[^<]*</uom>\s*)?<value>([^<]*)</value>')
    foreach ($h in $hits) { $dict[$h.Groups[1].Value] = $h.Groups[2].Value }
    return $dict
}

function Log($msg) {
    $ts = (Get-Date).ToString("HH:mm:ss")
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Round6([double]$v) { [math]::Round($v, 6).ToString("F6") }

# ── Pre-flight ────────────────────────────────────────────────────────────────
if (-not (Test-Path $basePath)) { throw "Base file not found: $basePath" }
$baseSize = (Get-Item $basePath).Length
if ($baseSize -lt 200000) { throw "Base file too small ($baseSize bytes) - may be corrupt" }

New-Item -ItemType Directory -Force -Path $genDir | Out-Null

Log "=== generate_and_run.ps1 : JobTag=$JobTag ==="
Log "Base file : $basePath  ($baseSize bytes)"
Log "Output dir: $genDir"
Log "CSV output: $csvOut"

# ── STEP 1: Read design fouling values ────────────────────────────────────────
$baseXml   = [System.IO.File]::ReadAllText($basePath, [System.Text.Encoding]::UTF8)
$designCS  = [double]([regex]::Match($baseXml,
    '(?s)<scalar name="FoulResCS">.*?<value>([^<]+)</value>').Groups[1].Value)
$designHS  = [double]([regex]::Match($baseXml,
    '(?s)<scalar name="FoulResHS">.*?<value>([^<]+)</value>').Groups[1].Value)

Log "Design FoulResCS = $designCS  m2*K/W"
Log "Design FoulResHS = $designHS  m2*K/W"

# ── STEP 2: Build 10x10 fouling grid (0 to 5x design, 10 equal steps) ────────
# Row 0 = 0 (clean), rows 1-9 linearly spaced up to 5x the design value.
# This ensures the clean baseline and design point are both in the grid.
$nSteps   = 10
$maxMulti = $MaxMultiplier

$csVals = 0..($nSteps-1) | ForEach-Object {
    Round6 ($_ * $designCS * $maxMulti / ($nSteps - 1))
}
$hsVals = 0..($nSteps-1) | ForEach-Object {
    Round6 ($_ * $designHS * $maxMulti / ($nSteps - 1))
}

Log "CS grid (10 values): $($csVals -join ', ')"
Log "HS grid (10 values): $($hsVals -join ', ')"

# ── STEP 3: Generate 100 variation EDR files ──────────────────────────────────
Log "Generating 100 variation files..."
$cases = [System.Collections.Generic.List[hashtable]]::new()

foreach ($cs in $csVals) {
    foreach ($hs in $hsVals) {
        $fname = "${JobTag}_var_CS${cs}_HS${hs}.EDR"
        $fpath = Join-Path $genDir $fname

        $xml = $baseXml
        $xml = $xml -replace '(?s)(<scalar name="FoulResCS">(?:\s*<uom>[^<]*</uom>\s*)?<value>)[^<]*(</value>)', "`${1}${cs}`${2}"
        $xml = $xml -replace '(?s)(<scalar name="FoulResHS">(?:\s*<uom>[^<]*</uom>\s*)?<value>)[^<]*(</value>)', "`${1}${hs}`${2}"
        [System.IO.File]::WriteAllText($fpath, $xml, [System.Text.Encoding]::UTF8)

        $cases.Add([ordered]@{ CS=$cs; HS=$hs; fname=$fname; fpath=$fpath })
    }
}
Log "Generated $($cases.Count) files in $genDir"

# Write case_list.csv alongside variations
$clPath = Join-Path $genDir "case_list.csv"
$clStream = [System.IO.StreamWriter]::new($clPath, $false, [System.Text.Encoding]::UTF8)
$clStream.AutoFlush = $true
$clStream.WriteLine("filename,FoulResCS,FoulResHS")
foreach ($c in $cases) { $clStream.WriteLine("$($c.fname),$($c.CS),$($c.HS)") }
$clStream.Close()
Log "case_list.csv written: $clPath"

# ── STEP 4: Run all 100 files via COM ─────────────────────────────────────────
Log "Starting COM..."
$app = New-Object -ComObject "BJACCOM2.BJACApp"
Log "COM ready"

$header = ((@("filename","FoulResCS","FoulResHS","RunStatus") + $resultFields) -join ",")
[System.IO.File]::WriteAllText($csvOut, $header + "`n", [System.Text.Encoding]::UTF8)
$csvStream = [System.IO.StreamWriter]::new($csvOut, $true, [System.Text.Encoding]::UTF8)
$csvStream.AutoFlush = $true

$ok = 0; $fail = 0
$total = $cases.Count
$sw = [System.Diagnostics.Stopwatch]::StartNew()

for ($i = 0; $i -lt $total; $i++) {
    $c     = $cases[$i]
    $fpath = $c.fpath

    try {
        $doc = $app.GetDocument($fpath, $true)
        $doc.Run()      | Out-Null
        $doc.FileSave() | Out-Null
        try { $app.RemoveDocument($fpath) | Out-Null } catch {}
        Start-Sleep -Milliseconds 1000

        $xml        = [System.IO.File]::ReadAllText($fpath, [System.Text.Encoding]::UTF8)
        $resultCode = [regex]::Match($xml, '<result>([^<]*)</result>').Groups[1].Value
        $runStatus  = if ($resultCode -eq "101") { "OK" } else { "FAIL_$resultCode" }
        $fileSize   = (Get-Item $fpath).Length
        if ($resultCode -eq "101") { $ok++ } else { $fail++ }

        if ($fileSize -lt 200000) {
            Log "  WARNING: $($c.fname) looks truncated ($fileSize bytes) after run"
        }

        $scalars = Extract-Scalars $xml
        $row = [System.Collections.Generic.List[string]]::new()
        $row.Add($c.fname); $row.Add($c.CS); $row.Add($c.HS); $row.Add($runStatus)
        foreach ($f in $resultFields) {
            $row.Add($(if ($scalars.ContainsKey($f)) { $scalars[$f] } else { "" }))
        }
        $csvStream.WriteLine($row -join ",")
    }
    catch {
        $fail++
        $row = [System.Collections.Generic.List[string]]::new()
        $row.Add($c.fname); $row.Add($c.CS); $row.Add($c.HS)
        $row.Add("ERROR: $($_.Exception.Message)")
        foreach ($f in $resultFields) { $row.Add("") }
        $csvStream.WriteLine($row -join ",")
        Log "ERROR $($c.fname): $($_.Exception.Message)"
    }

    if ((($i+1) % 10 -eq 0) -or (($i+1) -eq $total)) {
        $elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        $rate    = if ($elapsed -gt 0) { [math]::Round(($i+1)/$elapsed*60,1) } else { 0 }
        Log "[$($i+1)/$total] ok=$ok fail=$fail elapsed=${elapsed}s (~${rate}/min)"
    }
}

$csvStream.Close()
$sw.Stop()

# ── STEP 5: Validate ──────────────────────────────────────────────────────────
Log "Validating $csvOut ..."
$data    = Import-Csv $csvOut
$rowCnt  = $data.Count
$badHtr  = ($data | Where-Object { $_.HeatTranRatDirty -eq "" -or $_.HeatTranRatDirty -eq "0" }).Count
$badArd  = ($data | Where-Object { $_.AreaRatioDirty   -eq "" -or $_.AreaRatioDirty   -eq "0" }).Count
$badSts  = ($data | Where-Object { $_.RunStatus -ne "OK" }).Count

Log "  Rows            : $rowCnt (expected 100)"
Log "  HeatTranRatDirty empty/zero: $badHtr"
Log "  AreaRatioDirty   empty/zero: $badArd"
Log "  Non-OK RunStatus:            $badSts"

if ($rowCnt -eq 100 -and $badHtr -eq 0 -and $badArd -eq 0 -and $badSts -eq 0) {
    Log "ALL CHECKS PASSED"
} else {
    Log "WARNING: validation issues found - check log and CSV"
}

# Range summary
$htr = $data | ForEach-Object { [double]$_.HeatTranRatDirty }
$ard = $data | ForEach-Object { [double]$_.AreaRatioDirty }
Log ("HeatTranRatDirty : min={0:F4}  max={1:F4}" -f ($htr|Measure-Object -Minimum).Minimum, ($htr|Measure-Object -Maximum).Maximum)
Log ("AreaRatioDirty   : min={0:F7}  max={1:F7}" -f ($ard|Measure-Object -Minimum).Minimum, ($ard|Measure-Object -Maximum).Maximum)
Log "=== Done. Total=$total OK=$ok Failed=$fail Time=$([math]::Round($sw.Elapsed.TotalSeconds,1))s ==="
