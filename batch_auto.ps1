# batch_auto.ps1
# Fully automatic batch EDR processing + master dataset merge + shutdown
# Skips: PD files, 8537 (TASC), already-complete jobs (100 clean rows)

$root      = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML"
$resDir    = Join-Path $root "results"
$masterDir = Join-Path $root "master"
$logFile   = Join-Path $resDir "batch_auto.log"
New-Item -ItemType Directory -Force -Path $masterDir | Out-Null

$resultFields = @(
    "HeatTranRatClean","HeatTranRatDirty","HeatTranRatService",
    "AreaRatioClean","AreaRatioDirty","HtLdTotal","DutyRatio",
    "PresDropCalcSS","PresDropCalcTS","PresDropAlloSS","PresDropAlloTS",
    "DPratioSS","DPratioTS","TempInSS","TempOutSS","TempInTS","TempOutTS",
    "FlRaTotalSS","FlRaTotalTS","VelThruTubesMaxTS","VelCrossFlowMaxSS",
    "RV2BundleEnt","RV2InNoz","RV2ShlEnt","FoulMaxSS","FoulMaxTS",
    "FoulResSS","FoulResTS","LMTD","MTDCorrFactor",
    "ExcessSurfClean","ExcessSurfDirty","TubeNum","TubeOD","TubeID","TubeLng",
    "ShlID","BafNum","BafSpcCC","BafCutPerc","TubePassNum","TubePattern",
    "OverallLength","Area","FilmCoefSS","FilmCoefTS","PresOperInSS","PresOperInTS"
)

# Jobs to process: EDR filename -> JobTag
# PD files and 8537 (TASC/AccessViolation) are excluded
$jobs = [ordered]@{
    "8364 -A1in-3in - InLine - Duty INTEGRATED DESIGN.EDR" = "8364-A"
    "8364 -B- 2in-4in-InLine - Duty.EDR"                   = "8364-B"
    "8395- DUTY 785- 8-18in In-LINE HEX.EDR"               = "8395"
    "8404 NGN DUTY CALCS REV 1.EDR"                        = "8404"
    "8409 DUTY REVO.EDR"                                    = "8409"
    "8410 DUTY REV0.EDR"                                    = "8410"
    "8414- 8IN-16IN DUTY kW.EDR"                           = "8414"
    "8422-Amstrong 3in-8in -65 kW DUTY.EDR"                = "8422"
    "8423DUTYCALCS.EDR"                                     = "8423"
    "8426DUTY 16INCH CALCS REV 0.EDR"                      = "8426"
    "8433DUTY REV0.EDR"                                     = "8433"
    "8436 -4IN-10IN BEM witv cones 107.4 kW DUTY.EDR"      = "8436"
    "8471 DESIGN 1 (4-6INCH) DUTY REV 0.EDR"               = "8471"
    "8474 CADENTGAS DUTY REV 0.EDR"                        = "8474"
    "8482 DUTY REV 0.EDR"                                   = "8482"
    "8485- DUTY.EDR"                                        = "8485"
    "8499 (SAME AS 8460 NO1) 99.6 kW DUTY.EDR"            = "8499"
    "8505 DUTY REV 0.EDR"                                   = "8505"
    "8520 DUTY REV 1.EDR"                                   = "8520"
    "8523- DUTY 6-12in In-LINE HEX (original 7871A).EDR"   = "8523"
    "8545 DUTY REV 0.EDR"                                   = "8545"
}

# ── Helper functions ─────────────────────────────────────────────────────────

