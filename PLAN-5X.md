# İmece 5X — doğrulanmış sonuç başına beşte bir maliyet

Durum: **P0–P4 altyapısı kodda; P5 kabul kapısı henüz ölçülmüş değil.** 50 görev
× protokol, rezervasyon defteri, kanıt önbelleği, uyarlanan üretim, onarım/
beceri akışları ve Hermes like-for-like adaptörü (`evals/hermes`) mevcut.
Karşılaştırmalı 250 koşu + bağımsız denetim + fatura mutabakatı dış çalışma
gerektirir — `accepted_5x` yalnızca `evals.imece.compare` ile ilan edilir.
Kapsam İmece ve ajan çekirdeğidir. Web ürünü `PLAN-WEB.md` altındadır.

Madde bazında uygulama ve açık kabul koşulları:
[kabul kaydı](docs/plan-5x-acceptance.md).

6 Kasım son yerel doğrulamasında **588 test geçti**, atlanan test yok.
Gerçek Docker izolasyonu, dosya azaltma, kurtarma ve önbellek regresyonları dahil;
Kullanıcının sonraki izniyle canlı kıyaslama denendi: iki tarafta dörder
satır kaydedildi, belirsiz çağrılarda duruldu. Gerçek çağrı bazlı USD dökümü
mevcut değil. Bu sonuç 5X performans kabulü değildir. Ayrıntılar:
[canlı kampanya ve inceleme](docs/audits/2026-11-05-campaign.md).

P3 devamı: isteğe bağlı kısa CLI talimat profili, tek görevlik eşleşmiş
kalibrasyonda iki tarafta da doğrulanmış kabul sağlarken tokenı yaklaşık
%39,5 azalttı; süre bu örnekte arttı. Bu, yarı token veya 5X kabulü değildir.
[Kalibrasyon kaydı](docs/experiments/compact-cli-2026-11-05.md).

6 Kasım devamında beş alanlı örneklem tamamlandı: iki kolda da 4/5
doğrulanmış kabul, bir bütçe sonucu ve bir belirsiz çağrı var. Tam maliyet
oranı hesaplanamıyor; `accepted_5x=false`.
[Beş alanlı sonuçlar](docs/experiments/compact-five-domains-2026-11-06.md).
Kesinti sonrası gerçek çağrı/token hesabı, eski kimliksiz kullanımın özeti ve
belirsiz çağrıdan sonra varsayılan duruş düzeltildi. Manifestte görev sırası
artık açık; CLI varsayılanı her görevi tekrar etmeden önce bir kez dolaşır.

P2 devamı: gerçek Docker üzerinde açık ve tekrarlanan üç örnekte soğuk
önbellekle 15 doğrulama süreci 3'e indi (%80). Kaynak, kontrol ve timeout
değişimleri yeniden çalıştı; onaysız ve başarısız kontroller yeniden kullanılamadı.
Bu sentetik yük, tam matris veya üretim için P2 kabulü değildir.
[Ölçüm kaydı](docs/experiments/cache-probe-2026-11-06.md).
Sonraki ortam kimliği düzeltmesi seçilen imajı, daemon/kernel/sürüm/güvenlik
özelliklerini ve yürütme komutunu da kanıta bağladı. Eksik metadata eski kanıtı
kullandıramaz. Kimlik sorguları dahil güncel toplam CLI süreci 45'ten 33'e
indi (%26,7); %80 yalnızca doğrulama konteynerleri için geçerlidir.
Gerçek Docker'da daha sıkı PID politikası ve erişilemeyen bağlam regresyonları
da geçti. [Güncel ölçüm](docs/experiments/cache-runtime-probe-2026-11-06.md).
P4 devamında hata paketi, hatanın görüldüğü ortam/politika kimliğine bağlandı.
Kapıdan yakalanan gerçek Docker hatası dosya azaltmaya kadar aynı kimlikle
taşındı. Farklı ortamda replay engellenir; kimliksiz eski paketler açık izin
gerektirir ve ortamı doğrulanmamış sonuç üretir. Bu, P4'ün beceri başarısı ve
hata turu azalması hedeflerinin ölçüldüğü anlamına gelmez.
Beceri yayımlaması test edilmiş metin ve metadata kopyasından yapılır;
staging değişikliği canlıya sızamaz. Yeni sürüm taşınamazsa eski sürüm geri
konur; geri alma da başarısızsa kurtarma dizininde korunur. Onarım kapısı
yalnızca gerçek `True` kabul eder; oracle iptali yayımlama kilidinde yeniden
denetlenir. Çökme sonrası otomatik kurtarma henüz sağlanmıyor.
Yeni yayımlamalarda işlem kaydı ve dosya/dizin eşitlemesi var.
`skills recover-publications` kayıtları inceler; `--apply` yalnızca hedefi
eksik, özetleri eşleşen ve iptal edilmemiş eski sürümü geri koyar. Gerçek alt
süreç kesintisi testleri geçti. Bu araç açılışta otomatik kurtarma veya tüm
depolama hatalarında atomiklik garantisi değildir.

