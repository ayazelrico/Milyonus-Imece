# İmece onarım akışı

Python doğrulamasında hiçbir aday kapıdan geçemezse sistem bir sonraki turda en iyi üç adayı inceler. Kısmen geçen, çalıştırılmış bir kontrolü hata kodu 1 ile biten, insan kararı gerektirmeyen ve metni 16.000 karakteri aşmayan bir aday varsa bir üreticiye önceki çözümle hata çıktısı verilir. Onarılan çözüm de bağımsız kapılardan geçer.

Yürütülebilir kontrollerin `failure_class` alanı bağımsız kanıtta ve hata arşivinde taşınır:

| Değer | Anlam |
| --- | --- |
| `oracle_missing` | Çalıştırılabilir kontrol metni boş. |
| `oracle_syntax_error` | Üretilen kontrol metni host üzerinde yalnızca `compile` ile derlenemedi; kod host üzerinde çalıştırılmaz. Bu kontrol sandbox başlatılmadan yapılır. |
| `candidate_missing_files` / `candidate_invalid_files` | Adayın Python dosyaları yok veya dosya sözleşmesine aykırı. |
| `sandbox_unavailable` / `sandbox_launch_error` | Sandbox bulunamadı veya süreç başlatılamadı. |
| `timeout` | Süre sınırı aşıldı; nedenin aday mı oracle mı olduğu bilinmez. |
| `docker_infrastructure_error` | Docker 125, 126 veya 127 çıkışıyla komutu çalıştıramadı. |
| `candidate_or_oracle_runtime` | Diğer başarısız süreç çıkışları; `AssertionError` dahil, hangi tarafın hatalı olduğunu kanıtlamaz. |

Başarıda alan `null` olur. Her başarısız kontrol kapıyı kapalı tutar. Kesin oracle ve altyapı hataları hedefli üretici onarımına gerekçe sayılmaz; karma sonuçlarda ayrı bir uygun hata kodu 1 gözlemi varsa aday yine seçilebilir. Süre aşımı tek başına seçim gerekçesi değildir. Eski kayıtlarda alan bulunmayabilir: neden tahmin edilmez, önceki seçim davranışı korunur ve arşivde sınıf `null` olur. Arşiv aynı tanı satırını farklı sınıflar için ayrı gruplar.

İsteğe bağlı `[imece]` ayarı `adaptive_production = true` ilk turdaki üretici sayısını yaklaşım sayısı ve çerçeveleme sırasında kaydedilen farklı görüşlerle sınırlar. Sonraki turlar yalnızca önceki turun en son bağımsız kapı raporlarını kullanır; ilk adaylar, revizyon, entegrasyon veya cilalama aşamasındaki eski bir başarısızlık daha yeni kapı kanıtının yerine geçmez.

Yukarıdaki onarım koşullarına uyan kısmen başarılı bir aday varsa üretim bir hedefli onarım ve adayın yaklaşımından farklı her güncel yaklaşım için bir üreticiye daralır. Diğer durumlarda başarısız kontrol kimliği, hata sınıfı ve çıktının son tanı satırı birlikte farklı hata gözlemlerini ayırır; yüksek veya kritik bağımsız bulgular da kaynak, önem ve metinleriyle sayılır. Aynı gözlemin farklı adaylarda tekrarlanması ek üretici gerekçesi değildir. Genişlik, yaklaşım sayısı artı farklı gözlem sayısının bir eksiğini kapsayacak şekilde artırılır; önceki genişliğin altına inmez ve yapılandırılmış üretim kapasitesini aşmaz. Çalışma zamanı hataları adayın hatalı olduğunu tek başına kanıtlamaz.

Kesin oracle/altyapı hataları, süre aşımı, sınıfı bilinmeyen yürütme hataları ve geçersiz bağımsız inceleme raporları genişleme gerekçesi değildir. Yalnızca bu gözlemler varsa veya kullanılabilir kapı kanıtı yoksa önceki genişlik korunur. Böylece aynı altyapı hatasının tekrarı her tur üretimi büyütmez. Kapı 3 reddi de tek başına üretim kapasitesini artırmaz.

