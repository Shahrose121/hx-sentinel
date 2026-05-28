# Merge results_8497.csv (Rating) + simulation_8497.csv (Simulation)
# Join key: FoulResCS + FoulResHS
# Rating columns  → <col>_rating
# Simulation cols → <col>_sim
# Shared metadata (filename, FoulResCS, FoulResHS) kept once, unmodified.

$ratingPath = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\results_8497.csv"
$simPath    = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\simulation_8497.csv"
$outPath    = "C:\Apps\pRDEICTIEV mIANTENANCE\EDR_ML\combined_8497.csv"

$ratingRows = Import-Csv $ratingPath
$simRows    = Import-Csv $simPath

# Get column lists
$ratingCols = $ratingRows[0].PSObject.Properties.Name
$simCols    = $simRows[0].PSObject.Properties.Name

# Columns that serve as the join key / shared identity — kept once without suffix
$sharedCols = @("filename","FoulResCS","FoulResHS")

# Build a lookup hashtable for Simulation rows: "CS_HS" → row
$simLookup = @{}
foreach ($sr in $simRows) {
    $key = "$($sr.FoulResCS)_$($sr.FoulResHS)"
    $simLookup[$key] = $sr
}

# Determine final column order:
#   filename, FoulResCS, FoulResHS,
#   then every rating col (excl. shared) with _rating,
#   then every sim col (excl. shared) with _sim
$ratingResultCols = $ratingCols | Where-Object { $_ -notin $sharedCols }
$simResultCols    = $simCols    | Where-Object { $_ -notin $sharedCols }

$allCols = @("filename","FoulResCS","FoulResHS") +
           ($ratingResultCols | ForEach-Object { "${_}_rating" }) +
           ($simResultCols    | ForEach-Object { "${_}_sim"    })

# Build merged rows
$merged = foreach ($rr in $ratingRows) {
    $key  = "$($rr.FoulResCS)_$($rr.FoulResHS)"
    $sr   = $simLookup[$key]   # may be $null if no match

    $obj = [ordered]@{}
    $obj["filename"]  = $rr.filename
    $obj["FoulResCS"] = $rr.FoulResCS
    $obj["FoulResHS"] = $rr.FoulResHS

    foreach ($col in $ratingResultCols) {
        $obj["${col}_rating"] = $rr.$col
    }
    foreach ($col in $simResultCols) {
        $obj["${col}_sim"] = if ($sr) { $sr.$col } else { "" }
    }

    [PSCustomObject]$obj
}

# Write CSV (Export-Csv adds BOM and quotes — use StreamWriter for clean output)
$header = $allCols -join ","
[System.IO.File]::WriteAllText($outPath, $header + "`n", [System.Text.Encoding]::UTF8)
$csvStream = [System.IO.StreamWriter]::new($outPath, $true, [System.Text.Encoding]::UTF8)
$csvStream.AutoFlush = $true

foreach ($row in $merged) {
    $vals = foreach ($col in $allCols) { $row.$col }
    $csvStream.WriteLine($vals -join ",")
}

$csvStream.Close()
Write-Host "Merged $($merged.Count) rows → $outPath"
Write-Host ""

# ── Show first 3 rows ──────────────────────────────────────────────────────────
Write-Host "=== First 3 rows (key columns + selected fields) ==="
$preview = Import-Csv $outPath | Select-Object -First 3
$preview | Format-List filename, FoulResCS, FoulResHS,
                        RunStatus_rating, HtLdTotal_rating, DutyRatio_rating,
                        TempOutSS_rating, TempOutTS_rating,
                        RunStatus_sim, HtLdTotal_sim, DutyRatio_sim,
                        TempOutSS_sim, TempOutTS_sim,
                        FoulResSS_sim, FoulResTS_sim