P3 için ortak kısa CLI profiliyle yeni beş alanlı eşleşmiş koşu tamamlandı.
İki kolda da 5/5 doğrulanmış kabul, 150'şer tamamlanmış çağrı var; token
958.593'ten 957.583'e indi (%0,105). 17 ajanlık bu yapı yarı token hedefini
sağlamadı; tüm görevlerde üretici sayısı aynı kaldı. Bu sonucu 120 ajana
genellemek veya önceki profille çarparak 5X ilan etmek geçerli değildir.
[Uyarlama ölçümü](docs/experiments/adaptive-compact-five-domains-2026-11-06.md).

Uyarlamalı Python akışı, aynı tanımlı Docker ortamında bütün kontrolleri geçen
adayları ayrı değerlendirir. Kapı bulgusu olmayan aday, kendi çapraz eleştirisi
somut kusur veya başka adaydan alınacak iyileştirme bulamadığını açıkça
bildirdiğinde yeniden teste geçer. Bulgusu olan veya belirsiz cevap alan aday
revize edilir. Atlanan yazar çağrıları `revision_calls_avoided`
olarak raporlanır. Gerçek Docker regresyonu hatalı entegrasyonun son onaya
ulaşmadığını doğrular. İlk canlı kalibrasyonda `left_join` iki kolda doğrulandı.
Adaydaki bir kapı bulgusu normal revizyonu korudu. `group_totals` takibinde
yapılandırılmış eleştiri çalıştı ve bir iyileştirme önerisi revizyonu tetikledi.
Önceki iki kalibrasyonda revizyon atlanmadı. Aday bazında kararın sonraki
`group_totals` takibinde iki kol da doğrulandı. Bir yazar çağrısı atlandı ve
toplam token kullanımı %3,73 azaldı. Temsili yük ve yarı token hedefi açık.
[Aday bazında kalibrasyon](docs/experiments/per-candidate-revision-2026-11-06.md).

P0 hazırlığında sabit Docker imajıyla birlikte gerçek doğrulama ortamının
parmak izi de dondurulur. Görev boyunca ortam uyuşmazlığı koşuyu keser ve
çağrı kayıtları korunur. Gerçek Docker üzerinde 50 görev × 5 tekrar, iki kol
için aynı ortam kimliğiyle hazırlandı. Bu hazırlıkta model çağrısı yapılmadı.
[Deney hazırlığı](docs/imece-cli.md).
P1'de sırada bekleyen çağrıların kabul kontrolleri gönderim anına taşındı;
önceki çağrı bütçeyi tüketince veya belirsiz kalınca yeni çağrı başlatılmaz.

Yerel uygulamada sürümlü görev kümesi, gizli yürütülebilir oracle, deney manifesti
ve rapor karşılaştırma kapısı; bütçe rezervasyon defteri, kalıcı aşama/çağrı
günlüğü ve tamamlanan yanıtları yeniden kullanarak devam etme; deterministik,
digest ile sabitlenmiş Docker doğrulaması için kanıt önbelleği bulunuyor.
İlk turda isteğe bağlı uyarlanan üretim, hata çıktısıyla aday onarımı,
bağlam/seçenek/kanıta bağlı emsaller, hata arşivi ve bağımsız kontrollerden sonra
beceri yükseltme/iptal akışları da kodda mevcut. Bunlar P0–P4 kapsamının bütünüyle
tamamlandığı veya performans hedeflerinin sağlandığı anlamına gelmez.