`RunResult.production_schedule` ve JSON raporundaki aynı alan, üretim planlanan her tur için `round`, `builders` ve somut seçim gerekçesini taşıyan `reason` alanlarını kaydeder. `builders`, seçilen normal üretici sayısıdır; keşif ajanlarını veya tamamlanmış çağrı sayısını içermez. Uyarlama kapalıyken her tur yapılandırılmış üretim dağılımı kullanılır. Keşif, bağımsız değerlendirme, onay ve veto kuralları kendi davranışlarını korur.

Bir rapordaki başarısız kontrolleri tekrar incelemek için aşağıdaki komut hata çıktısının son satırına göre gruplandırılmış yerel bir dosya üretir. Her örnek görev, tekrar, aday ve kontrol kimliğini taşır. Aynı tanı satırı farklı nedenlerden kaynaklanabilir.

```sh
uv run python -m evals.imece.failures run.json --out failure-families.json
```

Arşiv, aile başına farklı görev ve görev/tekrar sayılarını da verir. Tam
çıktısı kayıtlı, Python kaynağı eşleşen ve dönüş kodu 1 olan çalışma zamanı
hatası varsa `repair_template` altında inceleme taslağı üretir. Taslak önce
hatalı tarafın aday mı kontrol mü olduğunun belirlenmesini, küçük onarımı,
bağımsız yeniden yürütmeyi ve kaynak geçersizleşme koşullarını içerir.
Altyapı hataları ve eksik/kesilmiş çıktı için şablon üretilmez. Aynı tanı
satırı ortak neden kanıtı değildir; farklı görev sayısı bağımsız doğrulama
yerine geçmez. Bu taslak doğrulanmış onarım veya canlı beceri değildir;
beceri dosyası yazmaz ve yükseltme kapısını çalıştırmaz.

Ajanın oluşturduğu veya güncellediği beceri, kendi örneği çalıştıktan sonra hazırlık dizininde bekler. Operatör, ayrı görevleri temsil eden en az iki bağımsız kontrol dosyası seçer. Görevlerin bağımsızlığı operatörün sorumluluğundadır. Sistem farklı görev etiketleri, farklı Python kontrol kodları ve çalıştırılabilir doğrulama ifadeleri arar.

Örnek bir manifest:

```json
{"empty-invoice": "checks/empty_invoice.py", "refund-reconciliation": "checks/refund.py"}
```

```sh
milyonus skills promote-repair reconcile-invoice replay-manifest.json
milyonus skills view reconcile-invoice replays.json
milyonus skills revoke-oracle ORACLE_SHA256
```

Yükseltme komutu manifestteki en az iki kontrolü ve becerinin yeniden üretilebilirlik kapısını çalıştırır. Canlı becerideki `replays.json`, tam beceri metninin SHA-256 özetini, yürütme arka ucunu ve görev etiketi → oracle SHA-256 eşlemesini kaydeder; kontrol dosyalarının yollarını veya içeriklerini saklamaz. Oracle özeti, yüklenen Python kontrol metninin UTF-8 kodlamasından hesaplanır; dosya metin olarak okunurken satır sonları normalleştirilebilir. Onay ve yetki politikaları uygulama kodunda tanımlıdır.

`revoke-oracle`, küçük harfli 64 haneli bir SHA-256 özeti kabul eder. Önce canlı katalog kökündeki `_revoked_oracles/<özet>` boş işaret dosyasını kalıcı olarak oluşturur ve dosya/dizinleri `fsync` ile eşitler; ardından o özeti makbuzunda taşıyan canlı sürümleri `_revoked/` altına taşır. Eşleşen canlı beceri olmasa da kayıt tutulur. Tekrar iptal etmek güvenlidir; dönen adlar yalnızca o çağrıda arşivlenen sürümlerdir, kayıt sayısı değildir. Arşivleme sırasında hata çıkarsa komut hata verebilir ve arşivleme kısmi kalabilir; önceden yazılmış iptal kaydı korunur. Eksik, okunamayan veya bozuk makbuzlar arşiv taramasında atlanır ve yükleyicide reddedilir. İptali geri alma komutu yoktur.

