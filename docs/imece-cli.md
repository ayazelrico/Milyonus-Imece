# Codex CLI ile İmece deneyini hazırlama

Sabit digest kullanan Docker deneylerinde hazırlık ve devam sırasında yerel
Docker çalışıyor ve seçilen imaj hazır olmalıdır. Manifestteki
`verification_environment_id`, seçilen imajı, Docker daemon kimliğini,
kernel ve güvenlik özelliklerini, yürütme komutunu ve süre sınırını kapsar.
İki kolun protokolleri bu alan dahil eşleşmelidir. Devam sırasında farklı
kimlikteki ortam reddedilir. Görevden önce, yürütülebilir kontrollerde ve
görev satırı kaydedilmeden önce kimlik tekrar denetlenir. Görev ortasında
uyuşmazlık tespit edilirse çağrı kayıtları korunur ve koşu kesilmiş olarak
kaydedilir. Bu kontroller sorgu ile Docker çağrısı arasında daemon üzerinde
atomik bir kilit sağlamaz.

Eski raporlar karşılaştırmada okunabilir. CLI üzerinden 5X kabulü için
doğrulanabilir ortam kimliği alanı gerekir. Eski checkpoint'ler donmuş
kaynak ve protokol koşullarına uygun kendi sürümleriyle devam ettirilir.

Uyarlanan üretimi tek başına ölçmek için çift hazırlarken hem
`--baseline-compact-cli-instructions` hem
`--candidate-compact-cli-instructions` seçilebilir. İki kolun aynı kısa CLI
talimatını kullanması talimat değişimini deneyden çıkarır; yalnızca
`adaptive_production` farkı kalabilir. Araç bunu manifestlerin gerçek
farklarından hesaplar; hazırlık model çağrısı yapmaz.

Model çağrısı yapmadan gerçek Docker kanıt önbelleğini ölçmek için
`uv run python -m evals.imece.cache_probe --out cache-probe.json` kullanılır.
Sabit digest'li imaj, açık deterministik örnekler, soğuk önbellek ve açık
operatör izinleriyle çalışır. Bu sentetik tekrar yükü tam görev matrisindeki
kazanım veya 5X kabulü değildir. [Ölçüm ve sınırları](experiments/cache-probe-2026-11-06.md).

Güncel kimlik seçilen imajı, Docker daemon'unu ve yürütme komutunu da kapsar;
metadata okunamazsa önbellek kullanılmaz. Eski onay hash'lerinin yeniden
incelenip üretilmesi gerekir. Kimlik sorgularının ek süreçleri dahil ölçüm:
[çalışma ortamı ve politika](experiments/cache-runtime-probe-2026-11-06.md).

Yerel hashing hafıza gömmesi `hashing-blake2b-v1-DIM` imzasını kullanır.
Eski `hashing-DIM` imzasıyla kaydedilmiş vektörler Python süreç tohumuna bağlı
olduğundan yeni sorgularla karşılaştırılmaz. Hashing hafıza kullanan mevcut
kurulumda `milyonus memory reindex` ile aktif kayıtları yeniden indeksleyin.
Bellek metinleri ve güven seviyeleri bu geçişle değiştirilmez.

Rapor özeti başarısızlar dahil tüm koşular için `status_counts`,
`gate_failure_classes` ve süre/token/maliyet dağılımlarını içerir. Dağılımda
bilinen ve bilinmeyen koşu sayısı, minimum, medyan, yüzde 95 ve maksimum
bulunur. Yüzdelikler sıralı değerler arasında doğrusal ara değerle hesaplanır.
Herhangi bir koşunun ilgili ölçümü eksikse nüfus yüzdelikleri boş kalır;
yalnızca bilinen koşulardan düşük maliyet veya gecikme sonucu çıkarılmaz.
Maliyet dağılımı tahmini değerler içerebilir; `cost_estimated` ayrıca
incelenmelidir ve P5 doğrulanmış fatura koşulunu kaldırmaz. Hata sınıfları
yalnızca Python kapı kontrollerindeki başarısız gözlemleri sayar; aynı
koşunun birden çok başarısız kontrolü ayrı gözlemdir.

Çift hazırlama aracı `--seat-model SEAT=MODEL` seçeneklerini iki tarafa aynı
uygular. `--declared-budget-usd`, `--failure-families`, `--agents` ve
`--max-tokens` da ortak olarak aktarılır. Böylece koltuk kökeni incelemesi,
makbuz karşılaştırması ve hata ailesi ölçümü için gereken ön bildirimler
eşleşmiş protokole girer. Dolar tavanı CLI harcamasını anlık sınırlamaz;
sonradan fatura denetimi içindir. Model adları bağımsızlık kanıtı değildir.

Bir CLI çağrısı hata, iptal veya geçersiz yanıt nedeniyle belirsiz kalırsa
görev/tekrar çifti aynı süreç içinde hemen engellenir. Sonraki gönderimler
uzlaştırma gerektirir; engel yalnızca yeniden başlatmada uygulanmaz. Daha önce
başlatılmış eşzamanlı çağrılar kendi kayıtlarında tamamlanır veya iptal edilir.
Geçersiz tamamlanma yanıtı kalıcı durum hatasıdır ve koşuyu keser. Belirsiz
kayıt ile bilinen kullanım sayıları korunur; sıfır maliyet varsayılmaz.

Gönderim kotası, belirsizlik ve token bütçesi kontrolleri yürütme sırası
beklendikten sonra yapılır. Önceki çağrı beklerken bütçeyi tüketmiş veya görevi
belirsiz hale getirmişse sıradaki çağrı başlatılmaz. Henüz yürütme sırası
gelmemiş işler gerçek CLI çağrısı olarak kaydedilmez.

