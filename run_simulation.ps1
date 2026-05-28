# Batch EDR Simulation runner
# Mirrors run_batch.ps1 but:
#   1. Patches ProgramMode 2 → 3 (Simulation) in each file before running
#   2. Extracts the Simulation-specific result fields
# Same COM safety pattern: RemoveDocument + 500ms pause between files.

$edrDir  = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\generated"
$csvOut  = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\simulation_8497.csv"
$logFile = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\sim_batch_log.txt"

$resultFields = @(
    "HtLdTotal","DutyRatio",
    "TempOutSS","TempOutTS","TempInSS","TempInTS",
    "HeatTranRatDirty","HeatTranRatClean",
    "AreaRatioDirty","AreaRatioClean",
    "PresDropCalcSS","PresDropCalcTS",
    "DPratioSS","DPratioTS",
    "VelThruTubesMaxTS","VelCrossFlowMaxSS",
    "RV2BundleEnt","RV2InNoz",
    "LMTD","MTDCorrFactor",
    "ExcessSurfDirty","FoulResSS","FoulResTS"
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
    Add-Content -Path $logFile -Value "[$ts] $msg" -Encoding UTF8
}

# Use sorted dir listing (consistent ordering with run_batch.ps1)
$edrFiles = @(cmd /c "dir /b /on ""$edrDir\8497_var_*.EDR"" 2>nul")
$total    = $edrFiles.Count
Log "Starting simulation batch: $total files"

$header = ((@("filename","FoulResCS","FoulResHS","RunStatus") + $resultFields) -join ",")
[System.IO.File]::WriteAllText($csvOut, $header + "`n", [System.Text.Encoding]::UTF8)
$csvStream = [System.IO.StreamWriter]::new($csvOut, $true, [System.Text.Encoding]::UTF8)
$csvStream.AutoFlush = $true

$app = New-Object -ComObject "BJACCOM2.BJACApp"
Log "COM ready"

$ok = 0; $fail = 0
$sw = [System.Diagnostics.Stopwatch]::StartNew()

for ($i = 0; $i -lt $total; $i++) {
    $fname = $edrFiles[$i]
    $fpath = Join-Path $edrDir $fname
    $csVal = [regex]::Match($fname, 'CS([\d.]+)(?=_)').Groups[1].Value
    $hsVal = [regex]::Match($fname, 'HS([\d.]+)(?=\.)').Groups[1].Value

    try {
        # ── Step 1: Patch ProgramMode from Rating (2) → Simulation (3) ──────────
        $xmlContent = [System.IO.File]::ReadAllText($fpath, [System.Text.Encoding]::UTF8)
        $xmlSim = $xmlContent -replace '(?s)(<scalar name="ProgramMode">.*?<value>)2(</value>)', '${1}3${2}'
        [System.IO.File]::WriteAllText($fpath, $xmlSim, [System.Text.Encoding]::UTF8)

        # ── Step 2: Run via COM ──────────────────────────────────────────────────
        $doc = $app.GetDocument($fpath, $true)
        $doc.Run()      | Out-Null
        $doc.FileSave() | Out-Null
        # RemoveDocument fully releases the doc; FileClose does not.
        # 500 ms lets the COM server finish cleanup before next open.
        try { $app.RemoveDocument($fpath) | Out-Null } catch {}
        Start-Sleep -Milliseconds 500

        # ── Step 3: Extract results from saved XML ───────────────────────────────
        $xml        = [System.IO.File]::ReadAllText($fpath, [System.Text.Encoding]::UTF8)
        $resultCode = [regex]::Match($xml, '<result>([^<]*)</result>').Groups[1].Value
        $runStatus  = if ($resultCode -eq "101") { "OK" } else { "FAIL_$resultCode" }
        if ($resultCode -eq "101") { $ok++ } else { $fail++ }

        $scalars = Extract-Scalars $xml
        $row = [System.Collections.Generic.List[string]]::new()
        $row.Add($fname); $row.Add($csVal); $row.Add($hsVal); $row.Add($runStatus)
        foreach ($f in $resultFields) {
            $row.Add( $(if ($scalars.ContainsKey($f)) { $scalars[$f] } else { "" }) )
        }
        $csvStream.WriteLine($row -join ",")
    }
    catch {
        $fail++
        $row = [System.Collections.Generic.List[string]]::new()
        $row.Add($fname); $row.Add($csVal); $row.Add($hsVal)
        $row.Add("ERROR: $($_.Exception.Message)")
        foreach ($f in $resultFields) { $row.Add("") }
        $csvStream.WriteLine($row -join ",")
        Log "ERROR $fname`: $($_.Exception.Message)"
    }

    if ((($i+1) % 10 -eq 0) -or (($i+1) -eq $total)) {
        $elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        $rate    = if ($elapsed -gt 0) { [math]::Round(($i+1)/$elapsed*60,1) } else { 0 }
        Log "[$($i+1)/$total] ok=$ok fail=$fail elapsed=${elapsed}s (~${rate}/min)"
    }
}

$csvStream.Close()
$sw.Stop()
Log "DONE. Total=$total OK=$ok Failed=$fail Time=$([math]::Round($sw.Elapsed.TotalSeconds,1))s"
Write-Host "DONE. OK=$ok Failed=$fail  →  $csvOut"
