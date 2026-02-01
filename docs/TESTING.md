# Sentient Planner - Postman Test Rehberi

## 🚀 Hızlı Başlangıç

### 1. Postman Collection'ı İçe Aktar
1. Postman'i aç
2. **Import** → **File** → `postman_collection.json` seç
3. Collection "Sentient Planner API" olarak görünecek

### 2. Variables'ları Ayarla
Collection'ın **Variables** sekmesine git ve şunları güncelle:

| Variable | Değer |
|----------|-------|
| `api_id` | `i83jhjhpbl` |
| `jwt_token` | Aşağıdaki token'ı kopyala |

### 3. JWT Token Üret
PowerShell'de çalıştır:
```powershell
python scripts/generate_token.py --user-id user1 --secret "sentient-planner-dev-secret-key-2026"
```

Veya mevcut token'ı kullan (24 saat geçerli):
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMSIsImVtYWlsIjoidXNlcjFAZXhhbXBsZS5jb20iLCJleHAiOjE3NzAwNTAzMjAsImlhdCI6MTc2OTk2MzkyMH0.MkARKeBjxpMZJSpYjw-gAnSv-4DmaziL--UeLu-8yfA
```

---

## 📋 API Endpoints

### Base URL
```
http://localhost:4566/restapis/i83jhjhpbl/dev/_user_request_
```

### 1. Health Check (Auth gerektirmez)
```
GET http://localhost:4566/_localstack/health
```

### 2. POST /analyze - Metin Analizi
```http
POST http://localhost:4566/restapis/i83jhjhpbl/dev/_user_request_/analyze
Content-Type: application/json
Authorization: Bearer <JWT_TOKEN>

{
  "text": "I am feeling stressed about work but excited about my new project",
  "userId": "user1"
}
```

### 3. GET /plan/{userId} - Plan Getir
```http
GET http://localhost:4566/restapis/i83jhjhpbl/dev/_user_request_/plan/user1
Authorization: Bearer <JWT_TOKEN>
```

---

## 🔧 Lambda'ları Doğrudan Test Et

API Gateway bypass ederek Lambda'ları doğrudan çağırabilirsin:

### Auth Lambda
```http
POST http://localhost:4566/2015-03-31/functions/sentient_planner_auth/invocations
Content-Type: application/json

{
  "authorizationToken": "Bearer <JWT_TOKEN>",
  "methodArn": "arn:aws:execute-api:us-east-1:000000000000:i83jhjhpbl/dev/POST/analyze"
}
```

### Processor Lambda
```http
POST http://localhost:4566/2015-03-31/functions/sentient_planner_processor/invocations
Content-Type: application/json

{
  "Records": [
    {
      "kinesis": {
        "data": "eyJ0ZXh0IjoiSSBhbSBmZWVsaW5nIGhhcHB5IHRvZGF5ISIsInVzZXJJZCI6InVzZXIxIn0=",
        "sequenceNumber": "123",
        "partitionKey": "user1"
      },
      "eventSource": "aws:kinesis"
    }
  ]
}
```

> **Not:** `data` alanı base64 encoded JSON: `{"text":"I am feeling happy today!","userId":"user1"}`

---

## 🔄 Lambda Hot Reload

Kod değişikliklerini anında deploy etmek için:

### Tek Lambda Deploy
```powershell
# Auth Lambda
.\scripts\deploy-lambda.ps1 auth

# Processor Lambda
.\scripts\deploy-lambda.ps1 processor

# Plan API Lambda
.\scripts\deploy-lambda.ps1 plan_api

# Tümünü deploy
.\scripts\deploy-lambda.ps1 all
```

### Watch Mode (Otomatik Deploy)
```powershell
.\scripts\deploy-lambda.ps1 -Watch
```
Bu mod:
- `src/lambdas/` klasöründeki `.py` dosyalarını izler
- Değişiklik algılandığında otomatik deploy eder
- `Ctrl+C` ile durdurulur

---

## 🧪 Curl ile Test

### POST /analyze
```bash
curl -X POST "http://localhost:4566/restapis/i83jhjhpbl/dev/_user_request_/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMSIsImVtYWlsIjoidXNlcjFAZXhhbXBsZS5jb20iLCJleHAiOjE3NzAwNTAzMjAsImlhdCI6MTc2OTk2MzkyMH0.MkARKeBjxpMZJSpYjw-gAnSv-4DmaziL--UeLu-8yfA" \
  -d '{"text": "I am feeling happy today!", "userId": "user1"}'
```

### GET /plan/{userId}
```bash
curl "http://localhost:4566/restapis/i83jhjhpbl/dev/_user_request_/plan/user1" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMSIsImVtYWlsIjoidXNlcjFAZXhhbXBsZS5jb20iLCJleHAiOjE3NzAwNTAzMjAsImlhdCI6MTc2OTk2MzkyMH0.MkARKeBjxpMZJSpYjw-gAnSv-4DmaziL--UeLu-8yfA"
```

---

## 📊 DynamoDB'yi Kontrol Et

```powershell
aws --endpoint-url http://localhost:4566 --region us-east-1 --no-cli-pager dynamodb scan --table-name sentient-planner-table
```

---

## ⚠️ Troubleshooting

### Token Expired
Yeni token üret:
```powershell
python scripts/generate_token.py -u user1 -s "sentient-planner-dev-secret-key-2026"
```

### API Gateway ID Değişti
Güncel ID'yi al:
```powershell
aws --endpoint-url http://localhost:4566 --region us-east-1 --no-cli-pager apigateway get-rest-apis --query "items[0].id" --output text
```

### Lambda Çalışmıyor
1. Lambda'ları yeniden deploy et: `.\scripts\deploy-lambda.ps1 all`
2. Terraform'u yeniden uygula: `tflocal apply -auto-approve`
