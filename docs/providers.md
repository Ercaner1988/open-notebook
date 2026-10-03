# Gömme Sağlayıcıları Kataloğu ve Sağlayıcı Mağazası (Provider Store)

Bu belge, Open Notebook'un **Gelişmiş > Sağlayıcılar** sekmesinde yer alan gömme sunucusu kataloğunu, mimarisini, güvenlik prensiplerini ve yeni sağlayıcı ekleme standartlarını açıklar.

---

## 1. Mimari ve Amaç

Open Notebook'un yerel gömme modelleriyle (bge-embed-rs, Ollama, LM Studio vb.) entegrasyonu, harici kod çalıştırmayan **liste temelli** bir katalog mimarisi ile sağlanır.

### Neden Liste Temelli (Statik Katalog)?
- **Güvenlik:** Eklenti olarak dışarıdan indirilen Python veya JavaScript kodu kütüphaneye ve sisteme doğrudan erişim riski taşır. Liste temelli yapıda kod indirilmez veya çalıştırılmaz.
- **Next.js Standalone Yapısı:** Ön yüz derlenmiş Next.js olduğundan harici arayüz parçaları dinamik olarak yüklenmez.
- **Upstream PR Uyumluluğu:** Küçük, temiz, sürdürülebilir ve ana depoya kolayca entegre edilebilir bir tasarımdır.
- **İndirme Güvenliği:** Katalogdaki indirme bağlantıları yalnızca kullanıcının tarayıcısında yeni bir sekmede açılır; Open Notebook arka planda otomatik indirme veya kurulum yapmaz.

---

## 2. Katalog Biçimi (`catalog.json`)

Katalog, paket verisi olarak `open_notebook/providers/catalog.json` dosyasında saklanır ve `load_catalog()` fonksiyonu ile okunur.

### Alanlar ve Şema
| Alan | Tip | Açıklama |
|---|---|---|
| `id` | `str` | Benzersiz slug (örn. `"bge-embed-rs"`, `"ollama"`) |
| `name` | `str` | Görüntülenen sağlayıcı adı |
| `description` | `{"en": str, "tr": str}` | İngilizce ve Türkçe açıklama metinleri |
| `homepage` | `HttpUrl` (opsiyonel) | Proje ana sayfası |
| `download_url` | `HttpUrl` (https zorunlu) | Resmi indirme / release sayfası |
| `kind` | `Literal["embedding"]` | Sağlayıcı türü (ilk sürümde yalnızca embedding) |
| `base_url` | `str` | Varsayılan API adresi (örn. `"http://127.0.0.1:11435/v1"`) |
| `probe_ports` | `List[int]` | Yoklanacak yerel portlar (örn. `[11434, 11435]`) |
| `health_path` | `str` | Sağlık kontrolü uç noktası (örn. `"/health"`, `"/api/tags"`) |
| `model` | `str` | Model adı (örn. `"bge-m3"`) |
| `dimension` | `int` | Model vektör boyutu (örn. `1024`) |
| `provider_type` | `str` | Open Notebook'taki sağlayıcı türü (`"openai_compatible"`) |
| `credential_name` | `str` | Veritabanında oluşturulacak/aranacak kimlik bilgisi adı |
| `notes` | `str` (opsiyonel) | Kullanıcıya yönelik ek kullanım ipucu/notu |

`load_catalog()` fonksiyonu Pydantic doğrulaması uygular; bozuk veya hatalı bir kayıt varsa tüm listeyi düşürmez, hatayı loglayıp diğer geçerli kayıtları sunar.

---

## 3. Güvenlik Prensipleri

### SSRF (Server-Side Request Forgery) Koruması
- **Yoklama (Probing):** Canlı durum yoklaması yalnızca `127.0.0.1` / `localhost` üzerinde ve katalogda tanımlı `probe_ports` listesindeki portlara yapılır.
- **Keyfi URL Reddi:** `POST /api/providers/{id}/connect` çağrısında gelen `base_url`, loopback veya katalogdaki adres dışında bir adres ise **HTTP 400** ile reddedilir.
- **Yoklama Önbelleği:** Yerel portların gereksiz ağ trafiğiyle boğulmasını önlemek için yoklama sonuçları 5 saniye boyunca bellekte önbelleğe alınır.

### Beş Temel Bağlantı Kuralı
1. **İdempotentlik:** Aynı `credential_name` ya da aynı `base_url` ile bir kimlik bilgisi zaten varsa ikincisi oluşturulmaz, var olan kullanılır/güncellenir. Aynı model `(name, credential)` tekrar oluşturulmaz.
2. **Varsayılanı Ezmeme:** `default_embedding_model` zaten atanmışsa, `make_default=true` açıkça belirtilmedikçe değiştirilmez. Hiç varsayılan model yoksa ilk bağlantıda otomatik atanır.
3. **Boyut Çakışması Kontrolü (HTTP 409):** Mevcut `source_embedding` tablosundaki vektör boyutu sağlayıcının boyutundan farklıysa (örn. 3072 vs 1024) ve model varsayılan yapılmak istenirse, işlem **HTTP 409 Conflict** ile reddedilir (`confirm_dimension_mismatch=true` onayı verilmedikçe).
4. **Varsayılan Model Silme Koruması:** Open Notebook'ta kimlik bilgisi silmek ona bağlı modelleri cascade olarak siler. Bağlantıyı kaldırma (`disconnect`) işlemi, sağlayıcının modeli şu anda varsayılan model ise **HTTP 400** ile reddedilir ("Önce başka bir varsayılan seçin").
5. **Gömme Doğrulaması:** Başarılı bağlantı sonrasında arka planda `test_individual_model()` çalıştırılarak gömme boyutu ve test cevabı bağlantı yanıtında döndürülür.

---

## 4. Yeni Sağlayıcı Ekleme Rehberi

Yeni bir yerel gömme sunucusu eklemek için:

1. `open_notebook/providers/catalog.json` dosyasına yeni bir JSON nesnesi ekleyin.
2. `download_url` adresinin geçerli bir `https://` bağlantısı olduğundan emin olun.
3. Sağlayıcının sağlık adresini (`health_path`), portunu (`probe_ports`) ve model boyutunu (`dimension`) kesin olarak doğrulayın. Emin olunmayan alanları tahmin yoluyla eklemeyin.
4. `uv run --with pytest --with pytest-asyncio pytest tests/test_provider_catalog.py` ile kataloğun şemaya uygunluğunu doğrulayın.
