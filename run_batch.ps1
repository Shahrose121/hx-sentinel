# Batch EDR Rating runner - final working version
# Key fix: RemoveDocument + 500ms pause between files prevents COM session corruption.
# Writes each CSV row immediately (autoflush) so results survive early termination.

$edrDir  = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\generated"
$csvOut  = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\results_8497.csv"
$logFile = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\batch_log.txt"

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
    Add-Content -Path $logFile -Value "[$ts] $msg" -Encoding UTF8
}

$edrFiles = @(cmd /c "dir /b /on ""$edrDir\8497_var_*.EDR"" 2>nul")
$total    = $edrFiles.Count
Log "Starting batch: $total files"

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
        $doc = $app.GetDocument($fpath, $true)
        $doc.Run()      | Out-Null
        $doc.FileSave() | Out-Null

        # RemoveDocument fully releases the doc from the COM session (FileClose does not).
        # 500ms pause lets the COM server finish cleanup before the next open.
        try { $app.RemoveDocument($fpath) | Out-Null } catch {}
        Start-Sleep -Milliseconds 500

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