Yükseltme, oracle özetlerini tekrar çalıştırmadan önce ve yayımlamadan hemen önce denetler. İptal edilmiş bir özet varsa yükseltme reddedilir; hazırlık dosyası korunur. Aynı oracle başka bir hazırlık becerisinde de kullanılamaz. Her canlı yükleme makbuzdaki bütün oracle özetlerini yeniden denetler; arşivleme başarısız olsa veya eski canlı sürüm elle geri taşınsa bile iptal kaydı kaldığı sürece örnek kabul edilmez. Kayıt dizini yoksa eski katalogla uyumluluk için iptal listesi boş sayılır; mevcut dizin açılamıyorsa işlem reddedilir. Bir özet adına sahip herhangi bir dizin girdisi, bozuk veya sembolik bağlantı olsa da, o özeti engeller.

Yayımlama, iptal kaydı/arşivleme ve canlı yükleme, katalogdaki `.repair-catalog.lock` normal dosyası üzerinde aynı yerel POSIX `flock` kilidini kullanır. Normal beceri oluşturmanın canlıya taşıması ve silme de bu kilide uyar. Yükseltmenin bağımsız tekrarları ve yeniden üretilebilirlik kapısı kilit dışında beklenir; son iptal denetimi ile canlı dizin değişimi tek kilit bölgesindedir. Böylece iptal önce gerçekleşirse devam eden yükseltme yayımlayamaz; yayımlama önce gerçekleşirse iptal yeni sürümü de tarar. Yükleme, doğrulama ve iptal denetimini aynı kilit altında tamamlar. Kök, kilit ve iptal dizini açılırken sembolik bağlantı izlenmez. Yükleme kilit dosyasını gerekirse oluşturduğundan katalog üzerinde buna uygun yazma izni de gerekir.

Bu kilit aynı yerel katalog ve kilit dosyasını kullanan işbirlikçi süreçleri koordine eder; dağıtık kilit veya dosya sisteminin dışarıdan değiştirilmesine karşı koruma sağlamaz. Kilit dosyası silinmemeli/değiştirilmemelidir. Daha önce yüklenmiş bir örnek veya başlamış ajan çağrısı sonradan iptal edilerek geri çekilemez; iptal sonraki yüklemeleri engeller. Kayıtlar, makbuzlar ve katalog operatörün güven sınırındadır: bunları silebilen/değiştirebilen bir taraf engeli aşabilir. Özet yalnızca aynı kontrol metnini engeller; anlamsal olarak eşdeğer farklı metin farklı özet alır. Eski yalnızca-arşivleme uygulamasının geçmiş iptalleri otomatik çıkarılmaz; bu özetler yeni komutla tekrar iptal edilmelidir. Dizin yayımlama/arşivleme işlemleri tam bir çökme kurtarma işlemi değildir; `fsync` başarısı da depolama aygıtının garantileriyle sınırlıdır.

P4 beceri kullanımı operatörün açık seçimine bağlıdır. `[imece]` altında `repair_skill = "reconcile-invoice"` ayarı, normal CLI koşusunda, CLI değerlendirmesinde ve `evals/imece/run.py --config ...` değerlendirme koşucusunda aynı şekilde uygulanır. Varsayılan `None` değeridir; TOML dosyasında ayarı yazmamak kullanımı kapatır. Bu ayar onarım seçme koşullarını değiştirmez ve tek başına onarım başlatmaz.

Yerel yükleyici her hedefli onarımda beceri içeriği olarak yalnızca canlı `skills/<ad>/SKILL.md` ve `replays.json` dosyalarını okur; ayrıca katalog kilidini ve kalıcı oracle iptal kayıtlarını denetler. Ad en fazla 64 ASCII harf/rakam, alt çizgi veya kısa çizgiden oluşur ve harf/rakamla başlar. Yol bileşenlerinde ve dosyalarda sembolik bağlantı kabul edilmez; dizin dışına çıkılmaz. Dosyalar normal dosya olmalıdır. Tam `SKILL.md` baytlarının SHA-256 özeti makbuzdaki `skill_sha256` ile, belgedeki ad seçilen adla eşleşmelidir. Makbuzda en az iki farklı, boş olmayan görev etiketi ve iki farklı geçerli oracle SHA-256 özeti bulunmalıdır. Güvenlik taraması uyarı dahil bulgu verirse beceri reddedilir. Belge en fazla 65.536 bayt, makbuz 32.768 bayt ve gövde 1–6.000 karakter olabilir; fazla içerik kesilerek kabul edilmez.