Deney yürütücüsü [`evals/imece/run.py`](evals/imece/run.py) **yalnızca Codex veya
Antigravity CLI** kullanır (`--engine codex|antigravity`, açık `--model`);
ham sağlayıcı API'si üzerinden çalışmaz. `--prepare` model çağrısı yapmadan
hazırlık kaydı üretir. Oracle erişim koruması şu anda macOS `sandbox-exec`
gerektirir. CLI raporlarında dolar maliyeti `null`/bilinmiyor olarak kalır;
abonelikten token fiyatı türetilmez. Token sınırı tamamlanan çağrılar üzerinden
izlenir; çağrı başına kesin çıktı token sınırı uygulanmaz. Varsayılan olarak üretim havuzu, konsey ve onay aynı modeli kullanır.
Koltuklara ayrı model atanabilir; bağımsızlık için denetçinin model kökeni kanıtı gerekir. Sağlayıcı rezervasyon defterinin kodda bulunması, bu CLI
koşularında doğrulanmış dolar muhasebesi olduğu anlamına gelmez.

`core-v1`, üretimi temsil ettiği henüz gösterilmemiş sınırlı Python görevlerinden
oluşur. Temsili baseline, sürüm başına en az 50 görev × 5 tekrar, tam maliyet
muhasebesi, karşılaştırmalı başarı/maliyet dağılımları, güven aralıkları ve
bağımsız denetim henüz tamamlanmadı. CLI raporlarının bilinmeyen maliyet ve
bağımsızlık uyarıları mevcut karşılaştırma kapısında 5X kabulünü engeller.
%60 doğrulama azalması, yarıya inen token/onarım maliyeti ve toplam 5X kazanç
ölçülmüş sonuçlar değildir. Başlangıç kanıtları:
[tamamlanma incelemesi](docs/completion.md); yerel onarım akışları ve ölçüm sınırı:
[onarım akışı](docs/imece-repairs.md).

## Ölçülebilir hedef

Ana hedef **aynı bütçeyle 5 kat fazla dış referans testlerini geçen kabul edilmiş
sonuç** üretmek. Hız, fiyat veya ajan sayısı tek başına başarı sayılmaz.

Mevcut tek başarılı `clamp` koşusu yaklaşık $0,546 tutmuştur; $0,109 bunun
aritmetik beşte biridir, ancak tek örnek gerçek bir baseline değildir. Önce
temsili veri kümesinde baseline dondurulur, sonra oran ölçülür.

Korunacak koşullar: değişmeyen dış oracle; sıfır gözlenen yanlış kabul; doğrulanmış
başarı oranında en fazla 2 yüzde puanı düşüş; belirsiz maliyetin sıfır gibi
sayılmaması; ret/durma/yeniden deneme giderlerinin toplam maliyete katılması.

## P0 — Ölçüm zemini ve bağımsız kontrol

- 50 farklı görev: kod, hata düzeltme, veri dönüşümü, entegrasyon, kanıtlı analiz.
  Her görevde kamuya açık sözleşme ve ajanlardan saklanan ayrı oracle bulunur.
- Sabit model kimlikleri, runtime/image digest'leri, konfigürasyon, seed ve
  sürüm kaydı; 5 tekrar. Yeni sistem ve baseline aynı şartlarda çalışır.
- Docker izolasyonu, iptal temizliği ve bozuk sağlayıcı cevapları CI kapısı olur.
- Aynı protokole Hermes adaptörü ve bağımsız denetçi incelemesi eklenir.

**Çıkış:** yeniden üretilebilir baseline, maliyet/başarı dağılımları ve hata
sınıfları. 250 koşuluk deney bütçesi önceden belirlenir; bu dosya deneyleri
otomatik başlatmaz.

## P1 — Bütçesi olan görev grafiği

Her aşama girdileri, çıktı hash'leri, model ve doğrulama kanıtları olan kalıcı bir
DAG düğümüne dönüşür. Kesilen koşu son tamamlanan düğümden devam eder.

- Model çağrısı başlamadan input/output ve dolar rezervasyonu; paralel çağrıların
  hepsi aynı rezervasyon defterinden yer alır. Fiyat bilinmiyorsa katı dolar
  bütçeli koşu başlamaz.
