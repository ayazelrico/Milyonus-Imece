# İmece ve ajan çekirdeği — tamamlanma değerlendirmesi

Tarih: **2 Kasım 2026**. Kapsam: İmece ve ajan çekirdeği. Kullanıcının seçimi
gereği `PLAN-WEB.md` bu çalışmaya dahil değildir.

## Başlangıçtaki durum

Sistem bitmiş değildi. README'nin İmece kontrol listesinde 13 maddeden 9'u
işaretliydi; açık 4 madde gerçek modelle kabul edilmiş çıktı, izole test
yürütme, büyük ölçek için hiyerarşi ve İmece benchmark'ıydı. Bu bir iş yükü
yüzdesi değildir: açık maddeler sistemin doğruluk iddiası için kritikti.

İlk yerel doğrulamada **306 test geçti**. Ancak testlerin geçmesi şu gerçek
açıkları yakalamıyordu:

- Eksik/tekrarlı veya `"false"` gibi metin biçimindeki test cevapları geçiş
  oranını yükseltebiliyordu; bozuk denetim cevabı temiz rapor sayılabiliyordu.
- Revize ve cilalanmış çözümler önceki sürümün test kanıtını kullanabiliyordu.
- Çapraz eleştirmen ve revize eden ajan donmuş problem tanımını almıyordu.
- Konseye sunulan çözüm kırpıldığında sonuna eklenen bağımsız kanıt kayboluyordu.
- Çekirdek döngünün varsayılan onayı açıktı; RiskEngine tüm giriş noktalarında
  zorunlu değildi. ACP iptali etkisizdi ve editör izin protokolü eksikti.
- Becerilerin varsayılan yeniden üretim kapısı koşulsuz kabul ediyordu.
- Aynı T3 kaydını tekrar işlemek yeni bağımsız teyit sayılıyordu.
- Model hafıza doğrulayıcısının hatası kural tabanlı onaya dönüşebiliyordu.
- Selfmod test kapısı doctor hatasını başarısızlık saymıyordu.

## Tamamlanan teknik işler

| Alan | Uygulama ve kanıt |
|---|---|
| Gerçek test yürütme | `--verification python`: her test ayrı izole Python sürecinde; Docker ve macOS geliştirme arka uçları; hata/eksik ortam geçiş sağlamaz |
| Test kanıtının bütünlüğü | Eksik/tekrarlı/yanlış tipli oylar reddedilir; kritik denetim hatası kapıyı kapatır; değişen çıktı tekrar test edilir |
| Kör onay | Koşullu cevap tek başına kabul sayılmaz; kabul için açık kabul çoğunluğu gerekir |
| Kapsamın korunması | Çapraz eleştiri ve revizyon aynı donmuş çerçeveyi alır; kapsam dışı varsayım ihlalleri kritik sözleşme hatası sayılmaz |
| Konsey | Kanıt ayrı alanda korunur; sayısal oylar sonlu ve 0..1 aralığında olmalıdır; tam konsey eşikleri sıkılaştırılır |
| Hiyerarşi | 7–12 üyelik komuta hücreleri (son hücre daha küçük olabilir), üst hücreler ve katmanlı plan seçimi; ilk birkaç plan dışında kalanlar atılmaz |
| Ölçek yürütme | Ajan başına bekleyen asyncio görevi yerine sınırlı işçi havuzu, sıra korunumu, zaman aşımı ve iptal temizliği |
| Benchmark | Kabul ve dış referans doğruluğu ayrı ölçülür; token, maliyet, kabul başına maliyet ve kalibrasyon raporlanır |
| Çekirdek güvenlik | Varsayılan ret; bütün araçlar RiskEngine'den geçer; hard block onayla aşılamaz; kimlik dosyası okuma onay gerektirir |
| ACP | Tek kullanımlık editör izni, bilinmeyen izin seçeneğine ret, çalışan model çağrısını iptal |
| Shell | Docker ayarı CLI/gateway/ACP/scheduler'a bağlanır; ağ kapalı, kaynak sınırları, yalnız çalışma alanı mount edilir; desteklenmeyen adaptör yerel shell'e düşmez |
| Beceriler | Gerçek izole Python örneği + assertion yeniden yürütmesi; doğrulanmamış beceri staging'de kalır; dizin kaçışı engellenir |
| Hafıza | Kaynağa bağlı ve yinelenmeyen teyitler; ek teyit kaynağı iptal zincirine dahil; bekleyen kayıt TTL'si tekrar işlemeyle uzamaz |
| Model doğrulayıcı | Bozuk/ulaşılamayan doğrulayıcı onay vermez; geçici hata karantinada kalır, olumsuz hafızaya yanlış bilgi eklemez |
| Selfmod | Kendi kaynaklarına araçla yazma snapshot/test/doctor/rollback kapısından geçer; yeni dosyalar da rollback'e dahil; sonraki başlangıç açık kabul/rollback bekler |

