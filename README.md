# KodGard AI

Commit bazlı güvenlik ve kod kalitesi analiz sistemi.

## Başlatma Notları (Yalnızca Yerel Erişim)

Tüm servisler (PostgreSQL, FastAPI/Uvicorn ve Vite geliştirme sunucusu) yalnızca yerel arayüzde (`127.0.0.1` / `localhost`) çalışacak şekilde yapılandırılmıştır.

### 1. Veritabanı (PostgreSQL)

```bash
docker compose up -d db
uv run python -m app.db migrate
```

PostgreSQL yalnızca `127.0.0.1:5432` adresinden dinler.

### 2. Backend API (Uvicorn)

Uvicorn varsayılan host (`127.0.0.1`) ile çalıştırılır (`--host 0.0.0.0` kullanılmaz):

```bash
uv run uvicorn app.main:app --port 8000
```

### 3. Worker

Bekleyen taramaları işlemek için:

```bash
uv run python -m app.cli worker
```

### 4. Frontend (Vite)

```bash
npm run --prefix frontend dev
```

Dış ortamdan erişim gerektiğinde servisleri dış ağa açmak yerine SSH tüneli kullanın:

```bash
ssh -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 <kullanici>@<sunucu>
```
