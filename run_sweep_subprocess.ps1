# run_sweep_subprocess.ps1
# Runs each BJAC COM case in its OWN PowerShell subprocess to avoid memory conflicts.
# Each subprocess runs run_one_case.ps1 and outputs one CSV line to stdout.
# A crash in one subprocess only kills that case, not the whole sweep.
param(
    [string]$JobTag  = "8537",
    [int]   $Workers = 1       # serial by default (BJAC COM not reliably parallel)
)

$root    = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML"
$genDir  = Join-Path $root "generated\$JobTag"
$csvOut  = Join-Path $root "results\results_$JobTag.csv"
$logFile = Join-Path $root "results\run_${JobTag}_sub.log"
$oneCaseScript = Join-Path $root "run_one_case.ps1"

function Log($msg) {
    $ts = (Get-Date).ToString("HH:mm:ss")
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

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

$header = ((@("filename","FoulResCS","FoulResHS","RunStatus") + $resultFields) -join ",")

$caseList = Import-Csv (Join-Path $genDir "case_list.csv")
$total    = $caseList.Count
Log "=== run_sweep_subprocess.ps1 : JobTag=$JobTag total=$total ==="

[System.IO.File]::WriteAllText($csvOut, $header + "`n", [System.Text.Encoding]::UTF8)

$ok = 0; $fail = 0
$sw = [System.Diagnostics.Stopwatch]::StartNew()

foreach ($row in $caseList) {
    $fname = $row.filename
    $cs    = $row.FoulResCS
    $hs    = $row.FoulResHS
    $fpath = Join-Path $genDir $fname

    # Run in a completely isolated subprocess
    $result = & powershell.exe -NonInteractive -NoProfile -File $oneCaseScript `
        -FilePath $fpath -CS $cs -HS $hs 2>$null

    if ($result) {
        Add-Content -Path $csvOut -Value $result -Encoding UTF8
        $status = ($result -split ",")[3]
        if ($status -eq "OK") { $ok++ } else { $fail++; Log "FAIL $fname : $status" }
    } else {
        # Subprocess crashed (AccessViolationException terminates it)
        $crashLine = "$fname,$cs,$hs,CRASH_AV" + (",") * $resultFields.Count
        Add-Content -Path $csvOut -Value $crashLine -Encoding UTF8
        $fail++
        Log "CRASH (AccessViolationException) $fname"
    }

    $i = $ok + $fail
    if (($i % 10 -eq 0) -or ($i -eq $total)) {
        $elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        $rate    = if ($elapsed -gt 0) { [math]::Round($i/$elapsed*60,1) } else { 0 }
        Log "[$i/$total] ok=$ok fail=$fail elapsed=${elapsed}s (~${rate}/min)"
    }
}

$sw.Stop()

# Validate
Log "Validating $csvOut..."
$data   = Import-Csv $csvOut
$rowCnt = $data.Count
$badSts = ($data | Where-Object { $_.RunStatus -ne "OK" }).Count
$badHtr = ($data | Where-Object { $_.HeatTranRatDirty -eq "" -or $_.HeatTranRatDirty -eq "0" }).Count
$badArd = ($data | Where-Object { $_.AreaRatioDirty   -eq "" -or $_.AreaRatioDirty   -eq "0" }).Count

Log "  Rows=$rowCnt  bad_status=$badSts  bad_HeatTranRatDirty=$badHtr  bad_AreaRatioDirty=$badArd"

if ($rowCnt -eq 100 -and $badSts -eq 0 -and $badHtr -eq 0 -and $badArd -eq 0) {
    Log "ALL CHECKS PASSED"
} else {
    Log "WARNING: validation issues"
}
Log "=== Done. OK=$ok Fail=$fail Time=$([math]::Round($sw.Elapsed.TotalSeconds,1))s ==="
