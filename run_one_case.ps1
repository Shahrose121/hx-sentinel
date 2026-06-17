# run_one_case.ps1 — runs ONE EDR file via BJAC COM and prints results as CSV line to stdout
# Called by run_sweep_subprocess.ps1 for each case.
# Usage: powershell -File run_one_case.ps1 -FilePath "C:\path\to\file.EDR" -CS "0.000000" -HS "0.000000"
param(
    [Parameter(Mandatory)][string]$FilePath,
    [string]$CS = "",
    [string]$HS = ""
)

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

$fname = [System.IO.Path]::GetFileName($FilePath)

try {
    $app = New-Object -ComObject "BJACCOM2.BJACApp"
    $doc = $app.GetDocument($FilePath, $true)
    $doc.Run()      | Out-Null
    $doc.FileSave() | Out-Null
    try { $app.RemoveDocument($FilePath) | Out-Null } catch {}

    $xml = [System.IO.File]::ReadAllText($FilePath)
    $rc  = [regex]::Match($xml, '<result>([^<]*)</result>').Groups[1].Value
    $runStatus = if ($rc -eq "101") { "OK" } else { "FAIL_$rc" }

    $hits = [regex]::Matches($xml, '(?s)<scalar name="([^"]+)">\s*(?:<uom>[^<]*</uom>\s*)?<value>([^<]*)</value>')
    $scalars = @{}
    foreach ($h in $hits) { $scalars[$h.Groups[1].Value] = $h.Groups[2].Value }

    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.Add($fname); $parts.Add($CS); $parts.Add($HS); $parts.Add($runStatus)
    foreach ($f in $resultFields) {
        $parts.Add($(if ($scalars.ContainsKey($f)) { $scalars[$f] } else { "" }))
    }
    Write-Output ($parts -join ",")
}
catch {
    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.Add($fname); $parts.Add($CS); $parts.Add($HS)
    $parts.Add("ERROR: $($_.Exception.Message -replace ',',';')")
    foreach ($f in $resultFields) { $parts.Add("") }
    Write-Output ($parts -join ",")
}