Yeniden başlatmada geçmiş belirsiz çağrılar varsayılan olarak deneyin sonraki
görevini de durdurur. Operatör yalnızca diğer görevlere açıkça devam etmek
istiyorsa `--resume --continue-after-uncertain-trial` kullanabilir. Görev ve
tekrar kimliği bilinen belirsiz çağrı yine tekrar gönderilmez. Kimliksiz eski
belirsiz kayıtlar bütün yeni gönderimleri engeller. Bu seçenek bilinmeyen
harcamayı uzlaştırmaz ve kayıtları tamamlanmış saymaz.

Günlük bütünlüğü veya kalıcı kayıt yazma hatası `FatalAgentStateError` ile
çalışmayı keser. Ajan havuzu bu hatayı sıradan başarısız yanıt metnine
çevirmez; aynı havuzun paralel partilerindeki çalışanlar iptal edilip beklenir.
İptal kaydı yazılırken oluşan kalıcı durum hatası da korunur. Bu durumda
retrospektif model çağrısı veya tamamlanmış görev satırı üretilmez. CLI koşucusu
eldeki çağrı kayıtlarıyla `interrupted` kontrol noktası yazmayı dener;
depolama sorunu sürerse bu yazım da başarısız olabilir. Olağan sağlayıcı
hataları ve sonucu bilinmeyen çağrıların otomatik tekrarlanmaması ayrı kalır.

`inspect_run`, okuyamadığı veya kimliği eksik günlükleri `journal_errors`
alanında gösterir; `journal_scan_complete=false` taramanın eksik olduğunu
belirtir. Bu tarama tam günlük bütünlüğü denetimi değildir.
Günlük taraması eksikse komut çıkış kodu `2` döndürür; boş bir hata listesi
gibi yorumlanarak otomasyonun başarıyla devam etmesi önlenir.

Devam işlemi ana transkriptleri hem yan kayıtlar birleştirilmeden önce hem sonra
doğrular. Modern kayıtlarda benzersiz çağrı ve günlük düğümü kimliği, kesintisiz
tamsayı sıra numarası, görev/tekrar üyeliği, donmuş koltuk-model eşlemesi ve
istek/yanıt özetleri zorunludur. Belirsiz durumdaki kayıt tamamlanmış yanıt
taşıyamaz. Bozuk yan kayıtlar günlük uzlaştırmasından önce reddedilir.
Eski biçimlerden yalnızca tam olarak `spec+reply` veya `spec+error` içeren
kayıtlar, modern kayıtlardan önce gelen bir önek olarak korunur. Bunlara kimlik
uydurulmaz; tamamlanmamış günlük düğümlerini kurtarmak için kullanılamazlar.
Kimlikli fakat günlük bağlantısı eksik ara biçimler devam için reddedilir.
Kod kimliği değiştiğinde mevcut manifest kısıtlaması ayrıca geçerlidir.

Kesinti sonrası token hesabı mantıksal dalın toplamı yerine kalıcı gerçek çağrı
kayıtlarından yeniden kurulur. Terk edilen dalın bilinen kullanımı da görev
bütçesinde kalır; günlükten tekrar kullanılan yanıt ikinci kez sayılmaz.
`logical_path_tokens` yeniden yürütülen dalı, `observed_tokens` bilinen gerçek
kullanımı gösterir. Belirsiz çağrı varsa `tokens` boş kalır. Eski kimliksiz
kayıtlar görevlere dağıtılamadığından `usage_attribution_complete=false` olur
ve yeni gönderim uzlaştırma gerektirir. Koşu düzeyindeki
`accounting.observed_tokens` bu kayıtların bilinen kullanımını da korur.
Özetin `observed_tokens` alanı tüm gerçek kayıtların bilinen alt sınırıdır;
`unassigned_observed_tokens` ve `unassigned_unknown_usage_calls` henüz görev
satırına atanamayan kullanımı ayrıca gösterir. Bu kullanım varken toplam
token ve doğrulanmış sonuç başına token değeri boş kalır.
Bu sınır tamamlanan çağrıları izler; eşzamanlı veya halen çalışan çağrıların
çıktısını önceden kesin olarak sınırlamaz.

Önceki süreç görev satırını yazmadan kesilmişse toplam süre bilinmez.
Bu durumda devam denemesinin süresi yalnızca `attempt_seconds` olarak
kaydedilir; `seconds` yazılmaz ve toplam gecikme dağılımı eksik görünür.

Yeni ajan günlüğünde şema, sürüm, koşu kimliği ve ilk aşama girdisi tek SQLite
işleminde oluşturulur. İşlem tamamlanmadan bir kesinti olursa SQLite dosyası
diskte boş kalabilir. `--resume` ön denetimi koşu kimliğini okuyamadığında
durur. Günlük yalnızca dosyayı ilk oluşturan açılışta kimlik bağlar. Boş bir
dosya veya kimliği eksik bir günlük inceleme için olduğu gibi bırakılır.

Bir yanıt günlükten yeniden kullanılmadan önce düğümün aşaması, girdi özeti ve
ebeveyn JSON'u hesaplanan düğüm kimliğinin girdileriyle karşılaştırılır. Yanıt
ve çıktı özeti de doğrulanır. Sürüm 0, düğüm kimliğini doğrudan ebeveyn
listesinden hesaplamaya devam eder. Sürüm 2'de aşamaya girerken paylaşılan
ebeveyn kaydının JSON içeriğinden özet yeniden hesaplanır ve kayıt anahtarıyla
karşılaştırılır. Mevcut bir düğümün başvurduğu paylaşılan kayıt eksikse aşama
reddedilir.