function Log($msg) {
    $ts   = (Get-Date).ToString("HH:mm:ss")
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Extract-Scalars($xml) {
    $dict = @{}
    [regex]::Matches($xml, '(?s)<scalar name="([^"]+)">\s*(?:<uom>[^<]*</uom>\s*)?<value>([^<]*)</value>') |
        ForEach-Object { $dict[$_.Groups[1].Value] = $_.Groups[2].Value }
    return $dict
}

function Get-ResultStatus($csvPath) {
    if (-not (Test-Path $csvPath)) { return @{ clean=$false; rows=0; bad=0 } }
    try {
        $d   = Import-Csv $csvPath
        $bad = ($d | Where-Object {
            $_.HeatTranRatDirty -eq "" -or $_.HeatTranRatDirty -eq "0" -or
            $_.AreaRatioDirty   -eq "" -or $_.AreaRatioDirty   -eq "0" -or
            $_.RunStatus -ne "OK"
        }).Count
        return @{ clean=($d.Count -eq 100 -and $bad -eq 0); rows=$d.Count; bad=$bad }
    } catch { return @{ clean=$false; rows=0; bad=0 } }
}

function Kill-HeavyPS {
    Get-Process | Where-Object {
        $_.Name -eq "powershell" -and $_.Id -ne $PID -and $_.WorkingSet -gt 100MB
    } | ForEach-Object {
        try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch {}
    }
    Start-Sleep -Seconds 4
}

function Repair-MissingRows($basePath, $genDir, $csvOut, $jobTag) {
    $caseListPath = Join-Path $genDir "case_list.csv"
    if (-not (Test-Path $caseListPath)) {
        Log "  No case_list.csv - cannot repair $jobTag"
        return
    }

    $caseList = Import-Csv $caseListPath
    $existing = if (Test-Path $csvOut) { @(Import-Csv $csvOut) } else { @() }

    $goodKeys = @($existing | Where-Object {
        $_.HeatTranRatDirty -ne "" -and $_.HeatTranRatDirty -ne "0" -and
        $_.AreaRatioDirty   -ne "" -and $_.AreaRatioDirty   -ne "0" -and
        $_.RunStatus -eq "OK"
    } | ForEach-Object { "$($_.FoulResCS)_$($_.FoulResHS)" })

    $toRepair = @($caseList | Where-Object { "$($_.FoulResCS)_$($_.FoulResHS)" -notin $goodKeys })
    if ($toRepair.Count -eq 0) { Log "  No repair needed for $jobTag"; return }

    Log "  Repairing $($toRepair.Count) missing/bad rows for $jobTag..."

    # Regenerate EDR files from base
    $baseXml = [System.IO.File]::ReadAllText($basePath, [System.Text.Encoding]::UTF8)
    foreach ($c in $toRepair) {
        $fname = "${jobTag}_var_CS$($c.FoulResCS)_HS$($c.FoulResHS).EDR"
        $fpath = Join-Path $genDir $fname
        $xml   = $baseXml
        $xml   = $xml -replace '(?s)(<scalar name="FoulResCS">(?:\s*<uom>[^<]*</uom>\s*)?<value>)[^<]*(</value>)', "`${1}$($c.FoulResCS)`${2}"
        $xml   = $xml -replace '(?s)(<scalar name="FoulResHS">(?:\s*<uom>[^<]*</uom>\s*)?<value>)[^<]*(</value>)', "`${1}$($c.FoulResHS)`${2}"
        [System.IO.File]::WriteAllText($fpath, $xml, [System.Text.Encoding]::UTF8)
    }

    Kill-HeavyPS
    $app = New-Object -ComObject "BJACCOM2.BJACApp"
    Log "  Fresh COM ready"

    # Rebuild CSV: keep good rows, append newly-run rows
    $keepRows = $existing | Where-Object {
        $_.HeatTranRatDirty -ne "" -and $_.HeatTranRatDirty -ne "0" -and
        $_.AreaRatioDirty   -ne "" -and $_.AreaRatioDirty   -ne "0" -and
        $_.RunStatus -eq "OK"
    }
    $colOrder = if ($existing.Count -gt 0) {
        $existing[0].PSObject.Properties.Name
    } else {
        @("filename","FoulResCS","FoulResHS","RunStatus") + $resultFields
    }

    [System.IO.File]::WriteAllText($csvOut, ($colOrder -join ",") + "`n", [System.Text.Encoding]::UTF8)
    $stream = [System.IO.StreamWriter]::new($csvOut, $true, [System.Text.Encoding]::UTF8)
    $stream.AutoFlush = $true

    foreach ($row in $keepRows) {
        $stream.WriteLine(($colOrder | ForEach-Object { $row.$_ }) -join ",")
    }

    $repOk = 0; $repFail = 0
    foreach ($c in $toRepair) {
        $fname = "${jobTag}_var_CS$($c.FoulResCS)_HS$($c.FoulResHS).EDR"
        $fpath = Join-Path $genDir $fname
        try {
            $doc = $app.GetDocument($fpath, $true)
            $doc.Run()      | Out-Null
            $doc.FileSave() | Out-Null
            try { $app.RemoveDocument($fpath) | Out-Null } catch {}
            Start-Sleep -Milliseconds 1500

            $xml        = [System.IO.File]::ReadAllText($fpath, [System.Text.Encoding]::UTF8)
            $resultCode = [regex]::Match($xml, '<result>([^<]*)</result>').Groups[1].Value
            $runStatus  = if ($resultCode -eq "101") { "OK" } else { "FAIL_$resultCode" }
            $scalars    = Extract-Scalars $xml
            $repOk++

            $row = [System.Collections.Generic.List[string]]::new()
            $row.Add($fname); $row.Add($c.FoulResCS); $row.Add($c.FoulResHS); $row.Add($runStatus)
            foreach ($f in $resultFields) { $row.Add($(if ($scalars.ContainsKey($f)) { $scalars[$f] } else { "" })) }
            $stream.WriteLine($row -join ",")
        } catch {
            $repFail++
            Log "  ERROR repairing $fname`: $($_.Exception.Message)"
            $row = [System.Collections.Generic.List[string]]::new()
            $row.Add($fname); $row.Add($c.FoulResCS); $row.Add($c.FoulResHS); $row.Add("ERROR")
            foreach ($f in $resultFields) { $row.Add("") }
            $stream.WriteLine($row -join ",")
        }
    }
    $stream.Close()
    Log "  Repair complete: ok=$repOk fail=$repFail"
}

# ── MAIN BATCH LOOP ──────────────────────────────────────────────────────────
Log "=========================================="
Log "=== BATCH AUTO START: $($jobs.Count) jobs ==="
Log "=========================================="
$batchStart = Get-Date
$jobResults = [System.Collections.Generic.List[hashtable]]::new()

$jobNum = 0
foreach ($entry in $jobs.GetEnumerator()) {
    $jobNum++
    $fname    = $entry.Key
    $jobTag   = $entry.Value
    $basePath = Join-Path $root "base_files\$fname"
    $genDir   = Join-Path $root "generated\$jobTag"
    $csvOut   = Join-Path $resDir "results_$jobTag.csv"

    Log ""
    Log "--- [$jobNum/$($jobs.Count)] JOB: $jobTag ---"

    # Skip if already complete
    $status = Get-ResultStatus $csvOut
    if ($status.clean) {
        Log "  ALREADY DONE (100 clean rows) - skipping"
        $jobResults.Add(@{ tag=$jobTag; result="SKIPPED"; rows=100 })
        continue
    }

    # Verify base file
    if (-not (Test-Path $basePath)) {
        Log "  ERROR: Base file not found: $basePath"
        $jobResults.Add(@{ tag=$jobTag; result="FILE_NOT_FOUND"; rows=0 })
        continue
    }

    New-Item -ItemType Directory -Force -Path $genDir | Out-Null
    $jobSW = [System.Diagnostics.Stopwatch]::StartNew()

    # Run generate_and_run.ps1 as subprocess with 12-min timeout
    Log "  Launching generate_and_run.ps1 (12-min timeout)..."
    $procArgs = "-NonInteractive -File `"$root\generate_and_run.ps1`" -BaseFile `"base_files\$fname`" -JobTag `"$jobTag`" -MaxMultiplier 2.5"
    $proc = Start-Process -FilePath "powershell.exe" `
                          -ArgumentList $procArgs `
                          -WorkingDirectory $root `
                          -PassThru -NoNewWindow
    $completed = $proc.WaitForExit(720000)

    if (-not $completed) {
        Log "  TIMEOUT after 12min - killing subprocess..."
        try { $proc.Kill() } catch {}
        Kill-HeavyPS
    } else {
        $ec = $proc.ExitCode
        if ($ec -ne 0) {
            Log "  Subprocess exited with code $ec - may have crashed"
            Kill-HeavyPS
        }
    }

    # Validate; repair if needed
    $status = Get-ResultStatus $csvOut
    if (-not $status.clean) {
        Log "  Post-run: rows=$($status.rows) bad=$($status.bad) - attempting repair..."
        Repair-MissingRows $basePath $genDir $csvOut $jobTag
        $status = Get-ResultStatus $csvOut
    }

    $jobSW.Stop()
    $elapsed = [math]::Round($jobSW.Elapsed.TotalMinutes, 1)

    if ($status.clean) {
        Log "  PASSED: 100 clean rows in ${elapsed}min"
        $jobResults.Add(@{ tag=$jobTag; result="OK"; rows=100; minutes=$elapsed })
    } else {
        Log "  FAILED after repair: rows=$($status.rows) bad=$($status.bad) elapsed=${elapsed}min"
        $jobResults.Add(@{ tag=$jobTag; result="FAILED"; rows=$status.rows; bad=$($status.bad); minutes=$elapsed })
    }
}

# ── MERGE ALL RESULTS INTO MASTER DATASET ───────────────────────────────────
Log ""
Log "=== MERGING ALL RESULTS ==="

# Special job_id overrides (clean versions replace originals)
$jobIdOverride = @{ "8497_clean" = "8497" }

# Collect all result CSVs - exclude PD files and raw 8497 (superseded by _clean)
$mergeFiles = Get-ChildItem "$resDir\results_*.csv" | Where-Object {
    $_.Name -notmatch "_PD" -and
    $_.Name -ne "results_8497.csv" -and
    $_.Name -ne "results_8537.csv"
} | Sort-Object Name

$masterCsv  = Join-Path $masterDir "master_dataset.csv"
$masterCols = @("job_id","filename","FoulResCS","FoulResHS","RunStatus") + $resultFields
[System.IO.File]::WriteAllText($masterCsv, ($masterCols -join ",") + "`n", [System.Text.Encoding]::UTF8)
$masterStream = [System.IO.StreamWriter]::new($masterCsv, $true, [System.Text.Encoding]::UTF8)
$masterStream.AutoFlush = $true

$totalRows  = 0
$mergeLog   = [System.Collections.Generic.List[string]]::new()

foreach ($f in $mergeFiles) {
    $rawId  = $f.BaseName -replace '^results_', ''
    $jobId  = if ($jobIdOverride.ContainsKey($rawId)) { $jobIdOverride[$rawId] } else { $rawId }
    try {
        $rows = @(Import-Csv $f.FullName | Where-Object { $_.RunStatus -eq "OK" })
        foreach ($row in $rows) {
            $vals = [System.Collections.Generic.List[string]]::new()
            $vals.Add($jobId)
            foreach ($col in @("filename","FoulResCS","FoulResHS","RunStatus") + $resultFields) {
                $v = if ($row.PSObject.Properties.Name -contains $col) { $row.$col } else { "" }
                $vals.Add($v)
            }
            $masterStream.WriteLine($vals -join ",")
            $totalRows++
        }
        $msg = "  $($f.Name) -> job_id=$jobId  $($rows.Count) rows"
        Log $msg; $mergeLog.Add($msg)
    } catch {
        $msg = "  ERROR merging $($f.Name): $($_.Exception.Message)"
        Log $msg; $mergeLog.Add($msg)
    }
}
$masterStream.Close()
Log "Master dataset: $totalRows rows -> $masterCsv"

# ── BATCH SUMMARY REPORT ─────────────────────────────────────────────────────
Log ""
Log "=== WRITING SUMMARY REPORT ==="
$batchEnd = Get-Date
$batchMin = [math]::Round(($batchEnd - $batchStart).TotalMinutes, 1)

$ok      = ($jobResults | Where-Object { $_.result -eq "OK" }).Count
$skipped = ($jobResults | Where-Object { $_.result -eq "SKIPPED" }).Count
$failed  = ($jobResults | Where-Object { $_.result -eq "FAILED" }).Count

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("BATCH AUTO SUMMARY")
$lines.Add("==================")
$lines.Add("Started : $($batchStart.ToString('yyyy-MM-dd HH:mm:ss'))")
$lines.Add("Finished: $($batchEnd.ToString('yyyy-MM-dd HH:mm:ss'))")
$lines.Add("Elapsed : ${batchMin} minutes")
$lines.Add("")
$lines.Add("NEW JOBS: $($jobs.Count) queued  |  OK=$ok  Skipped=$skipped  Failed=$failed")
$lines.Add("")
$lines.Add("JOB RESULTS:")
foreach ($jr in $jobResults) {
    $tag = $jr.tag.PadRight(14)
    $res = $jr.result.PadRight(10)
    $ext = if ($jr.rows)    { "rows=$($jr.rows)" }    else { "" }
    $ext+= if ($jr.minutes) { "  time=$($jr.minutes)min" } else { "" }
    $ext+= if ($jr.bad)     { "  bad=$($jr.bad)" }    else { "" }
    $lines.Add("  $tag $res $ext".TrimEnd())
}
$lines.Add("")
$lines.Add("MASTER DATASET:")
$lines.Add("  Path : $masterCsv")
$lines.Add("  Rows : $totalRows  (OK rows only, all jobs)")
$lines.Add("  Cols : $($masterCols.Count)  (job_id + filename + FoulResCS/HS + RunStatus + 48 result fields)")
$lines.Add("")
$lines.Add("MERGED FILES:")
foreach ($ml in $mergeLog) { $lines.Add($ml) }
$lines.Add("")
$lines.Add("SKIPPED (not processed - PD/TASC/manual-exclusion):")
$lines.Add("  8369 PD CALCS - REv 3.EDR  (PD file)")
$lines.Add("  8497 PD REV 1.EDR          (PD file)")
$lines.Add("  8537 DUTY REV 0.EDR        (TASC format - AccessViolationException)")

$summPath = Join-Path $masterDir "batch_summary.txt"
[System.IO.File]::WriteAllText($summPath, ($lines -join "`r`n"), [System.Text.Encoding]::UTF8)
Log "Summary -> $summPath"

Log ""
Log "=========================================="
Log "=== ALL DONE. Shutting down in 30s... ==="
Log "=========================================="
Start-Sleep -Seconds 30
Stop-Computer -Force