- Tekil çağrı kimliği, ücret durumu `known/unknown`, sağlayıcı zaman aşımı ve
  güvenli tekrar politikası; belirsiz faturayı silip yeni çağrı gibi gösterme yok.
- İnsan durdurduğunda bekleyen işler başlatılmaz; çalışanlar iptal edilir ve
  tamamlanmamış işlerin durumu açıkça kaydedilir.

**Çıkış:** kesintiden sonra tamamlanan işler tekrarlanmadan devam; eşzamanlı
rezervasyon testlerinde bütçe aşımı yok; bilinmeyen ücret ayrı raporlanır.

## P2 — Kanıt kimliği ve artımlı doğrulama

Çözüm + oracle + çalışma ortamı + politika + kaynak sınırları tek kanıt kimliği
oluşturur. Çıktı aynıysa geçerli kanıt yeniden kullanılır; değiştiyse etkilenen
kontroller tekrar çalışır.

- Deterministik olmayan testlerde cache kapalıdır. Ortam, oracle veya politika
  değişirse önceki kanıt geçersizdir.
- Kod farkı, başarısız test ve traceback üzerinden küçük onarım görevleri;
  bütün çözümün her tur baştan yazılması azalır.
- Çalışmayan/yanlış oracle, çözüm hatasından ayrı sınıflandırılır. Oracle değişimi
  yeni bir doğrulama sözleşmesi sayılır; önceki sonuçla sessizce kıyaslanmaz.

**Çıkış:** tekrarlanan iş yükünde doğrulama çağrılarında en az %60 düşüş;
oracle/ortam değişikliklerinin %100 cache invalidation regresyonu.

## P3 — Uyarlanan İmece

120 ajanı her işe aynı biçimde dağıtmak yerine küçük bir keşif turu belirsizliği
ölçer. Ek ajanlar ölçülen belirsizliği azaltacak işlere gider.

- Ucuz üretim + güçlü bağımsız doğrulama; başarısızlık türüne göre model yükseltme.
- Yaklaşım çeşitliliği, yeni bulunan hata ve test kapsamına göre üretim havuzunu
  büyütme/durdurma. Marjinal faydası kalmayan yeni adaylar üretilmez.
- Konsey önüne tam çözüm yerine sözleşme, çalıştırılmış kanıt ve gerçek karar
  farkı gelir. Veto ve bağımsız kapılar korunur.
- Emsaller bağlam/seçenek/kanıt kimliğine bağlıdır; soru metni aynı diye değişmiş
  seçenekler eski kararı miras almaz. Rastgele denetim açık kalır.

**Çıkış:** doğrulanmış sonuç başına token maliyeti en az yarıya iner; aynı dış
oracle ve yanlış-kabul sınırı korunur.

## P4 — Hata arşivinden doğrulanmış beceri

Başarısızlıklar kısa bir hata açıklaması, minimal yeniden üretim ve onarım
şablonuna dönüştürülür. Bir beceri birden fazla bağımsız görevde tekrar
çalışmadan canlı beceri kitaplığına geçmez.

- Beceri kaynağı, hangi görevlerde işe yaradığı ve geçersizleşme koşulları görünür.
- Aday beceriler önce staging'de kalır; kaynak iptali bağlı becerileri de etkiler.
- T0 yetkisi, onay politikası ve güvenlik kuralları beceri öğrenmesiyle değişmez.

**Çıkış:** tekrar eden hata ailelerinde başarısız tur sayısı en az yarıya iner;
beceri kullanan görevlerde dış oracle başarısı gerilemez.

## P5 — 5X kabul kapısı

Baseline ve adayın tüm koşuları (başarısızlar dahil) yayımlanabilir bir yerel
raporda birleştirilir. Sadece başarılı örnekler seçilmez. Entegre iyileşmeler
çarpılarak tahmini 5X ilan edilmez; toplam sonuç doğrudan ölçülür.

Kabul: doğrulanmış sonuç/dolar ≥ baseline × 5; başarı oranı sınırı ve sıfır
gözlenen yanlış kabul korunmuş; en az 250 koşu/sürüm; güven aralıkları raporlanmış;
bağımsız denetimde açık kritik bulgu kalmamış. Sağlanmazsa sonuç ve başarısızlık
nedeni kaydedilir, **5X iddiası yapılmaz**.