Bu kontroller yalnızca yürütme sırasında ulaşılan düğümleri ve aşama girdilerini
kapsar. Bir düğümün silindiğini veya anahtarının değiştirildiğini bu kontrollerle
saptamak mümkün değildir. Özetler tutarlılık kontrolü sağlar ve kayıtların
kim tarafından yazıldığını doğrulamaz.

## PLAN-5X için çevrimdışı eşli hazırlık

Proje kökünden, henüz var olmayan bir çıktı dizini seçerek:

```sh
uv run python -m evals.imece.prepare_pair --engine codex --model gpt-6.1-sol \
  --baseline-config docs/imece-codex-baseline.toml \
  --candidate-config docs/imece-codex-adaptive.toml \
  --suite core-v2 --repeats 5 --seed 0 --backend macos \
  --max-cli-calls 2000 --out-dir experiments/codex-adaptive-pair
```

Bu komut yalnızca hazırlık yapar: model çağrısı, ajan çalıştırma, görev yürütme veya benchmark başlatmaz. `--resume` ya da canlı koşu seçeneği sunmaz; yalnızca `codex` motorunu kabul eder. `--model`, `--out-dir` ve iki yapılandırma dosyası zorunludur; eksik dosyalar varsayılanlara düşmez. Ortak varsayılanlar `core-v2`, beş tekrar, seed `0` ve `docker` backend'idir. `--backend`, `--image`, `--seed`, `--suite`, `--repeats`, isteğe bağlı `--max-cli-calls` ve yerel CLI seçimi için `--executable` iki rapora aynı uygulanır. Çağrı sınırı her rapor için ayrıdır, çiftin toplam sınırı değildir; verilmezse sınırsız olarak kaydedilir. Yukarıdaki 2000 yalnızca örnek bir çağrı sınırıdır, bütçe veya tamamlanma garantisi değildir.

Araç doğrudan mevcut `evals.imece.run.make_parser/main` yolunu zorunlu `--prepare` ile kullanır. Mevcut çalıştırıcı yerel Codex `--version`, `exec --help` ve `--help` komutlarını doğrular, dosya özetlerini okur ve macOS `sandbox-exec` korumasını denetler. Bu nedenle hazırlık da desteklenen yerel Codex kurulumu ve macOS gerektirir; `--backend docker` bu gereksinimi kaldırmaz. Docker veya oracle çalıştırılmaz; imaj indirilmez ve imajın erişilebilirliği doğrulanmaz. Yeni araç sağlayıcı API istemcisi oluşturmaz veya çağırmaz. Ancak mevcut runner'ın dolaylı import zinciri `milyonus.providers` üzerinden Anthropic ve OpenAI uyumlu sağlayıcı uygulama modüllerini de yükler. Bu modüllerin hiç import edilmemesi bu dört dosyalık değişiklikle sağlanmaz; mevcut paket/runner bağımlılıklarının ayrıca ayrıştırılması gerekir. Hazırlık dalı herhangi bir ajan oluşturulmadan önce döner.

Örnek TOML dosyalarında yalnızca `[imece]` değerleri vardır; sağlayıcı, fiyat veya model kökeni tanımlanmaz. İki dosyada yalnızca `adaptive_production` farklıdır: baseline `false`, aday `true`. `max_rounds=4`, art arda retlerden sonra durgunluk duruşunun sonraki turları önleyebilmesine alan bırakır. Bu seçenek uyarlamalı üretimin diğer davranışlarını da etkinleştirir; gelecekteki fark yalnızca durgunluk sezgiselinin etkisi diye yorumlanamaz. Hazırlık bu davranışları ölçmez. Mevcut runner semantiği gereği ajan sayısı `17`, token bütçesi `250000`, doğrulama `python` olarak alınır; TOML'deki `agents`, `max_tokens`, `verification` veya koltuk modelleri bu CLI eşlemesini değiştirmez. Burada bütün koltuklar açık `--model` değerine eşlenir; eşli araç koltuk bazlı model seçeneği sunmaz.

İki rapor çıktı dizininin yanında oluşturulan geçici dizinde hazırlanır. Her raporun protokol özeti yeniden hesaplanır; hem özetler hem gerçek protokol nesneleri eşleşmelidir. Her ikisinde durum `prepared`, `runs=[]`, `transcripts=[]` ve ayrılan CLI çağrısı sayısı sıfır olmalıdır. Aynı etkin ayarlar reddedilir; baseline `adaptive_production=false`, aday `true` olmalıdır. Diğer etkin ayar farkları ekrana ve manifeste yazılır; protokolü değiştiren farklar reddedilir. İki raporun revision ve implementation hash değerleri de eşleşmelidir. Doğrulama bitince dizin tek, üzerine yazmayan atomik yeniden adlandırmayla yayımlanır. Mevcut boş dizin veya sembolik bağlantı dahil hiçbir çıktı değiştirilmez; hata halinde çift yayımlanmaz.

Çıktıda `baseline.json`, `candidate.json`, `pair.json` ve runner'ın boş `.lock` dosyaları bulunur. `pair.json`, göreli rapor yollarını, her raporun `report_hash`, `protocol_hash`, `revision`, `implementation_hash` değerlerini ve etkin ayar farklarını kaydeder. `report_hash`, ham dosya baytlarının değil, tam JSON raporunun `evals.imece.protocol.digest` özetidir. Git revision tek başına yerel değişiklikleri tanımlamaz; implementation hash mevcut `src/milyonus` ve `evals/imece` Python içeriklerini kapsar. Kaynak dosyalar hazırlık boyunca değiştirilmemelidir.

