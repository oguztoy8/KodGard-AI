# KodGard AI

[English](README.md) | **Türkçe**

Statik tarayıcıları (Semgrep, Gitleaks), Claude yapılandırılmış kod incelemesini ve pgvector tabanlı RAG asistanını birleştiren commit bazlı güvenlik ve kod kalitesi analiz sistemi.

![Commit listesi görünümü](docs/screenshots/01-commits.png)

## Neler Yapar (What it does)

- **Otomatik Commit Dokümantasyonu (`summary` & `detail`)**: İzlenen her commit için 5–10 satırlık Türkçe Markdown özet dokümanı ve dosya bazında değişen fonksiyon/sınıfları, yan etkileri ve statik analiz bulgularını açıklayan detaylı Markdown dokümanı üretir.
- **Çok Kaynaklı Güvenlik ve Kalite Bulguları (Semgrep + Gitleaks + Claude)**:
  - **Semgrep**: Commit ağacından çıkarılan değişen dosyalar üzerinde yerel Python ve JavaScript kurallarını (`rules/python-js.yml`) çalıştırır.
  - **Gitleaks**: Commit aralığını (`<sha>^..<sha>` veya kök commit için `<sha>`) sır sızıntılarına karşı tarar; gizli değeri kaydetmeden yalnızca dosya, satır ve kural kimliğini (`severity: high`, `CWE-798`) kaydeder.
  - **Claude İncelemesi**: Birleştirilmiş diff'i ve ön bulguları yapılandırılmış Pydantic çıktısı ile analiz ederek dokümantasyon ve zorunlu dosya + pozitif satır referanslı ek kod/güvenlik bulguları üretir.
- **Bulgu Yaşam Döngüsü (`open` / `ignored` / `fixed`)**:
  - Her bulgu deterministik bir SHA-256 parmak izine (`source | rule_id | file | line | summary`) sahiptir.
  - Kullanıcılar bir bulguyu zorunlu `ignore_reason` ile `ignored` olarak işaretleyebilir (`PATCH /findings/{id}`); aynı depodaki sonraki commit'lerde aynı parmak izi tekrar görülürse `ignored` durumu ve gerekçesi korunur.
  - Aynı depodaki sonraki bir commit bir dosyayı değiştirdiğinde, o dosyadaki önceki `open` durumundaki bir bulgu tekrar oluşmazsa otomatik olarak `fixed` durumuna geçer.
- **Markdown Dışa Aktarma (Export)**: Özet ve detay raporları doğrudan `<sha8>-summary.md` ve `<sha8>-detail.md` olarak indirilebilir (`GET /commits/{sha}/export?doc=summary|detail`).
- **RAG Asistanı**: Commit özetlerini, detay dokümanlarını, bulguları, diff'leri ve kaynak dosyaları (`<= 200 KB`) `sentence-transformers/all-MiniLM-L6-v2` modeliyle PostgreSQL `pgvector` (`vector(384)`, HNSW kosinüs indeksi) tablosuna indeksler ve soruları Server-Sent Events (`POST /assistant/chat`) üzerinden numaralı kaynak atıflarıyla (`[1]`, `[2]`, ...) yanıtlar.

### Commit Özeti (`02-commit-summary.png`)
![Commit özet görünümü](docs/screenshots/02-commit-summary.png)

### Dosya Bazlı Detaylı Dokümantasyon (`03-commit-detail-doc.png`)
![Commit detaylı dokümantasyon görünümü](docs/screenshots/03-commit-detail-doc.png)

### Bulgular ve Yaşam Döngüsü (`fixed` / `ignored`) (`04-findings.png`)
![Bulgu listesi ve yaşam döngüsü durumları](docs/screenshots/04-findings.png)

### Sabit Kodlanmış Kimlik Bilgisi / Sır Bulguları (`05-secret-finding.png`)
![Sabit kodlanmış parola ve sır bulguları görünümü](docs/screenshots/05-secret-finding.png)

### Kaynak Atıflı RAG Asistanı (`06-assistant.png`)
![RAG asistanı görünümü](docs/screenshots/06-assistant.png)