Kabul edilen gövde yalnızca mevcut `repair` ajanının bağlamına, JSON içinde **güvenilmeyen prosedür örneği** olarak eklenir. Sistem istemine, role, hedefe veya başarı ölçütlerine taşınmaz; araç, yetki, donmuş sözleşme, bağımsız kapı ve insan onayı kurallarını değiştiremez. Referans dosyaları yüklenmez ve beceri kodu yükleyici tarafından çalıştırılmaz. Diğer üreticiler ve değerlendirme ajanları bu örneği almaz.

Eksik, iptal edilmiş, değiştirilmiş veya geçersiz beceri kullanılmaz; normal hedefli onarım örneksiz devam eder ve ilgili tur için `RunResult.warnings` alanına ret gerekçesi eklenir. Kullanılan örnekler `RunResult.applied_repair_skills` ve JSON raporundaki aynı alanda `round`, `name`, `skill_sha256` ile kaydedilir. Onarım yoksa veya beceri reddedilirse kullanım kaydı oluşmaz. Makbuz yerel operatör güvenine dayanır; dijital imza değildir. Hem belgeyi hem makbuzu yeniden yazabilen bir tarafı bu özet kontrolü doğrulayamaz. Görevlerin gerçekten bağımsız olması yükseltmeyi yapan operatörün sorumluluğudur.

Bu akışların başarı ve maliyet üzerindeki etkisi karşılaştırmalı koşularda henüz ölçülmedi.

Yürütücü çıktı sınırı aşıldığında veya kapı raporu çıktıyı 2000 karaktere
kısalttığında `output_truncated=true` kaydedilir. Uyarlamalı durgunluk duruşu
bu kayıtları kullanmaz; alanı olmayan eski raporlar da tam çıktı kanıtı
sayılmaz. Böylece yalnızca aynı başlangıcı görünen farklı hata çıktıları
eşit kabul edilmez. Geçici yollar ve deterministik olmayan çıktılar yine
eşleşmeyi engelleyebilir.

Kanıt önbelleği, içerik sağlama toplamına ek olarak yürütme sonucunun tüm alanlarını
denetler. Başarı bayrağı gerçek `true`, dönüş kodu gerçek tamsayı sıfır, çıktı
metin, backend `docker` ve hata sınıfı boş olmalıdır. Kaydın `evidence_id` değeri
istenen önbellek anahtarıyla eşleşmelidir. Eksik alanlı veya başka kimliğe bağlı
eski/bozuk kayıtlar yeniden kullanım sayılmaz; yürütücü kontrolü yeniden çalıştırır.
Bu denetim yerel veritabanına yazabilen bir taraf için dijital imza sağlamaz.

Digest ile sabitlenmiş Docker imajında her Python kapı kontrolü bir `evidence_id` üretir. Operatör, hem çözümün hem kontrolün deterministik olduğunu inceledikten sonra bu kimliği `[imece].approved_evidence` listesine ekleyebilir. İlk başarılı çalıştırma yerel önbelleğe kaydedilir. Aynı dosyalar, kontrol, imaj, mimari, süre sınırı ve yürütücüyle tekrar karşılaşıldığında başarılı sonuç kullanılabilir. Liste varsayılan olarak boştur. Dış referans değerlendirmesi ayrı çalışır. Raporun `gate_checks_reused` sayacı kapı raporlarında kaç kontrolün yeniden kullanıldığını gösterir.

Çalıştırılmış bir kontrolün hata sınıfı kapı raporunda ve hata arşivinde saklanır. Örneğin söz dizimi bozuk bir kontrol veya başlatılamayan sandbox, kod onarımı için aday seçimine kanıt oluşturmaz. Çalışma zamanı hatası tek başına adayın mı yoksa kontrolün mü yanlış olduğunu göstermez. Eski raporlarda sınıf eksikse inceleme özeti bunu `unknown` olarak sayar.

Uyarlamalı modda dondurulmuş bir Python kontrolünün boş veya söz dizimi açısından geçersiz olduğu kapıda görülürse koşu reddedilir ve rapora kontrol kimliği yazılır. Aynı sözleşmede yeni aday üretmek bu hatayı düzeltemez. Düzeltilmiş kontrol yeni bir doğrulama sözleşmesi gerektirir.
