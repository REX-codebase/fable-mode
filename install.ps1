# ==============================================================================
# FABLE-MODE: Frontier Cognitive Engine & Deterministic System 2 Installer
# Independent REX-codebase project; installs into a host-compatible MCP layout
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$SkipTests = $false,
    [switch]$RegisterMcp = $false,
    [string]$TargetDir = "$HOME\.gemini"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "`n[+] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Alert {
    param([string]$Message)
    Write-Host "  [!] $Message" -ForegroundColor Yellow
}

Write-Host @"
================================================================================
   ______ ___     ____   __     ______       __  ___ ____   ____   ______
  / ____//   |   / __ ) / /    / ____/      /  |/  // __ \ / __ \ / ____/
 / /_   / /| |  / __  |/ /    / __/  ______/ /|_/ // / / // / / // __/   
/ __/  / ___ | / /_/ // /___ / /___ /_____/ /  / // /_/ // /_/ // /___   
/_/    /_/  |_|/_____//_____//_____/      /_/  /_/ \____//_____//_____/   
                                                                          
  Deterministic System 2 Deliberation • Mechanical Time-Lock • 0 Dependencies
================================================================================
"@ -ForegroundColor Magenta

# Step 1: Verify Python Environment
Write-Step "Checking Python runtime environment..."
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found in PATH."
    }
    Write-Success "Found Python: $pythonVersion"
} catch {
    Write-Error "Python 3.10+ is required to run the Fable-Engine MCP server. Please install Python and retry."
    exit 1
}

# Step 2: Resolve Directories
$SourceRoot = $PSScriptRoot
$EngineSource = Join-Path $SourceRoot "fable_engine"
$SkillSource = Join-Path $SourceRoot "skills\fable-mode"

$McpTarget = Join-Path $TargetDir "antigravity\mcp\fable-engine"
$SkillTarget = Join-Path $TargetDir "config\skills\fable-mode"
$RulesTarget = Join-Path $TargetDir "config\rules"

Write-Step "Configuring directory layouts..."
New-Item -ItemType Directory -Path $McpTarget -Force | Out-Null
New-Item -ItemType Directory -Path $SkillTarget -Force | Out-Null
New-Item -ItemType Directory -Path $RulesTarget -Force | Out-Null
Write-Success "Target directories prepared at $TargetDir"

# Step 3: Deploy MCP Server & Schema
Write-Step "Deploying Fable-Engine MCP Server..."
Copy-Item -Path (Join-Path $EngineSource "server.py") -Destination (Join-Path $McpTarget "server.py") -Force
Copy-Item -Path (Join-Path $EngineSource "fable_session.json") -Destination (Join-Path $McpTarget "fable_session.json") -Force
Write-Success "MCP Server deployed to: $McpTarget"

# Step 4: Deploy Fable-Mode Skill & References
Write-Step "Deploying Fable-Mode Cognitive Protocols & Reference Manuals..."
Copy-Item -Path "$SkillSource\*" -Destination $SkillTarget -Recurse -Force
Write-Success "Cognitive skill installed to: $SkillTarget"

# Step 5: Run Automated Invariant & MCP Test Suites
if (-not $SkipTests) {
    Write-Step "Executing Fable-Engine verification suite..."
    $testScript = Join-Path $EngineSource "test_server.py"
    $testOutput = python $testScript 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Fable-Engine verification suite PASSED."
    } else {
        Write-Host $testOutput -ForegroundColor Red
        throw "Fable-Engine verification failed; installation aborted."
    }
}

# Step 6: Register the server without clobbering existing MCP entries.
if ($RegisterMcp) {
    Write-Step "Registering fable-engine with the MCP host..."
    $McpConfig = Join-Path $TargetDir "antigravity\mcp_config.json"
    $McpConfigDir = Split-Path -Parent $McpConfig
    New-Item -ItemType Directory -Path $McpConfigDir -Force | Out-Null
    $config = [ordered]@{}
    if (Test-Path $McpConfig) {
        try {
            $rawConfig = Get-Content -Raw -Path $McpConfig
            if ($rawConfig.Trim()) {
                $parsedConfig = $rawConfig | ConvertFrom-Json
                foreach ($property in $parsedConfig.PSObject.Properties) {
                    $config[$property.Name] = $property.Value
                }
            }
        } catch {
            throw "Existing MCP config is invalid JSON; installation aborted without modifying it."
        }
    }

    if ($RegisterMcp) {
        if (-not $config.Contains("mcpServers") -or $null -eq $config["mcpServers"]) {
            $config["mcpServers"] = [pscustomobject]@{}
        }
        $servers = $config["mcpServers"]
        if ($servers -is [System.Array] -or $servers -is [string] -or $servers -is [ValueType]) {
            throw "Existing MCP config has an invalid mcpServers value; expected a JSON object."
        }
        $entry = [pscustomobject][ordered]@{
            command = "python"
            args = @((Join-Path $McpTarget "server.py"))
        }
        if ($servers.PSObject.Properties.Name -contains "fable-engine") {
            $servers."fable-engine" = $entry
        } else {
            $servers | Add-Member -MemberType NoteProperty -Name "fable-engine" -Value $entry
        }

        if (Test-Path $McpConfig) {
            Copy-Item $McpConfig "$McpConfig.bak" -Force
        }
        $tempConfig = "$McpConfig.tmp"
        $config | ConvertTo-Json -Depth 20 | Set-Content -Path $tempConfig -Encoding UTF8
        Move-Item -Path $tempConfig -Destination $McpConfig -Force
        Write-Success "Registered fable-engine in: $McpConfig"
    }
}

# Step 7: Final Setup Summary
Write-Host @"

================================================================================
 [SUCCESS] Fable-Mode installation completed successfully!
================================================================================

 MCP Host Configuration:
 ------------------------------------
 Location: $McpTarget\server.py
 Schema:   $McpTarget\fable_session.json

 MCP-compatible host mcpServers snippet:
 -----------------------------------------------------
 {
   "mcpServers": {
     "fable-engine": {
       "command": "python",
       "args": [
         "$($McpTarget.Replace('\', '/'))/server.py"
       ]
     }
   }
 }

 Ready to deliberate! Trigger Fable-Mode in your MCP host or set an authority budget.
================================================================================
"@ -ForegroundColor Green