## Mimari (Architecture)

```mermaid
flowchart LR
    A["git commit"] --> B["post-commit hook"]
    B --> C["POST /enqueue"]
    C --> D["API"]
    D --> E["PostgreSQL scans"]
    E --> F["worker"]
    F --> G["Semgrep Gitleaks Claude"]
    G --> H["docs findings"]
    H --> I["chunks pgvector"]
    H --> J["API"]
    I --> J
    J --> K["React UI"]
```

## Hızlı Başlangıç (Quick start - Docker)

1. Depoyu klonlayın ve dizine girin:
   ```bash
   git clone <repo-url> KodGard-AI
   cd KodGard-AI
   ```
2. `.env.example` dosyasını `.env` olarak kopyalayın; `ANTHROPIC_API_KEY` ve `REPOS_HOST_DIR` (analiz etmek istediğiniz Git depolarını barındıran üst dizin) alanlarını doldurun:
   ```bash
   cp .env.example .env
   ```
3. Servisleri derleyip başlatın:
   ```bash
   docker compose up -d --build
   ```
4. Web arayüzünü `http://localhost:5173` adresinden açın (API sağlık kontrolü: `http://127.0.0.1:8000/health` veya `http://localhost:5173/api/health`).

**Image boyutları ve ilk açılışta model indirme:**
- Ölçülen gerçek Docker image boyutları:
  - `kodgard-backend:latest`: `4.03GB` (Python 3.12, CPU PyTorch, `sentence-transformers`, Semgrep `1.182.1` ve Gitleaks `8.30.1` içerir)
  - `kodgard-frontend:latest`: `94.7MB` (çok aşamalı Node 22 derlemesi, `nginx:alpine` ile sunulur)
  - `pgvector/pgvector:pg16`: `631MB`
- İlk açılışta tek seferlik `model-init` servisi `python -m app.cli download-model` komutunu çalıştırarak yerel embedding modelini (`sentence-transformers/all-MiniLM-L6-v2`) kalıcı `hf_cache` Docker volume'una indirip doğrular; `api` ve `worker` servisleri bu işlem tamamlandıktan sonra başlar.

## Kendi Reponuzu Bağlama (Connect your own repo)

1. **`REPOS_HOST_DIR` ile bağlama**:
   Docker modunda `REPOS_HOST_DIR`, `api` ve `worker` container'ları içine `/repos` altında salt-okunur (`${REPOS_HOST_DIR}:/repos:ro`) olarak bağlanır. Taranacak tüm Git depoları `REPOS_HOST_DIR` altında yer almalıdır.
2. **`post-commit` hook kurulumu**:
   Host üzerinde hedef Git deponuza işaret ederek `scripts/install-hook.sh` betiğini çalıştırın:
   ```bash
   ./scripts/install-hook.sh /path/to/repos/my-project
   ```
   - Hook dizinini `git -C <repo> rev-parse --git-path hooks` ile çözer ve **`core.hooksPath` ayarına kesinlikle dokunmaz**.
   - `.git/hooks/post-commit` dosyasına işaretli bir blok (`# >>> kodgard >>>` ... `# <<< kodgard <<<`) ekler. Mevcut bir `post-commit` dosyası varsa `post-commit.kodgard.bak` olarak yedekler ve mevcut kancayı bozmadan bloğu sona ekler.
   - Yalnızca KodGard bloğunu (veya KodGard tarafından oluşturulan sarmalayıcı dosyayı) kaldırmak için:
     ```bash
     ./scripts/install-hook.sh --uninstall /path/to/repos/my-project
     ```
3. **Geçmiş commit'leri tarama (Backfill)**:
   `/repos` altına bağlı bir depodaki geçmiş (merge olmayan) commit'leri kuyruğa eklemek için:
   ```bash
   docker compose exec worker python -m app.cli backfill --repo /repos/my-project --limit 20
   ```
   `--limit` değeri `1..200` aralığındadır (varsayılan `20`). Her commit bir Claude API çağrısı yaptığı için `--limit` değeri `20` üzerinde olduğunda `--yes` bayrağı zorunludur.