Hazırlık kaydı 50 × 5 planlanan koşu içerir, tamamlanmış sonuç içermez. `model_calls=0` ve `result=null` yalnızca hazırlığın durumudur; dolar maliyeti bilinmiyor kalır. Fiyat, fatura veya bağımsız model kökeni kanıtı gerekmez ve üretilmez. Bu çift P5 kabulü veya 5X kazanç kanıtı değildir. `macos` ile hazırlanan protokol yerel geliştirme içindir; nihai karşılaştırmanın sabit Docker imajı gereksinimi için iki taraf da gerçek bir `--image IMAGE@sha256:DIGEST` ile baştan hazırlanmalıdır. Çift manifesti hazırlanan raporlara bağlıdır; raporlar sonradan değişirse hash bağları artık geçerli değildir. Bu komut canlı yürütme veya sonraki denetim kaydının yerine geçmez.

## Tek rapor hazırlama ve mevcut koşu semantiği

Proje kökünden aşağıdaki komut deney kaydını oluşturur. Görevleri çalıştırmaz. Kurulu Codex uygulamasının sürümü ve dosya özeti, model adı, görev sözleşmeleri, beklenen sonuçların özetleri, doğrulama ortamı ve tekrar sayısı kayda girer.

```sh
uv run python -m evals.imece.run --engine codex --model gpt-6.1-sol \
  --config docs/imece-trial.toml --backend macos --suite core-v1 \
  --repeats 5 --prepare --out experiments/codex-core.json
```

`--prepare` yerine `--resume` ile aynı komutu çalıştırmak gerçek model çağrılarını başlatır. Yerel çalışma kopyası, CLI, ayarlar veya görev kimlikleri değişirse yeni bir deney kaydı gerekir. Koşu kayıtlarında görev ve tekrar çiftleri benzersiz olmalıdır. Kesintiden önce tamamlanmış ajan çağrıları aynı deney günlüğünden okunur. Belirsiz kalan çağrılar otomatik tekrarlanmaz.

`--model` zorunlu varsayılan CLI modelidir. İsteğe bağlı `--seat-model SEAT=MODEL` farklı koltuklar için tekrarlanabilir; belirtilmeyen her koltuk doğrudan `--model` değerini kullanır. Örneğin aşağıdaki komutta yalnızca onay ve risk perspektifi değiştirilir:

```sh
uv run python -m evals.imece.run --engine codex --model gpt-6.1-sol \
  --seat-model approval=APPROVAL_MODEL \
  --seat-model council_risk=RISK_MODEL \
  --config docs/imece-trial.toml --backend macos --suite core-v1 \
  --repeats 5 --prepare --out experiments/codex-routed.json
```

`APPROVAL_MODEL` ve `RISK_MODEL` yerine seçilen CLI'ın desteklediği model kimliklerini yazın. Aynı seçenekler `--engine antigravity` için de geçerlidir; tüm koltuklar seçilen tek CLI motorunu ve mevcut adaptörünü kullanır. Bu çalıştırıcı model seçimini bu CLI seçeneklerinden alır; yapılandırmadaki `[imece.seats]` sağlayıcı yönlendirmesini kullanmaz. Ek seçenek verilmezse bütün koltuklar eskisi gibi `--model` ile çalışır. `--seat-model pool=...` yalnızca havuzu değiştirir; diğer belirtilmemiş koltukların varsayılanını değiştirmez.

Geçerli koltuklar: `pool`, `framing`, `test_design`, `red_team`, `evidence_audit`, `compliance`, `observer`, `approval`, `council_correctness`, `council_risk`, `council_user_impact`, `council_cost_speed`, `council_devils_advocate`. Konsey için çalışma zamanındaki `council:correctness`, `council:risk`, `council:user_impact`, `council:cost_speed`, `council:devils_advocate` biçimleri de kabul edilir. Boş değerler, hatalı atamalar, bilinmeyen koltuklar ve aynı koltuğun tekrar atanması model çağrılarından önce reddedilir; alt çizgili ve iki noktalı biçimler aynı koltuk sayılır. Yönlendirme ajan rolüne veya blok adına göre değil, gerçek `spec.seat` değerine göre yapılır.

Manifestin `protocol.models` alanı varsayılanlar çözüldükten sonraki tam eşlemeyi dondurur: havuz, beş ayrı `council:<perspective>` koltuğu, onay ve diğer koltuklar ayrı kaydedilir. Raporun `models` alanı aynı eşlemeyi, yeni çağrıların transkriptleri seçilen modeli içerir. `--resume` için aynı çözülmüş eşleme gerekir; seçeneklerin sırası veya eşdeğer koltuk yazımı önemli değildir. Eşlemenin değişmesi mevcut manifest karşılaştırmasında reddedilir; tamamlanmış satırları atlama, günlükten devam etme ve belirsiz çağrıları yeniden çalıştırmama kuralları korunur. Önceki kod sürümünde hazırlanmış kayıtlar mevcut kod kimliği denetimine tabidir; bu değişiklik onları dönüştürmez.

