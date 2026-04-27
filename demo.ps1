$GW = "http://localhost:8000"

function Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Err($msg)  { Write-Host "[!!] $msg" -ForegroundColor Red }

function Get-Token {
    $login = Invoke-RestMethod -Uri "$GW/token" -Method Post `
        -ContentType "application/x-www-form-urlencoded" `
        -Body "username=admin&password=Admin123!"
    return $login.access_token
}

function Add-ToCart($token, $productId) {
    $body = "{`"product_id`":$productId,`"quantity`":1}"
    Invoke-RestMethod -Uri "$GW/cart/items" -Method Post `
        -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $token" } `
        -Body $body | Out-Null
}

# ── PHASE 1: always_on (100%) ─────────────────────────────────────────────────

Clear-Host
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  PHASE 1: always_on Sampling (100%)" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan

$env:LATENCY_SPORADIC_ENABLED = "true"
$env:LATENCY_SPORADIC_PROB    = "0.7"
$env:LATENCY_SPORADIC_MIN_MS  = "300"
$env:LATENCY_SPORADIC_MAX_MS  = "1500"
$env:SAMPLING_STRATEGY        = "always_on"

Step "Docker starten + Jaeger-Traces loeschen"
docker compose up -d 2>&1 | Out-Null
docker compose restart jaeger 2>&1 | Out-Null

for ($i = 1; $i -le 20; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "$GW/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { Ok "Gateway bereit"; break }
    } catch {}
    Start-Sleep -Seconds 2
}

Step "Admin + Produkt einrichten"
$userBody = '{"username":"admin","password":"Admin123!"}'
try { Invoke-RestMethod -Uri "$GW/auth/register" -Method Post -ContentType "application/json" -Body $userBody | Out-Null } catch {}
try {
    Invoke-RestMethod -Uri "$GW/auth/internal/create_admin" -Method Post `
        -ContentType "application/json" `
        -Headers @{ "x-internal-key" = "some-internal-key" } `
        -Body $userBody | Out-Null
} catch {}

$TOKEN = Get-Token

$productBody = '{"name":"Demo Laptop","description":"BA2 Testobjekt","price":999.99,"stock":10}'
try {
    $product = Invoke-RestMethod -Uri "$GW/products/" -Method Post `
        -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $TOKEN" } `
        -Body $productBody
    $PRODUCT_ID = $product.id
    Ok "Produkt ID=$PRODUCT_ID"
} catch {
    $PRODUCT_ID = 1
    Ok "Nehme Produkt ID=1"
}

Step "10x Order senden (alle werden getracet)"
for ($i = 1; $i -le 10; $i++) {
    $TOKEN = Get-Token
    Add-ToCart $TOKEN $PRODUCT_ID
    try {
        $order = Invoke-RestMethod -Uri "$GW/orders" -Method Post -Headers @{ Authorization = "Bearer $TOKEN" }
        Ok "Order $i  (ID=$($order.id))"
    } catch {
        Err "Order $i fehlgeschlagen"
    }
}

Write-Host ""
Write-Host "-> Jaeger: http://localhost:16686" -ForegroundColor Yellow
Start-Process "http://localhost:16686"

Write-Host ""
Write-Host "ENTER druecken fuer PHASE 2 (Head-based 10%)..." -ForegroundColor White
Read-Host | Out-Null

# ── PHASE 2: head-based (10%) ─────────────────────────────────────────────────

Write-Host "=================================================" -ForegroundColor Magenta
Write-Host "  PHASE 2: Head-based Sampling (10%)" -ForegroundColor Magenta
Write-Host "=================================================" -ForegroundColor Magenta

$env:SAMPLING_STRATEGY   = "head"
$env:SAMPLING_HEAD_RATE  = "0.1"

Step "Jaeger leeren + Services mit head 10% neu starten"
docker compose restart jaeger 2>&1 | Out-Null
docker compose up -d 2>&1 | Out-Null
Start-Sleep -Seconds 5
Ok "Traces geloescht, Strategie gewechselt"

Step "10x Order senden (nur ~1 wird getracet)"
for ($i = 1; $i -le 10; $i++) {
    $TOKEN = Get-Token
    Add-ToCart $TOKEN $PRODUCT_ID
    try {
        $order = Invoke-RestMethod -Uri "$GW/orders" -Method Post -Headers @{ Authorization = "Bearer $TOKEN" }
        Ok "Order $i  (ID=$($order.id))"
    } catch {
        Err "Order $i fehlgeschlagen"
    }
}

Write-Host ""
Write-Host "-> Jaeger: http://localhost:16686" -ForegroundColor Yellow
Write-Host "   Finished" -ForegroundColor Yellow
