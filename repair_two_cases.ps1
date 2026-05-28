# repair_two_cases.ps1
# Regenerates the 2 truncated EDR files from the base file,
# runs them in Rating mode, and produces results_8497_clean.csv
# with those 2 rows refreshed and all 100 rows validated.

$basePath  = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\8497 DUTY REV 1.EDR"
$genDir    = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\generated"
$ratingCsv = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\results_8497.csv"
$cleanCsv  = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\results_8497_clean.csv"
$logFile   = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\repair_log.txt"

# The 2 cases to regenerate (CS = cold/tube side, HS = hot/shell side)
$cases = @(
    [ordered]@{ CS = "0.000684"; HS = "0.000342"; fname = "8497_var_CS0.000684_HS0.000342.EDR" },
    [ordered]@{ CS = "0.000684"; HS = "0.000440"; fname = "8497_var_CS0.000684_HS0.000440.EDR" }
)

# Same result fields as run_batch.ps1
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

Log "=== repair_two_cases.ps1 starting ==="

# ── STEP 1: Verify base file exists and is full-size ────────────────────────
$baseSize = (Get-Item $basePath).Length
Log "Base file: $basePath  ($baseSize bytes)"
if ($baseSize -lt 200000) { throw "Base file looks too small: $baseSize bytes" }

# ── STEP 2: Regenerate the 2 EDR files from the base file ───────────────────
Log "Regenerating 2 EDR files from base..."
$baseXml = [System.IO.File]::ReadAllText($basePath, [System.Text.Encoding]::UTF8)

foreach ($c in $cases) {
    $targetPath = Join-Path $genDir $c.fname

    $xml = $baseXml
    # Replace only the User-source input scalars FoulResCS and FoulResHS
    $xml = $xml -replace '(?s)(<scalar name="FoulResCS">(?:\s*<uom>[^<]*</uom>\s*)?<value>)[^<]*(</value>)', "`${1}$($c.CS)`${2}"
    $xml = $xml -replace '(?s)(<scalar name="FoulResHS">(?:\s*<uom>[^<]*</uom>\s*)?<value>)[^<]*(</value>)', "`${1}$($c.HS)`${2}"

    [System.IO.File]::WriteAllText($targetPath, $xml, [System.Text.Encoding]::UTF8)
    $newSize = (Get-Item $targetPath).Length
    Log "  Written: $($c.fname)  ($newSize bytes)"

    # Verify the values landed correctly
    $check = [System.IO.File]::ReadAllText($targetPath, [System.Text.Encoding]::UTF8)
    $csGot = [regex]::Match($check, '(?s)<scalar name="FoulResCS">.*?<value>([^<]+)</value>').Groups[1].Value
    $hsGot = [regex]::Match($check, '(?s)<scalar name="FoulResHS">.*?<value>([^<]+)</value>').Groups[1].Value
    Log "    FoulResCS=$csGot (wanted $($c.CS))  FoulResHS=$hsGot (wanted $($c.HS))"
    if ($csGot -ne $c.CS -or $hsGot -ne $c.HS) { throw "Value mismatch after write - aborting." }
}

# ── STEP 3: Run both files via COM in Rating mode ────────────────────────────
Log "Starting COM..."
$app = New-Object -ComObject "BJACCOM2.BJACApp"
Log "COM ready"

$newRows = [System.Collections.Generic.List[hashtable]]::new()