`--resume`, `budget` sonucu dahil kaydedilmiş tüm görev/tekrar çiftlerini atlar ve yalnızca kaydı olmayan çiftlerden devam eder. Önceki son satırın `budget` olması devam etmeyi engellemez; yalnızca bu komut çalışırken kaydedilen yeni bir `budget` satırı sonraki görev/tekrarların başlatılmasını durdurur. Tekrar devam etmek için aynı komut açıkça `--resume` ile çalıştırılmalıdır. Önceki sonuçlar ve toplamlar korunur; yeni sonuçlar bunlara eklenir. Bilinmeyen kullanım ve ücretler sıfırlanmaz veya sıfır sayılmaz. Henüz sonuç satırı olmayan bir koşuda tamamlanmış günlük çağrıları yeniden kullanılır; sonuçlanmamış veya belirsiz günlük çağrıları ücretleri uzlaştırılmadan otomatik yeniden çağrılmaz.

Codex çalıştırıcısı bu sürümde macOS Seatbelt kullanır. Aday sürecinin proje ve deney kayıtlarını okuması engellenir. CLI tarafından raporlanan tokenlar kaydedilir. Ücret ve tamamlanmamış çağrıların kullanımı bilinmiyorsa rapor ilgili toplamı boş bırakır. Manifest ve rapor, aynı CLI model kimliğini paylaşan koltukları açıkça listeler. Farklı model adları (alias) farklı temel modellerin veya sağlayıcıların kanıtı değildir; konsey ve onayın bağımsızlığı yalnızca bu adlardan çıkarılamaz. Bu nedenle tüm adlar farklı olsa bile bağımsızlık uyarısı korunur. Yerel macOS koşusu geliştirme içindir. Plandaki nihai kıyaslama sabit Docker imajı, iki eksiksiz deney serisi, karşılaştırılabilir maliyet ve bağımsız denetim gerektirir.

## P5 için bağımsız model kökeni denetimi

`uv run python -m evals.imece.compare BASELINE ADAY --audit DOSYA --out SONUC` ile verilen JSON denetim kaydı aşağıdaki şemayı kullanır. Hash değerleri `evals.imece.protocol.digest` ile, manifest, koşular, ücretler ve uyarılar dahil **iki tam rapordan** ayrı ayrı hesaplanır; dosyanın ham baytlarının veya yalnızca manifestin hash'i değildir. Raporun herhangi bir alanı değişirse denetim yeniden bağlanmalıdır.

```json
{
  "baseline_hash": "BASELINE_TAM_RAPOR_SHA256",
  "candidate_hash": "ADAY_TAM_RAPOR_SHA256",
  "critical_findings": 0,
  "reviewer": "Bağımsız denetçinin kimliği",
  "reference": "İmzalı genel denetim kaydının konumu veya kimliği",
  "model_independence": {
    "reference": "İki raporun model kökenini inceleyen kanıt kaydının konumu veya kimliği",
    "seats": {
      "pool": {"alias": "POOL_ALIAS", "vendor": "Üretici A", "model": "Temel model A"},
      "approval": {"alias": "APPROVAL_ALIAS", "vendor": "Üretici B", "model": "Temel model B"},
      "council:correctness": {"alias": "CORRECTNESS_ALIAS", "vendor": "Üretici C", "model": "Temel model C"},
      "council:risk": {"alias": "RISK_ALIAS", "vendor": "Üretici D", "model": "Temel model D"},
      "council:user_impact": {"alias": "USER_IMPACT_ALIAS", "vendor": "Üretici E", "model": "Temel model E"},
      "council:cost_speed": {"alias": "COST_SPEED_ALIAS", "vendor": "Üretici F", "model": "Temel model F"},
      "council:devils_advocate": {"alias": "DEVILS_ADVOCATE_ALIAS", "vendor": "Üretici G", "model": "Temel model G"}
    }
  }
}
```

Örnekteki değerler yer tutucudur. `critical_findings` tam olarak tamsayı `0` olmalıdır; `false`, `0.0` ve `"0"` kabul edilmez. `reviewer`, iki `reference` alanı ve her `vendor`/`model` boş olmayan metinler olmalıdır; yalnızca boşluk yeterli değildir. Denetçi, her kritik koltuğun `alias` değerini dondurulmuş `manifest.protocol.models` eşlemesindeki değerle birebir eşleştirir. Ortak protokol nedeniyle bu eşleme iki rapor için de geçerlidir. Yedi koltuğun tamamı zorunludur; yalnızca bağımsız olduğunu söyleyen bir bayrak veya farklı alias listesi yeterli değildir.

Denetçi `vendor` alanına CLI hizmetini veya aracı satıcıyı değil gerçek temel modelin üreticisini, `model` alanına alias'ları aynı kimliğe indirgeyen temel model kimliğini yazar. Kanıt referansı bu çözümlemeyi ve iki koşudaki kullanımı bağımsız incelemeye açmalıdır. Kritik koltuklarda tekrarlanan alias veya aynı `(vendor, model)` köken çifti reddedilir. Beş konsey üyesi ile onay koltuğunun üreticileri birbirinden farklı olmalıdır; havuz bu altı koltuktan biriyle üretici paylaşabilir, fakat aynı temel modeli paylaşamaz. Alias ve köken tekrarları baştaki/sondaki boşluklar ve harf büyüklüğü farkları giderilerek denetlenir. `framing`, `test_design` ve diğer kritik olmayan rollerin havuzla veya kendi aralarında model paylaşması tek başına engel değildir; bu kontrol onların bağımsızlığına ilişkin bir onay vermez.