## Doğrulama

### Gerçek modelle kabul edilmiş çıktı

[`2026-11-02-final-clamp.json`](trials/2026-11-02-final-clamp.json):

- 17 ajan dağılımı, 5 farklı model ailesinden konsey ve ayrı onay modeli.
- Tek turda `accepted`; İRADE Kademe 2; insan müdahalesi yok.
- Son çıktı 12 bağımsız tasarlanmış testi macOS izolasyonunda gerçekten geçti.
- Ajanlara gösterilmeyen ek referans kontrolü de geçti.
- 83.048 token; katalog token fiyatlarıyla **yaklaşık $0,546**.

Bu **tek görevin tek koşusudur**. Genelleştirilmiş başarı oranı, 10.000 gerçek
ajanın performansı veya üretim güvenilirliği olarak yorumlanamaz. Diğer gerçek
denemelerin başarısız raporları da `docs/trials/` altında tutulmuştur.

Ek [`iki görevlik koşuda`](trials/2026-11-02-final-extended.json) kabul edilmiş
sonuç çıkmadı: `merge_intervals` konsey vetosuyla insan onayında durdu; `iban_tr`
OpenRouter'ın `in_flight_budget_exhausted` nedenli 402 hatalarıyla tamamlanamadı.
Bu sonuçlar saklanır; ilk başarılı örnek üzerinden genel %100 başarı iddiası yoktur.

### Ölçek

[`2026-11-02-scale-fake.json`](trials/2026-11-02-scale-fake.json) 10.000 ajan
dağılımındaki tam akışı deterministik sahte ajanlarla sınar. Bu, gerçek model
kalitesi veya hizmet sağlayıcı kapasitesi ölçümü değildir.

### Hafıza

[`2026-11-02-final-memory.json`](trials/2026-11-02-final-memory.json): ayrı gerçek model
doğrulayıcıyla held-out 8 saldırıda 0 kalıcı terfi, 4 meşru örnekte 4 terfi.
Train setindeki meşru örneklerden biri reddedildi. Bu küçük küme garanti değildir.
Kural tabanlı mod tek başına aynı held-out saldırılarda **%50 ASR** verdi;
yalnız regex tarayıcı için %0 iddiasında bulunulmamalıdır.

### Yerel kontroller

Son yerel sonuç **371 passed, 1 skipped**. `make check` lint, biçim ve bütün testleri çalıştırır; `uv build` wheel/sdist
üretimini doğrular. `make safety` hard-block politikalarını sınar. Docker entegrasyon
testi CI'ya eklenmiştir; bu bilgisayarda Docker olmadığı için yerel çalıştırmada
açıkça atlanır. macOS entegrasyon testi gerçekten çalışır. CLI, gateway ve ACP,
aynı bağımsız model doğrulayıcı kurulumunu kullanır; grup mesajının T3 tavanı
modelin `source_kind` alanıyla yükseltilemez.

## Tamamlanmanın sınırı

**İmece'nin açık dört teknik yol haritası maddesi artık uygulanmış ve bir gerçek
model kabulüyle desteklenmiştir. Ürün deneysel durumdadır.**

Henüz doğrulanmamış veya dış çalışma gerektiren işler:

1. Docker entegrasyon işinin gerçek CI/daemon üzerinde sonucu. Yapılandırıldı;
   burada çalıştırıldığı iddia edilmez.
2. Büyük, tekrarlı gerçek model benchmark'ı, yük altında dayanıklılık ve fatura
   doğrulaması. Maliyet rakamları token fiyatı hesabıdır, fatura değildir.
3. Hermes ile aynı modeller/araçlar/bütçe/görevlerle karşılaştırmalı çalışma ve
   bağımsız üçüncü taraf güvenlik denetimi.
4. SSH/Modal/Daytona shell adaptörleri uygulandı (`security/sandbox/backends.py`);
   kimlik bilgisi yoksa fail-closed (yerel shell'e düşmez). Doctor durumu raporlar.
   Modal/Daytona v1 komut odaklıdır; tam workspace senkronu sonraki sertleştirmedir.
5. Model-judged modun gerçek test yürütmesiyle aynı güvenceyi vermemesi;
   `verification="python"` kod işleri için açıkça seçilmelidir.
6. Paylaşılan token sınırı tamamlanan çağrılar üzerinden izlenir; uçuş halindeki
   paralel çağrılar sınırı aşabilir. Katı maliyet rezervasyonu sonraki plandadır.

Bu nedenle **"üretim için eksiksiz ve bağımsız denetlenmiş sistem" denemez**.
Sonraki ölçülebilir geliştirme planı: [`PLAN-5X.md`](../PLAN-5X.md).