foreach ($c in $cases) {
    $fpath = Join-Path $genDir $c.fname
    Log "Running: $($c.fname)"
    try {
        $doc = $app.GetDocument($fpath, $true)
        $doc.Run()      | Out-Null
        $doc.FileSave() | Out-Null
        try { $app.RemoveDocument($fpath) | Out-Null } catch {}
        Start-Sleep -Milliseconds 500

        $xml        = [System.IO.File]::ReadAllText($fpath, [System.Text.Encoding]::UTF8)
        $resultCode = [regex]::Match($xml, '<result>([^<]*)</result>').Groups[1].Value
        $runStatus  = if ($resultCode -eq "101") { "OK" } else { "FAIL_$resultCode" }
        $fileSize   = (Get-Item $fpath).Length

        Log "  ResultCode=$resultCode  RunStatus=$runStatus  FileSize=$fileSize bytes"
        if ($fileSize -lt 200000) { Log "  WARNING: file still looks truncated!" }

        $scalars = Extract-Scalars $xml
        $row = [ordered]@{}
        $row["filename"]  = $c.fname
        $row["FoulResCS"] = $c.CS
        $row["FoulResHS"] = $c.HS
        $row["RunStatus"] = $runStatus
        foreach ($f in $resultFields) {
            $row[$f] = if ($scalars.ContainsKey($f)) { $scalars[$f] } else { "" }
        }

        $newRows.Add($row)
        Log "  HeatTranRatDirty=$($row['HeatTranRatDirty'])  AreaRatioDirty=$($row['AreaRatioDirty'])"
    }
    catch {
        Log "  ERROR: $($_.Exception.Message)"
        throw
    }
}

# ── STEP 4: Remove old rows from results_8497.csv, insert fresh ones ─────────
Log "Building results_8497_clean.csv..."

$existing = Import-Csv $ratingCsv
Log "  Loaded $($existing.Count) rows from results_8497.csv"

# Remove the 2 stale rows (match on FoulResCS+FoulResHS string values)
$keepRows = $existing | Where-Object {
    -not ($cases | Where-Object {
        $c = $_
        $row = $_   # shadowed - use outer loop var explicitly
        $false   # placeholder; use the -contains logic below
    })
}
# Use explicit string matching to drop the 2 target cases
$targetKeys = $cases | ForEach-Object { "$($_.CS)_$($_.HS)" }
$keepRows = $existing | Where-Object {
    $key = "$($_.FoulResCS)_$($_.FoulResHS)"
    $targetKeys -notcontains $key
}
Log "  After removing 2 rows: $($keepRows.Count) rows remain"

# Get column order from existing CSV
$colOrder = $existing[0].PSObject.Properties.Name

# Write header
[System.IO.File]::WriteAllText($cleanCsv, ($colOrder -join ",") + "`n", [System.Text.Encoding]::UTF8)
$csvStream = [System.IO.StreamWriter]::new($cleanCsv, $true, [System.Text.Encoding]::UTF8)
$csvStream.AutoFlush = $true

# Write preserved rows (maintaining original order)
foreach ($row in $keepRows) {
    $vals = $colOrder | ForEach-Object { $row.$_ }
    $csvStream.WriteLine($vals -join ",")
}

# Append the 2 fresh rows
foreach ($row in $newRows) {
    $vals = $colOrder | ForEach-Object { if ($row.ContainsKey($_)) { $row[$_] } else { "" } }
    $csvStream.WriteLine($vals -join ",")
}
$csvStream.Close()

# ── STEP 5: Validate all 100 rows ────────────────────────────────────────────
Log "Validating results_8497_clean.csv..."
$clean = Import-Csv $cleanCsv
Log "  Total rows: $($clean.Count)"

$badHtr = $clean | Where-Object { $_.HeatTranRatDirty -eq "" -or $_.HeatTranRatDirty -eq "0" }
$badArd = $clean | Where-Object { $_.AreaRatioDirty   -eq "" -or $_.AreaRatioDirty   -eq "0" }
$badSts = $clean | Where-Object { $_.RunStatus -ne "OK" }

Log "  HeatTranRatDirty empty/zero: $($badHtr.Count)"
Log "  AreaRatioDirty   empty/zero: $($badArd.Count)"
Log "  Non-OK RunStatus:            $($badSts.Count)"

if ($badHtr.Count -eq 0 -and $badArd.Count -eq 0 -and $badSts.Count -eq 0 -and $clean.Count -eq 100) {
    Log "ALL CHECKS PASSED - 100 clean rows confirmed."
} else {
    Log "WARNING: validation found issues - review above."
}

Log "=== Done. Output: $cleanCsv ==="