CLI raporlarında bu ek köken kanıtı, uyarı listesi boş olsa bile zorunludur. Eksik/geçersiz denetim veya doğrulanamayan uyarı P5 kabulünü engeller. Geçerli kanıt yalnızca çalıştırıcının dondurulmuş tam model eşlemesinden ürettiği standart alias/paylaşım uyarısını karşılaştırmada giderilmiş sayabilir. Başka bir uyarı, değiştirilmiş uyarı metni veya hatalı uyarı biçimi engel olarak kalır. Kaynak raporlar ve uyarılar değiştirilmez. CLI dışındaki eski raporlar ek `model_independence` şemasına tabi değildir; genel denetimdeki tamsayı ve boş olmayan metin koşulları onlar için de geçerlidir.

Bu kapı dış kanıtın yapısını ve tutarlılığını denetler; referansı açmaz, imzayı doğrulamaz, üreticiye sorgu yapmaz ve denetçinin gerçekten bağımsız olduğunu kanıtlamaz. Uydurulmuş üretici/model adlarını veya gizli ortak model soyunu otomatik saptayamaz. Kanıtın doğruluğu ve gerçek üretici kimliklerinin tutarlı yazılması insan incelemesinin sorumluluğundadır. Köken denetiminin geçmesi; maliyet, sabit Docker imajı, eksiksiz görev matrisi veya diğer P5 koşullarını kaldırmaz.

[Bu çalışma kopyasında hazırlanan 50 × 5 deney kaydı](experiments/codex-core-v1-prepared.json) ve [onarım akışı](imece-repairs.md).

Bir kaydın durumunu model çağrısı yapmadan incelemek için:

```sh
uv run python -m evals.imece.inspect_run experiments/codex-core.json
```

Çıktı, kaydedilen ve kalan görev sayılarını, sıradaki görev/tekrar çiftini ve günlüğe girip tamamlanmamış çağrıların kimliklerini gösterir. Tutarlı bir kesinti raporu için komutu deney durduğunda çalıştırın.

Deney başına CLI çağrı sayısını sınırlamak, maliyet tavanını kayda geçirmek ve harici dökümleri raporla eşleştirmek için [ücret eşleştirme kılavuzuna](imece-billing.md) bakın.

Çalışma sırasında her çağrının başlangıcı ve sonucu, raporun yanındaki `.calls/` dizinine kendi kimliğiyle yazılır. Ana rapor görev sınırında atomik olarak kaydedildikten sonra içerdiği geçici çağrı kayıtları kaldırılır. Kesinti sonrasında çalışmaya devam ederken raporu, `.journal/` ve varsa `.calls/` dizinini birlikte koruyun. Devam komutu deney kimliğini ve çağrı sırasını kontrol eder. Yanıtı bilinmeyen bir çağrının maliyeti ilgili görev için belirsiz kalır.

Yeni CLI çağrı kayıtları, eşzamanlı çalışmada da gerçek günlük düğümüne bağlanır: donmuş koşu/görev/tekrar kimliğinin özeti, düğüm kimliği ve ajan isteğinin özeti birlikte saklanır. Tamamlanan yanıtın alanları ve çıktı özeti doğrulanır ve yanıt diske kalıcı olarak yazılır. İşlem bu yazımdan sonra fakat günlük düğümü tamamlanmadan kesilirse, `--resume` herhangi bir çağrı başlatmadan önce kayıtları uzlaştırır. Yalnızca aynı görev ve tekrardan gelen, tüm kimlikleri ve özetleri tam eşleşen kalıcı bir `completed` yanıt, `running` veya `unknown` düğümünü `completed` durumuna geçirebilir. Sonraki yürütme bu doğrulanmış yanıtı günlükten yeniden kullanır; yeni CLI çağrısı ve yeni çağrı kotası tüketimi oluşmaz. Ana rapora aktarılmış kalıcı transkript de aynı denetimlere tabidir.

Çelişen yanıtlar, bozuk özetler, eksik düğümler ve aynı düğüme bağlı birden fazla çağrı devam işlemini reddettirir. Gerçekten belirsiz bir çağrı otomatik tekrarlanmaz; ilgili görev/tekrarda yeni gönderimler uzlaştırma bekler. Eski günlüklerin sürümü ve düğüm kimliği hesabı değişmez; tamamlanmış yanıtları yeniden kullanılabilir. Ancak eski, düğüm bağı veya çıktı özeti olmayan transkriptlerden tamamlanmamış düğüm için başarı çıkarılmaz. Manifestin mevcut kod kimliği denetimi geçerliliğini korur; bu düzeltme eski deneyleri yeni kodla devam ettirmek için dönüştürmez.

Çalışma sırasında günlükte kimlik, aşama girdisi veya saklanmış yanıt bozulması ya da SQLite hatası saptanırsa deney hata ile kesilir. Kuyruktaki çağrılar başlatılmaz ve etkin işler iptal edilir. İlgili görev/tekrar için bütçe sonucu veya başka bir sonuç satırı yazılmaz ve retrospektif başlatılmaz. Rapor `interrupted` durumunda kaydedilir ve o ana kadarki çağrı kayıtları korunur. Sağlayıcı hataları olağan ajan hatası olarak işlenir ve bu çağrıların kullanımı belirsiz kalır.

Hermes ve İmece için önceden üretilmiş iki tam raporun görev sonuçlarını karşılaştırmak için `uv run python -m evals.hermes.compare imece.json hermes.json --out paired.json` kullanılır. Araç model çağrısı yapmaz. Veri kümesi, referans değerlendirme kodu, puanlama ortamı, zaman sınırı, üretici model adı ve görev/tekrar eşleşmesi doğrulanır. Çıktı her iki sistemin de başardığı, yalnızca birinin başardığı ve ikisinin de başaramadığı görev sayılarını verir. Motorların üretim bütçeleri ve onay kuralları farklı olabilir; P5 maliyet değerlendirmesi ayrı yürütülür.