4. **Hook hata günlüğü (`hook.log`)**:
   `post-commit` kancası arka planda asenkron çalışır ve `git commit` işlemini engellememek için her zaman `0` koduyla çıkar. `KODGARD_API_URL` kullanıldığında `POST /enqueue` çağrısı `2xx` dışında bir HTTP kodu döndürürse (veya bağlantı hatasında `000`), zaman damgası ve HTTP kodu şu dosyaya yazılır:
   ```text
   ${XDG_STATE_HOME:-$HOME/.local/state}/kodgard/hook.log
   ```

## Host Modu (Host mode - uv + npm)

PostgreSQL'i (`pgvector`) Docker'da çalıştırırken backend, worker, CLI ve Vite geliştirme sunucusunu doğrudan host üzerinde çalıştırabilirsiniz:

1. **Bağımlılıkları kurun**:
   ```bash
   uv sync
   npm --prefix frontend install
   ```
2. **PostgreSQL'i başlatın ve migration'ları çalıştırın**:
   ```bash
   docker compose up -d db
   uv run python -m app.db migrate
   ```
3. **API sunucusunu çalıştırın**:
   ```bash
   uv run uvicorn app.main:app --port 8000
   ```
4. **Worker'ı çalıştırın**:
   ```bash
   # Bekleyen taramaları bir kez işleyip çık:
   uv run python -m app.cli worker

   # Veya 5 saniyede bir sürekli yokla:
   uv run python -m app.cli worker --loop --interval 5
   ```
5. **Frontend'i (Vite) çalıştırın**:
   ```bash
   npm run --prefix frontend dev
   ```
   (`frontend/package.json` içindeki diğer komutlar: `npm run --prefix frontend build`, `npm run --prefix frontend preview`.)
6. **CLI komutları (`app/cli.py`)**:
   - `uv run python -m app.cli enqueue --repo <path> --sha <sha>`
   - `uv run python -m app.cli list [--repo <path>] [--limit 20]`
   - `uv run python -m app.cli worker [--loop] [--interval 5.0]`
   - `uv run python -m app.cli reindex (--sha <sha> | --all)`
   - `uv run python -m app.cli backfill --repo <path> [--limit 20] [--yes]`
   - `uv run python -m app.cli download-model`

**`KODGARD_HOME` ve `KODGARD_API_URL` farkı:**
- `KODGARD_HOME`, KodGard AI proje kök dizinini gösterir (`migrations/`, `rules/python-js.yml`, `.kodgardignore` dosyalarını bulmak ve CLI modunda hook tarafından çalıştırılmak için kullanılır).
- `KODGARD_API_URL`, HTTP API temel adresini gösterir (örn. `http://127.0.0.1:8000`). `hooks/post-commit` içinde `KODGARD_API_URL` tanımlıysa (`scripts/install-hook.sh` bunu varsayılan olarak dışa aktarır), hook her commit'te `uv` başlatmak yerine `curl -X POST .../enqueue` ile kuyruğa ekleme yapar. `KODGARD_API_URL` boşsa hook `cd "$KODGARD_HOME" && uv run python -m app.cli enqueue` yedek yolunu kullanır.

## Yapılandırma (Configuration)

`.env.example` dosyasındaki tüm anahtarlar:

| Değişken | `.env.example` Varsayılanı | Açıklama |
| :--- | :--- | :--- |
| `KODGARD_BIND` | `127.0.0.1` | Docker portlarının (`db`, `api`, `frontend`) host tarafında bağlanacağı arayüz adresi. |
| `FRONTEND_PORT` | `5173` | Frontend arayüzü için container `8080` portuna eşlenen host portu. |
| `API_PORT` | `8000` | FastAPI sunucusu için container `8000` portuna eşlenen host portu. |
| `DB_PORT` | `5432` | PostgreSQL için container `5432` portuna eşlenen host portu (host modu için). |
| `POSTGRES_USER` | `kodgard` | PostgreSQL kullanıcı adı. |
| `POSTGRES_PASSWORD` | `kodgard` | PostgreSQL parolası (varsayılan değer yalnızca `127.0.0.1` yerel kullanımı içindir). |
| `POSTGRES_DB` | `kodgard` | PostgreSQL veritabanı adı. |
| `DATABASE_URL` | `postgresql://kodgard:kodgard@localhost:5432/kodgard` | Host modu için PostgreSQL bağlantı dizgesi (`docker-compose.yml` container içinde `@db:5432` kullanır). |
| `KODGARD_HOME` | `/path/to/KodGard-AI` | KodGard AI proje kök dizini (yalnızca host modu içindir; Docker'da `/app` olarak ayarlıdır). |
| `ANTHROPIC_API_KEY` | *(boş)* | `worker` (commit inceleme) ve `api` (RAG asistanı) için gerekli Anthropic API anahtarı. |
| `REPOS_HOST_DIR` | *(boş, Compose için zorunlu)* | İncelenecek Git depolarının bulunduğu ve `/repos` altına salt-okunur bağlanan host üst dizini. |
| `REVIEW_MODEL` | `claude-sonnet-5-5` | `app/reviewer.py` tarafından commit dokümantasyonu ve incelemesi için kullanılan Anthropic modeli. |
| `ASSISTANT_MODEL` | `claude-haiku-5-5` | `app/assistant.py` tarafından RAG asistanı yanıtları için kullanılan Anthropic modeli. |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | 384 boyutlu vektör üreten yerel HuggingFace / `sentence-transformers` modeli. |
| `TOP_K_CHUNKS` | `8` | RAG asistanı sorgusu başına getirilecek maksimum bağlam parçası (chunk) sayısı. |
| `HF_TOKEN` | *(boş)* | Opsiyonel HuggingFace token'ı (varsayılan açık model için gerekmez). |

## Gizlilik ve Maliyet (Privacy and cost)

- **Diff'lerin Anthropic API'ye gönderilmesi (`60.000` karakter sınırı)**: Bir commit tarandığında `app/scanner.py` (`prepare_diff`), değişen `.py` ve `.js` dosyalarının (`.gitignore` ve `.kodgardignore` eşleşmeleri hariç) birleştirilmiş diff'ini oluşturur ve toplam diff boyutunu `MAX_DIFF_CHARS = 60000` karakterle sınırlar. Bu diff ve temizlenmiş ön bulgu üst verileri Anthropic API'ye (`REVIEW_MODEL`) gönderilir. Aracı kurum içi veya regüle kod tabanlarında kullanmadan önce kurumunuzun veri politikasını ve Anthropic API kullanım/saklama koşullarını kontrol edin.
- **İşlem başına model çağrıları**:
  - **Taranan her commit** **1** adet `REVIEW_MODEL` çağrısı yapar (`max_tokens=4096`, `temperature=0`, hata durumunda en fazla 2 yeniden deneme).
  - **Her asistan sorusu** (indekslenmiş chunk varsa) getirilen chunk'lar (`<= 8` chunk, her biri en fazla `1.500` karakter) ve son `6` sohbet geçmişi mesajıyla **1** adet akışlı (streaming) `ASSISTANT_MODEL` çağrısı (`max_tokens=1024`) yapar.
  - **Embedding üretimi** CPU üzerinde yerel olarak `sentence-transformers` ile çalışır (dış embedding API çağrısı yapılmaz).
- **Sırların işlenmesi ve sınırları**:
  - `parse_gitleaks_output` hiçbir zaman ham sır değerini veritabanına (`findings` tablosu) veya `pre_findings` verisine kaydetmez.
  - `filter_secret_safe_files` (`app/indexer.py`), ilgili depoda geçmişte veya o commit'te `source='gitleaks'` bulgusu olan dosyaları `diff` ve `file` RAG chunk'larından tamamen çıkarır; böylece sır bulaşmış dosyaların ham içerikleri asistan indeksine (`chunks`) girmez.
  - **Ancak**, bir `.py` veya `.js` dosyasının diff'i içinde açık bir sır varsa, bu diff commit inceleme aşamasında `REVIEW_MODEL`'e gönderilir (sistem istemi modele sır değerlerini çıktıda tekrarlamamasını emretse bile diff inceleme modeline gider).
- **Container ortam değişkeni görünürlüğü**: `api` ve `worker` container'ları çalışırken `ANTHROPIC_API_KEY` container ortam değişkeni olarak verilir; host üzerinde `docker` grubundaki herhangi bir kullanıcı `docker inspect` ile bu anahtarı görebilir. (`git`, `semgrep` ve `gitleaks` alt süreçleri başlatılırken `ANTHROPIC_API_KEY` değişkeni `_clean_subprocess_env` / `_clean_git_env` ile ortamdan temizlenir.)

## Güvenlik Notları (Security notes)

- **Kimlik doğrulaması yoktur**: Web arayüzünde ve FastAPI endpoint'lerinde kullanıcı kimlik doğrulaması (auth) veya yetkilendirme bulunmaz.
- **Korumasız `/enqueue`**: Yerel Git hook'larının ek yapılandırma olmadan çağrı yapabilmesi için `POST /enqueue` üzerinde kimlik doğrulaması yoktur.
- **Varsayılan `127.0.0.1` bağlantısı (`KODGARD_BIND`)**: Yayınlanan tüm Docker portları (`db`, `api`, `frontend`) varsayılan olarak `127.0.0.1` arayüzüne bağlanır (`${KODGARD_BIND:-127.0.0.1}`). Güvenilmeyen ağlarda `KODGARD_BIND=0.0.0.0` yapmayın.
- **Varsayılan veritabanı parolası**: Varsayılan `POSTGRES_PASSWORD=kodgard` yalnızca yerel (`127.0.0.1`) kullanım içindir.
- **Uzaktan erişim için SSH tüneli**: Servislere başka bir makineden erişmek için portları dış ağa açmak yerine `KODGARD_BIND=127.0.0.1` bırakıp SSH yerel port yönlendirmesi kullanın:
  ```bash
  ssh -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 <kullanici>@<sunucu>
  ```
- **`/enqueue` dizin kısıtlaması**: `resolve_and_validate_repo` (`app/enqueue.py`), `..` geçişlerini reddeder, sembolik bağlantı (symlink) kaçışlarını önlemek için `realpath` çözümlemesi yapar, hedef deponun (ve `.git` dizininin) yalnızca izin verilen `REPOS_HOST_DIR` / `/repos` altında olmasını zorunlu tutar ve herhangi bir `git` komutu çalıştırmadan önce `.git` varlığını doğrular.

## Bilinen Kısıtlamalar (Known limitations)

- **Diff, Semgrep ve dosya indeksleme yalnızca `.py` ve `.js` içindir**: `app/ignore.py` (`ALLOWED_EXTENSIONS = {".py", ".js"}`) değişen dosyaları yalnızca `.py` ve `.js` uzantılarıyla sınırlar (ve `.gitignore` ile `.kodgardignore` kalıplarını dışlar: `*.lock`, `dist/`, `build/`, `*.min.js`). `rules/python-js.yml` içinde **8** adet yerel Semgrep kuralı bulunur (`kodgard-eval-usage-python`, `kodgard-eval-usage-js`, `kodgard-subprocess-shell-true`, `kodgard-hardcoded-password-python`, `kodgard-hardcoded-password-js`, `kodgard-sql-string-concat-python`, `kodgard-sql-string-concat-js`, `kodgard-innerhtml-assignment`). (Gitleaks commit geçmişini tüm dosya türlerinde tarar.)
- **Hibrit bulgu aramasında en yakın 4 chunk sınırı**: Soru güvenlik niyeti anahtar kelimeleri içerdiğinde `app/assistant.py`, `kind='finding'` türünden en yakın en fazla `FINDING_HYBRID_LIMIT = 4` chunk getirir (genel chunk'larla birleştirilerek toplam `TOP_K_CHUNKS = 8` ile sınırlanır). Çok sayıda bulgu barındıran depolarda ilk 4 vektör eşleşmesi dışındaki bulgular bağlama girmeyebilir.
- **LLM çıktısı hatalı olabilir**: Claude tarafından üretilen özet/detay dokümanlar, ek `source='llm'` bulguları ve RAG asistanı yanıtları yanlış pozitifler, eksiklikler veya hatalı çıkarımlar içerebilir.
- **Genel amaçlı embedding modeli**: `sentence-transformers/all-MiniLM-L6-v2` kod veya güvenlik alanına özel eğitilmiş bir model değil, hafif ve genel amaçlı 384 boyutlu bir modeldir.
- **Tek kullanıcı ve tek worker tasarımı**: Sistem tek bir yerel geliştirici iş akışı ve sıralı çalışan tek bir worker (`SELECT ... FOR UPDATE SKIP LOCKED`) için tasarlanmıştır.
- **Türkçe arayüz ve doküman üretimi**: React arayüzü ile üretilen commit dokümanlarının (`summary_md`, `detail_md` ve tarayıcı bulgu açıklamaları) dili Türkçedir (RAG asistanı sorunun sorulduğu dilde yanıt verir).

## Sorun Giderme (Troubleshooting)

- **`hook.log` dosyasında `http_code=400` (veya `000`)**:
  `${XDG_STATE_HOME:-$HOME/.local/state}/kodgard/hook.log` dosyasını kontrol edin.
  - `http_code=400` genellikle `repo_not_allowed` anlamına gelir: hook tarafından gönderilen repo yolu `REPOS_HOST_DIR` dışındadır (veya `REPOS_HOST_DIR` dışına işaret eden bir sembolik bağlantıdır). Reponun `REPOS_HOST_DIR` altında olduğundan emin olun.
  - `http_code=000`, commit anında `KODGARD_API_URL` adresindeki API'ye ulaşılamadığını gösterir; `docker compose ps` ile servisleri kontrol edin ve servisler açıldığında `backfill` çalıştırın.
- **Worker loglarını inceleme**:
  Bir tarama `pending` durumunda kalıyor veya `failed` oluyorsa worker loglarını izleyin:
  ```bash
  docker compose logs -f worker
  ```
- **`MissingAPIKeyError`**:
  `.env` veya ortam değişkenlerinde `ANTHROPIC_API_KEY` boşsa tarama durumu `RuntimeError` ile `failed` olur (veya asistan sohbeti `{"class": "RuntimeError"}` döndürür). `ANTHROPIC_API_KEY` değerini tanımlayıp `api` ve `worker` servislerini yeniden başlatın (`docker compose up -d api worker`).
- **Docker Compose `REPOS_HOST_DIR tanimlanmali` hatası**:
  `docker-compose.yml` dosyası `${REPOS_HOST_DIR:?REPOS_HOST_DIR tanimlanmali}` kuralını zorunlu tutar. `docker compose` çalıştırmadan önce `.env` içinde geçerli bir `REPOS_HOST_DIR` tanımlayın.
- **`commit_not_found`**:
  Worker bir taramayı `error = commit_not_found` ile başarısız işaretlerse, bağlı repo dizininde ilgili commit SHA'sı bulunamamıştır (ör. commit `amend`/`rebase` sonrası silinmiş veya yanlış dizin bağlanmıştır).

## Geliştirme (Development)

**Testleri çalıştırma:**
```bash
uv run pytest -q
```

**Kısa proje ağacı:**
```text
.
├── app/
│   ├── assistant.py     # RAG geri getirme, istem oluşturma, SSE akışı
│   ├── cli.py           # CLI komutları (enqueue, list, worker, reindex, backfill, download-model)
│   ├── config.py        # Pydantic Settings ve chunk/embedding sabitleri
│   ├── db.py            # PostgreSQL bağlantı havuzu, sorgular ve migration çalıştırıcı
│   ├── enqueue.py       # Repo dizin kapsam doğrulaması ve commit kuyruklama
│   ├── findings.py      # SHA-256 parmak izi, ignored koruma, fixed durum geçişleri
│   ├── git_reader.py    # Git log/show okuyucu ve kararlı patch-id hesaplama
│   ├── ignore.py        # .py/.js filtreleme, .gitignore ve .kodgardignore eşleştirme
│   ├── indexer.py       # Markdown/diff/kod parçalama, sır güvenli filtreleme, pgvector indeksleme
│   ├── main.py          # FastAPI rotaları (/health, /commits, /findings, /assistant, /enqueue)
│   ├── reviewer.py      # Anthropic yapılandırılmış çıktı ile commit inceleme
│   ├── scanner.py       # Diff hazırlama (60k sınırı), Semgrep ve Gitleaks çalıştırıcıları
│   └── worker.py        # SKIP LOCKED ve güvenli kapanış destekli sıralı tarama worker'ı
├── frontend/            # React 18 + TypeScript + Vite arayüzü (Docker için Nginx yapılandırması)
├── hooks/
│   └── post-commit      # Engelleyici olmayan arka plan post-commit kancası
├── migrations/          # SQL şema dosyaları (001_init.sql, 002_scans_docs_findings.sql, 003_chunks.sql)
├── rules/
│   └── python-js.yml    # Python ve JavaScript için 8 yerel Semgrep kuralı
├── scripts/
│   └── install-hook.sh  # İdempotent post-commit kanca kurucu / kaldırıcı
├── tests/               # Pytest test paketi
├── Dockerfile           # Backend ve worker image tanımı
└── docker-compose.yml   # Tüm yığın orkestrasyonu (db, model-init, api, worker, frontend)
```

**Migration mantığı (`app/db.py`):**
`python -m app.db migrate` komutu çalıştırıldığında, yoksa `schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ)` tablosunu oluşturur, `migrations/*.sql` dosyalarını isim sırasına göre (`001_init.sql`, `002_scans_docs_findings.sql`, `003_chunks.sql`) tarar, henüz `schema_migrations` tablosunda kayıtlı olmayan SQL dosyalarını çalıştırır ve dosya adını aynı transaction içinde kaydeder. Docker modunda `api` container'ı Uvicorn'u başlatmadan önce otomatik olarak `python -m app.db migrate` çalıştırır.

## Üçüncü Taraf Bileşenler (Third-party)

Aşağıdaki lisans türleri yalnızca kurulu paket üst verilerinden (`importlib.metadata` / `package.json`) doğrudan doğrulanabilen paketler için yazılmıştır; diğer tüm harici araçlar, temel container imajları ve geçişli bağımlılıklar kendi lisanslarına tabidir.

**Paket metadata'sından doğrulananlar:**
- **Backend Python paketleri**:
  - `fastapi`: MIT
  - `uvicorn`: BSD-3-Clause
  - `psycopg` / `psycopg-pool`: LGPL-3.0-only
  - `pydantic` / `pydantic-settings`: MIT
  - `python-dotenv`: BSD-3-Clause
  - `anthropic`: Apache-2.0
  - `sentence-transformers`: Apache-2.0
  - `langchain-text-splitters` / `langchain-huggingface`: MIT
  - `torch`: Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib
  - `pytest`: MIT
  - `httpx`: BSD-3-Clause
- **Frontend paketleri**:
  - `react` / `react-dom`: MIT
  - `@tanstack/react-query`: MIT
  - `react-markdown` / `remark-gfm`: MIT
  - `vite` / `@vitejs/plugin-react`: MIT
  - `typescript`: Apache-2.0
- **Harici ikili dosyalar, modeller ve container imajları** (Semgrep, Gitleaks, PostgreSQL / `pgvector`, `sentence-transformers/all-MiniLM-L6-v2`, Nginx, Python, Node.js): her biri kendi lisansına tabidir.

> **Tasarım Notu:** Arayüz stili, `awesome-design-md` koleksiyonundaki Linear'dan çıkarılmış bir `DESIGN.md` dosyasından ilham alır; Linear ile hiçbir bağlantısı yoktur.

## Lisans (License)

Bu proje MIT Lisansı altında lisanslanmıştır — detaylar için [LICENSE](LICENSE) dosyasına bakın.