Karşılaştırma raporundaki `phase_efficiency`, iki ayrı ölçü verir. Token ölçüsünde her sürümün başarısızlar dahil toplam tokenı, dış referansı geçen kabul sayısına bölünür. Kullanım eksikse veya payda sıfırsa oran bilinmiyor kalır. Kapı ölçüsünde aynı görev ve tekrardaki kanıt kimliklerinin sayıları da eşleşmelidir. `matched_process_reduction` yalnızca eşleşen çiftlerde gerçekten başlatılan sandbox süreci sayısındaki azalmadır. Bütün çiftler ölçülebilir ve eşleşmiş değilse tam veri kümesi için yüzde 60 koşulu boş bırakılır. Bu ölçüler dolar başına 5X kazanç hesabından ayrıdır.

Onarıma atanan üretici varsayılan olarak üretim havuzunun modelini kullanır. `--seat-model repair=MODEL` yalnızca önceki aday ve bağımsız hata kaydıyla açılan onarım işini farklı bir modele yönlendirir. Olağan üreticiler `pool` koltuğunda kalır. Onarım için farklı model seçilirse denetim kaydına `repair` koltuğunun model kökeni de eklenir.

Onarım karşılaştırması için `--failure-families evals/imece/data/repair-families-v1.json` seçeneğini iki sürümün hazırlığında kullanabilirsiniz. Örnek dosya altı görevi üç hata ailesine atar. Bu atama bir hipotezdir ve çalışma başlamadan protokol kimliğine girer. `repair_families` raporu, beceri kullanılmamış denemeleri de dahil ederek her ailedeki başarısız tur sayısını ve dış referansı geçen kabul oranındaki değişimi gösterir. Yarıda kesilmiş turlar veya eski raporlarda eksik tur geçmişi varsa azalma oranı boş kalır. Birden çok değişiklik içeren sürümler karşılaştırıldığında fark tek başına becerinin etkisini kanıtlamaz.

Onarım becerisi seçilen deneyde hazırlık sırasında canlı becerinin içerik özeti sabitlenir. Erişilemeyen bir beceriyle deney hazırlanamaz. Çalışırken sürüm değişmiş veya iptal edilmişse o tur normal onarıma döner. `candidate_trials_with_skill_briefing` aday sürümde beceri örneği verilen onarım görevlerinin bulunduğu koşuları sayar. Eşleşen bu alt kümenin iki sürümdeki doğrulanmış kabul sayıları ayrıca gösterilir.

Yerel tanı amacıyla `--capture-reproductions` verildiğinde koşu başına en çok üç farklı çalışma zamanı hatasının dosyaları ve tek başarısız kontrolü rapora eklenir. Paket başına 32 KiB sınırı vardır. Gizli bilgi maskelemesine takılan içerik atlanır. Bu seçenek üretilen kaynak kodu rapora dahil ettiğinden varsayılan olarak kapalıdır. Paketlerin yeniden çalıştırıldığına dair kanıt yoktur; arşivden çıkarılanlar doğrulanmamış örneklerdir.

`--suite core-v2`, v1’deki 50 görevi ve dış referans vakalarını kullanır. On hata düzeltme görevinin kamuya açık sözleşmesine hatalı başlangıç programı eklenir. Böylece ajan somut bir uygulamayı onarır. Sözleşme değiştiği için v1 ve v2 raporları eşleştirilemez. Hermes hazırlığı da aynı küme adını kabul eder.

Uyarlamalı Python sentezinde konsey, dondurulmuş sözleşmeyle birlikte önceki bağımsız kontrolleri, aday dosyalarının referans adaya göre değişen adlarını ve ilk değişikliğin sınırlı bir kesitini görür. Aday ile kanıt paketinin ayrı içerik özetleri eski emsalin değişmiş bir çözümde kullanılmasını önler. Kesitler adayların davranışça eşdeğer olduğunu kanıtlamaz.

İsteğe bağlı `adaptive_production` ile `verification="python"` birlikte kullanıldığında, art arda iki üretim Kapı 2 reddinde aynı aday Python dosya içerik kümeleri, aynı dondurulmuş çalıştırılabilir kontrol sözleşmeleri ve aynı gözlenen yürütme sonuçları görülürse yeni planlama/üretim turuna geçilmeden durulur. Kimlik; dosya adları ve tam içerikleri, kontrolün `id`, `check`, `how`, `python` alanları ve her adaya bağlı kontrol sonuçlarından hesaplanır. Aday kimliği, yazarı, yaklaşım/tur etiketi ve Python dışı açıklamalar karşılaştırılmaz; aynı dosya ve sonuç paketinin kopyaları tek sayılır. Yeni dosya içeriği, kontrol veya sonuç karşılaştırmayı değiştirir. Kanıt kimliği karşılaştırmaya girer; önbellekten yeniden kullanım bayrağı girmez.

Her aday için tüm kontrollerin eksiksiz, benzersiz Python yürütme kaydı ve en az bir `returncode=1`, `failure_class="candidate_or_oracle_runtime"` başarısızlığı gerekir. Başarılı kontrollerde dönüş kodu sıfır olmalıdır. Eksik kanıt, yalnızca model yargısı, sandbox/altyapı sorunu, zaman aşımı, boş veya sözdizimi bozuk oracle bu durgunluk duruşunu tetiklemez; karşılaştırma sıfırlanır. Aday çıkmayan veya üretim kapısını geçen tur da ardışıklığı keser. Bozuk dondurulmuş oracle için mevcut ayrı duruş kuralı korunur.

Duruşta sonuç `rejected`, son gerçek turun sonucu `production_gate_rejected` kalır. `notes` açık duruş nedenini ve `stagnation SHA-256` parmak izini içerir; çalıştırılmamış tur veya kabul başarısı kaydedilmez. Varsayılan uyarlamasız davranış, bağımsız onay, insan incelemesi ve veto kapıları değişmez.

Bu, davranış eşdeğerliği veya gelecekte ilerleme olmayacağının kanıtı değil, tutucu bir sezgiseldir. Çalışma zamanı hatası aday ile oracle kusurunu ayıramaz; sözdizimi geçerli bir oracle anlamsal olarak yanlış olabilir. Raporlanan çıktı kapıda 2000 karakterle sınırlıdır. Yürütücüde veya kapıda kesilen çıktı `output_truncated=true` taşır ve durgunluk kararına katılmaz; bu alanın eksik olduğu eski kayıtlar da tam çıktı kanıtı sayılmaz. Geçici yollar veya deterministik olmayan çıktılar eşleşmeyi engelleyebilir; farklı kaynak kodların aynı davranışı göstermesi eşleşme sayılmaz. Duruş olası sonraki iyileşmeyi kaçırabilir. Bu değişiklik için ölçülmüş performans veya maliyet kazancı iddiası yoktur.

## Deneysel kısa Codex talimat profili

`evals.imece.run --compact-cli-instructions`, yalnızca Codex motorunda yerleşik
ajan talimatlarını sürümlü, araç kullanmayan uzman talimatıyla değiştirir.
Codex'in `model_instructions_file` ayarı kullanılır; dosya her çağrının geçici
dizininde oluşturulur ve çağrı kapanınca kaldırılır. Oracle için OS erişim
engeli, kapalı araç özellikleri, kullanım doğrulaması ve araç öğelerini
reddeden JSONL ayrıştırıcısı aynı kalır. Model davranışı değişebileceğinden
özellik varsayılan olarak kapalıdır; kapı veya insan onayı atlanmaz.

Manifestte `cli_prompt_treatment.kind` ve `instructions_hash` saklanır.
`--resume` bu alanları da karşılaştırır. Çift hazırlama aracındaki
`--candidate-compact-cli-instructions`, yalnızca adaya bu profili verir.
İki çekirdek ayarı aynı olduğunda bile açık bir talimat profili farkı varsa
çift hazırlanabilir. `--task ID` iki tarafa aynı görev alt kümesini uygular.
Karşılaştırılan güvenlik/çalıştırma kontrolleri yine eşleşmelidir; talimat
profili açıkça ilan edilmiş algoritma değişkenidir.
Hazırlık ve karşılaştırma çıktısındaki `treatments`, değişen etkenleri ve
`isolated_compact_prompt` değerini verir. Uyarlamalı üretim veya uygulama
kodu da değişmişse sonuç yalnızca kısa profile yüklenemez.

```sh
uv run python -m evals.imece.prepare_pair --model gpt-6.1-sol \
  --baseline-config docs/imece-codex-baseline.toml \
  --candidate-config docs/imece-codex-baseline.toml \
  --candidate-compact-cli-instructions --suite core-v2 --task stable_unique \
  --repeats 1 --max-tokens 500000 --max-cli-calls 80 \
  --backend docker --image python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e \
  --out-dir experiments/compact-calibration-example
```

5 Kasım'da aynı `READY` tanısı için normal profil 9349/9347, kısa profil
5316/5314 token bildirdi. Bu yalnızca ikişer çağrılık tanıdır; görev başarısı,
genel hızlanma, dolar tasarrufu veya 5X kanıtı değildir. Tam görev başarısı
ayrı, önceden dondurulmuş koşularla değerlendirilmelidir. Çağrı bazında USD
maliyeti bilinmiyor kalır.

Yapılandırma kaynağı: [resmi Codex referansı](https://learn.chatgpt.com/docs/config-file/config-reference),
`model_instructions_file` alanı. Bu seçenek kullanıcı/global Codex ayarını değiştirmez.

## Deney sırası ve bütçe kapsamı

Yeni CLI hazırlıkları `--trial-order repeat-major` kullanır: önce her seçili
görevin ilk tekrarı, sonra ikinci tekrarları çalışır. `task-major` önce aynı
görevin tüm tekrarlarını bitirir. Sıra protokol kimliğine girer; iki kolun
sırası farklıysa karşılaştırma reddedilir. İnceleme aracı aynı sıra üzerinden
sonraki kaydı hesaplar. Sıra alanı bulunmayan eski kayıtlar incelemede
`task-major` kabul edilir; yeni koşucu eski deneyi sessizce yeniden sıralamaz.
Kod/protokol değişimi mevcut devam kimliği denetimine tabidir.

Koşu başına `max_tokens` sınırında kalan bilinen bir `budget` sonucu kaydedilir
ve deney sonraki göreve geçebilir. Deneyin toplam `max_cli_calls` sınırına
ulaşılması veya bir koşunun kullanımının belirsiz kalması deney akışını
sonuç satırı sınırında durdurur. Son izinli çağrı, yalnızca rezerve edildiği
için çalışan işlem sırasında iptal edilmez. Belirsiz kullanım `rejected`
sonucuyla birlikte gelse bile otomatik devamı durdurur.
